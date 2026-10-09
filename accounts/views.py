from django.contrib.auth import login, logout
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.core.exceptions import PermissionDenied

from django.db.models import Q
from accounts.models import User
from accounts.forms import (
    LoginForm, StaffCreationForm, StaffUpdateForm,
    StoreAdminCreationForm, StoreAdminUpdateForm, UserProfileForm
)
from core.mixins import RoleRequiredMixin


class UserLoginView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        login(self.request, user)
        messages.success(self.request, f"Welcome back, {user.display_name}!")
        return redirect('accounts:role_redirect')


class UserLogoutView(View):
    def post(self, request, *args, **kwargs):
        logout(request)
        messages.info(request, "You have been logged out.")
        return redirect('accounts:login')

    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs)


class RoleRedirectView(LoginRequiredMixin, View):
    """Dispatches users directly to their dedicated role dashboard."""
    def get(self, request, *args, **kwargs):
        role = request.user.role
        if role == User.Role.SUPER_ADMIN or request.user.is_superuser:
            return redirect('dashboard:super_admin_dashboard')
        elif role == User.Role.STORE_ADMIN:
            return redirect('dashboard:store_admin_dashboard')
        elif role == User.Role.STAFF:
            return redirect('dashboard:staff_dashboard')
        else:
            messages.error(request, "Unknown user role.")
            return redirect('accounts:login')


class UserProfileView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = UserProfileForm
    template_name = 'accounts/profile.html'
    success_url = reverse_lazy('accounts:profile')

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Profile updated successfully.")
        return super().form_valid(form)


# Store Admin: Staff Management
class StaffListView(RoleRequiredMixin, ListView):
    model = User
    template_name = 'accounts/staff_list.html'
    context_object_name = 'staff_members'
    allowed_roles = [User.Role.STORE_ADMIN]
    paginate_by = 25

    def get_paginate_by(self, queryset):
        per_page = self.request.GET.get('per_page', '').strip()
        if per_page in ['20', '25', '50', '100']:
            return int(per_page)
        return 25

    def get_queryset(self):
        qs = User.objects.filter(
            store=self.request.user.store,
            role=User.Role.STAFF
        )
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        sort = self.request.GET.get('sort', 'latest').strip()

        if q:
            qs = qs.filter(
                Q(username__icontains=q) |
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(email__icontains=q) |
                Q(phone__icontains=q)
            )
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        if sort == 'oldest':
            qs = qs.order_by('date_joined')
        elif sort == 'name_asc':
            qs = qs.order_by('first_name', 'last_name', 'username')
        else:
            qs = qs.order_by('-date_joined')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = User.objects.filter(store=self.request.user.store, role=User.Role.STAFF)
        context['total_staff_count'] = base_qs.count()
        context['active_staff_count'] = base_qs.filter(is_active=True).count()
        return context


class StaffCreateView(RoleRequiredMixin, CreateView):
    model = User
    form_class = StaffCreationForm
    template_name = 'accounts/staff_form.html'
    success_url = reverse_lazy('accounts:staff_list')
    allowed_roles = [User.Role.STORE_ADMIN]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['store'] = self.request.user.store
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f"Staff member '{form.instance.username}' created successfully.")
        return super().form_valid(form)


class StaffUpdateView(RoleRequiredMixin, UpdateView):
    model = User
    form_class = StaffUpdateForm
    template_name = 'accounts/staff_form.html'
    success_url = reverse_lazy('accounts:staff_list')
    allowed_roles = [User.Role.STORE_ADMIN]

    def get_queryset(self):
        return User.objects.filter(store=self.request.user.store, role=User.Role.STAFF)

    def form_valid(self, form):
        messages.success(self.request, f"Staff '{form.instance.username}' updated.")
        return super().form_valid(form)


class StaffToggleActiveView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.STORE_ADMIN, User.Role.SUPER_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        if request.user.role == User.Role.SUPER_ADMIN:
            staff = get_object_or_404(User, pk=pk, role=User.Role.STAFF)
            redirect_url = 'accounts:all_staff_list'
        else:
            staff = get_object_or_404(User, pk=pk, store=request.user.store, role=User.Role.STAFF)
            redirect_url = 'accounts:staff_list'
        staff.is_active = not staff.is_active
        staff.save(update_fields=['is_active'])
        status_str = "activated" if staff.is_active else "deactivated"
        messages.success(request, f"Staff member '{staff.username}' {status_str}.")
        return redirect(redirect_url)


