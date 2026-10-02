import time
from importlib import import_module
from django.conf import settings
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.exceptions import SessionInterrupted
from django.utils.cache import patch_vary_headers
from django.utils.deprecation import MiddlewareMixin
from django.utils.http import http_date

from django.contrib.sessions.middleware import SessionMiddleware

PWA_SESSION_COOKIE_NAME = getattr(settings, 'PWA_SESSION_COOKIE_NAME', 'pwa_sessionid')
BROWSER_SESSION_COOKIE_NAME = getattr(settings, 'SESSION_COOKIE_NAME', 'sessionid')


def is_pwa_request(request):
    """
    Determines if the HTTP request originates from the installed PWA client.
    1. Query param: ?client=pwa or ?app=pwa (e.g. from PWA start_url)
    2. Header: X-App-Client: pwa or X-App-Mode: pwa
    3. Cookie presence: app_mode=pwa
    """
    if request.GET.get('client') == 'pwa' or request.GET.get('app') == 'pwa':
        return True
    if request.headers.get('X-App-Client') == 'pwa' or request.headers.get('X-App-Mode') == 'pwa':
        return True
    if request.COOKIES.get('app_mode') == 'pwa':
        return True
    return False


class PWASessionMiddleware(SessionMiddleware):
    """
    Security-hardened session isolation middleware for PWA vs Browser.
    Inherits from Django's SessionMiddleware for full admin compatibility.
    - Regular Browser: uses standard settings.SESSION_COOKIE_NAME ('sessionid')
    - Installed PWA: uses isolated PWA_SESSION_COOKIE_NAME ('pwa_sessionid')
    
    Prevents cross-session overwrite and keeps PWA logged in permanently
    without affecting or sharing logout/login with the regular browser.
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        engine = import_module(settings.SESSION_ENGINE)
        self.SessionStore = engine.SessionStore

    def process_request(self, request):
        is_pwa = is_pwa_request(request)
        cookie_name = PWA_SESSION_COOKIE_NAME if is_pwa else BROWSER_SESSION_COOKIE_NAME
        request._pwa_mode = is_pwa
        request._active_session_cookie_name = cookie_name

        session_key = request.COOKIES.get(cookie_name)
        request.session = self.SessionStore(session_key)

    def process_response(self, request, response):
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response

        cookie_name = getattr(request, '_active_session_cookie_name', BROWSER_SESSION_COOKIE_NAME)
        is_pwa = getattr(request, '_pwa_mode', False)

        # If PWA was detected via query param (?client=pwa), persist app_mode cookie
        # so subsequent navigations inside the standalone window know it's PWA
        if is_pwa and request.GET.get('client') == 'pwa':
            response.set_cookie(
                'app_mode',
                'pwa',
                max_age=31536000, # 1 year
                path=settings.SESSION_COOKIE_PATH,
                domain=settings.SESSION_COOKIE_DOMAIN,
                secure=settings.SESSION_COOKIE_SECURE or None,
                httponly=False, # Accessible by client PWA script if needed
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )

        # If session is empty (user logged out), delete the appropriate cookie
        if cookie_name in request.COOKIES and empty:
            response.delete_cookie(
                cookie_name,
                path=settings.SESSION_COOKIE_PATH,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
            need_vary_cookie = True
        else:
            need_vary_cookie = accessed
            if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
                if is_pwa:
                    # PWA gets long-lived persistent session (1 year)
                    max_age = getattr(settings, 'PWA_SESSION_COOKIE_AGE', 31536000)
                    expires_time = time.time() + max_age
                    expires = http_date(expires_time)
                else:
                    if request.session.get_expire_at_browser_close():
                        max_age = None
                        expires = None
                    else:
                        max_age = request.session.get_expiry_age()
                        expires_time = time.time() + max_age
                        expires = http_date(expires_time)

                if response.status_code < 500:
                    try:
                        request.session.save()
                    except UpdateError:
                        raise SessionInterrupted(
                            "The request's session was deleted before the request completed."
                        )
                    response.set_cookie(
                        cookie_name,
                        request.session.session_key,
                        max_age=max_age,
                        expires=expires,
                        domain=settings.SESSION_COOKIE_DOMAIN,
                        path=settings.SESSION_COOKIE_PATH,
                        secure=settings.SESSION_COOKIE_SECURE or None,
                        httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                        samesite=settings.SESSION_COOKIE_SAMESITE,
                    )
                    need_vary_cookie = True

        if need_vary_cookie:
            patch_vary_headers(response, ("Cookie",))
        return response
