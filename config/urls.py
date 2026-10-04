from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static


def root_redirect(request):
    if request.user.is_authenticated:
        return redirect('accounts:role_redirect')
    return redirect('accounts:login')


from core.views import PWAManifestView, PWAServiceWorkerView

urlpatterns = [
    path('', root_redirect, name='root'),
    path('manifest.json', PWAManifestView.as_view(), name='pwa_manifest'),
    path('sw.js', PWAServiceWorkerView.as_view(), name='pwa_sw'),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('stores/', include('stores.urls', namespace='stores')),
    path('dashboard/', include('dashboard.urls', namespace='dashboard')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('billing/', include('billing.urls', namespace='billing')),
    path('core/', include('core.urls', namespace='core')),
]

from django.urls import re_path
from django.views.static import serve

urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