# Super Admin: Store Admin User Management
class StoreAdminListView(RoleRequiredMixin, ListView):
    model = User
    template_name = 'accounts/store_admin_list.html'
    context_object_name = 'store_admins'
    allowed_roles = [User.Role.SUPER_ADMIN]
    paginate_by = 20

    def get_queryset(self):
        qs = User.objects.filter(role=User.Role.STORE_ADMIN).select_related('store')
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        store_id = self.request.GET.get('store', '').strip()
        assignment = self.request.GET.get('assignment', '').strip()
        sort = self.request.GET.get('sort', 'latest').strip()

        if q:
            qs = qs.filter(
                Q(username__icontains=q) |
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(email__icontains=q) |
                Q(phone__icontains=q) |
                Q(store__name__icontains=q) |
                Q(store__code__icontains=q) |
                Q(store__city__icontains=q)
            )

        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        if assignment == 'assigned':
            qs = qs.filter(store__isnull=False)
        elif assignment == 'unassigned':
            qs = qs.filter(store__isnull=True)

        if store_id:
            qs = qs.filter(store_id=store_id)

        if sort == 'oldest':
            qs = qs.order_by('date_joined', 'id')
        elif sort == 'username_asc':
            qs = qs.order_by('username')
        elif sort == 'username_desc':
            qs = qs.order_by('-username')
        elif sort == 'store':
            qs = qs.order_by('store__name', 'username')
        else:  # latest
            qs = qs.order_by('-date_joined', '-id')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from stores.models import Store
        all_admins = User.objects.filter(role=User.Role.STORE_ADMIN)
        context['total_admins_count'] = all_admins.count()
        context['active_admins_count'] = all_admins.filter(is_active=True).count()
        context['inactive_admins_count'] = all_admins.filter(is_active=False).count()
        context['unassigned_admins_count'] = all_admins.filter(store__isnull=True).count()
        context['stores_list'] = Store.all_objects.filter(is_active=True).order_by('name')
        return context


class StoreAdminCreateView(RoleRequiredMixin, CreateView):
    model = User
    form_class = StoreAdminCreationForm
    template_name = 'accounts/store_admin_form.html'
    success_url = reverse_lazy('accounts:store_admin_list')
    allowed_roles = [User.Role.SUPER_ADMIN]

    def form_valid(self, form):
        raw_password = form.cleaned_data.get('password')
        response = super().form_valid(form)
        user = self.object

        from core.emails import send_store_admin_welcome_email
        email_sent, email_msg = send_store_admin_welcome_email(user, raw_password, request=self.request)
        if email_sent:
            messages.success(
                self.request,
                f"Store admin '{user.username}' created! A professional onboarding email with login credentials was sent to {user.email}."
            )
        elif user.email:
            messages.warning(
                self.request,
                f"Store admin '{user.username}' created successfully, but welcome email could not be sent ({email_msg}). You can configure SMTP in Platform Settings."
            )
        else:
            messages.success(
                self.request,
                f"Store admin '{user.username}' created for store '{user.store.name if user.store else ''}'."
            )
        return response


class StoreAdminUpdateView(RoleRequiredMixin, UpdateView):
    model = User
    form_class = StoreAdminUpdateForm
    template_name = 'accounts/store_admin_form.html'
    success_url = reverse_lazy('accounts:store_admin_list')
    allowed_roles = [User.Role.SUPER_ADMIN]

    def get_queryset(self):
        return User.objects.filter(role=User.Role.STORE_ADMIN)

    def form_valid(self, form):
        pw_changed = bool(form.cleaned_data.get('new_password'))
        new_password = form.cleaned_data.get('new_password')
        response = super().form_valid(form)
        user = self.object

        msg = f"Store admin '{user.username}' updated."
        if pw_changed:
            msg += " Password has been updated successfully."
            # Optionally send updated credentials email if user has email
            if user.email:
                from core.emails import send_store_admin_welcome_email
                email_sent, email_msg = send_store_admin_welcome_email(user, new_password, request=self.request)
                if email_sent:
                    msg += f" An updated credentials email was dispatched to {user.email}."
        messages.success(self.request, msg)
        return response


class ResendStoreAdminWelcomeEmailView(RoleRequiredMixin, View):
    """
    Super Admin manually triggering or resending store admin welcome email.
    Generates a fresh login password, updates user credentials, and emails it.
    """
    allowed_roles = [User.Role.SUPER_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        admin_user = get_object_or_404(User, pk=pk, role=User.Role.STORE_ADMIN)
        if not admin_user.email:
            messages.error(request, f"Store admin '{admin_user.username}' does not have an email address configured.")
            return redirect('accounts:store_admin_list')

        import secrets
        import string

        # Generate a strong readable password or use provided one
        custom_password = (request.POST.get('password') or '').strip()
        if custom_password:
            new_password = custom_password
        else:
            chars = string.ascii_letters + string.digits + "!@#$%"
            new_password = ''.join(secrets.choice(chars) for _ in range(10))

        # Update and save the active password for this store admin
        admin_user.set_password(new_password)
        admin_user.save(update_fields=['password'])

        from core.emails import send_store_admin_welcome_email
        email_sent, email_msg = send_store_admin_welcome_email(
            admin_user,
            raw_password=new_password,
            request=request
        )
        if email_sent:
            messages.success(
                request,
                f"New password generated ({new_password}) and credentials email sent to {admin_user.email}."
            )
        else:
            messages.warning(
                request,
                f"Password was updated to '{new_password}', but email could not be sent: {email_msg}"
            )

        return redirect('accounts:store_admin_list')


# Super Admin: Store Staff Management (All stores staff list)
class AllStaffListView(RoleRequiredMixin, ListView):
    model = User
    template_name = 'accounts/all_staff_list.html'
    context_object_name = 'staff_members'
    allowed_roles = [User.Role.SUPER_ADMIN]
    paginate_by = 20

    def get_queryset(self):
        qs = User.objects.filter(role=User.Role.STAFF).select_related('store')
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()
        store_id = self.request.GET.get('store', '').strip()
        sort = self.request.GET.get('sort', 'latest').strip()

        if q:
            qs = qs.filter(
                Q(username__icontains=q) |
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(email__icontains=q) |
                Q(phone__icontains=q) |
                Q(store__name__icontains=q) |
                Q(store__code__icontains=q) |
                Q(store__city__icontains=q)
            )

        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        if store_id:
            qs = qs.filter(store_id=store_id)

        if sort == 'oldest':
            qs = qs.order_by('date_joined', 'id')
        elif sort == 'username_asc':
            qs = qs.order_by('username')
        elif sort == 'username_desc':
            qs = qs.order_by('-username')
        elif sort == 'name_asc':
            qs = qs.order_by('first_name', 'last_name', 'username')
        elif sort == 'store':
            qs = qs.order_by('store__name', 'username')
        else:  # latest
            qs = qs.order_by('-date_joined', '-id')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from stores.models import Store
        all_staff = User.objects.filter(role=User.Role.STAFF)
        context['total_staff_count'] = all_staff.count()
        context['active_staff_count'] = all_staff.filter(is_active=True).count()
        context['inactive_staff_count'] = all_staff.filter(is_active=False).count()
        context['stores_represented_count'] = all_staff.filter(store__isnull=False).values('store').distinct().count()
        context['stores_list'] = Store.all_objects.filter(is_active=True).order_by('name')
        return context


# Super Admin Impersonation Workflow (Login Without Password)
class ImpersonateUserView(RoleRequiredMixin, View):
    allowed_roles = [User.Role.SUPER_ADMIN]

    def post(self, request, pk, *args, **kwargs):
        target_user = get_object_or_404(User, pk=pk)

        # Do not allow impersonating yourself
        if target_user.pk == request.user.pk:
            messages.info(request, "You are already logged in as yourself.")
            return redirect('accounts:store_admin_list')

        original_admin_id = request.user.pk

        # Login as target user without password
        target_user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, target_user)

        # Retain impersonation token in new session
        request.session['impersonator_id'] = original_admin_id
        request.session.modified = True

        store_name = target_user.store.name if target_user.store else "Unassigned Store"
        messages.warning(
            request,
            f"You are now impersonating {target_user.username} ({store_name}). All actions taken are within this account."
        )
        return redirect('accounts:role_redirect')


class ExitImpersonationView(View):
    def get(self, request, *args, **kwargs):
        return self._exit_impersonation(request)

    def post(self, request, *args, **kwargs):
        return self._exit_impersonation(request)

    def _exit_impersonation(self, request):
        impersonator_id = request.session.get('impersonator_id')
        if not impersonator_id:
            user = getattr(request, 'user', None)
            if user and getattr(user, 'is_authenticated', False) and (getattr(user, 'role', None) == User.Role.SUPER_ADMIN or getattr(user, 'is_superuser', False)):
                messages.info(request, "You are already in Super Admin mode.")
                return redirect('accounts:store_admin_list')
            messages.error(request, "No active impersonation session found.")
            return redirect('accounts:role_redirect')

        original_admin = User.objects.filter(pk=impersonator_id).first()
        if not original_admin:
            messages.error(request, "Original Super Admin account not found.")
            return redirect('accounts:login')

        original_admin.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, original_admin)

        if 'impersonator_id' in request.session:
            del request.session['impersonator_id']
        request.session.modified = True

        messages.success(request, f"Exited impersonation. Welcome back, {original_admin.username} (Super Admin).")
        return redirect('accounts:store_admin_list')


