from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages
from django.http import Http404


class RoleRequiredMixin(LoginRequiredMixin):
    """
    CBV mixin that verifies the user is authenticated and has one of the allowed roles.
    Example:
        allowed_roles = ['store_admin', 'staff']
    """
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Superuser always has full system access for administrative overrides if needed,
        # unless specifically blocked by store isolation.
        if request.user.is_superuser and 'super_admin' in self.allowed_roles:
            return super().dispatch(request, *args, **kwargs)

        user_role = getattr(request.user, 'role', None)
        if self.allowed_roles and user_role not in self.allowed_roles:
            messages.error(request, "You do not have permission to access this page.")
            # Redirect to role-appropriate home if possible
            if user_role == 'super_admin':
                return redirect('dashboard:super_admin_dashboard')
            elif user_role == 'store_admin':
                return redirect('dashboard:store_admin_dashboard')
            elif user_role == 'staff':
                return redirect('dashboard:staff_dashboard')
            raise PermissionDenied("Unauthorized role access.")

        return super().dispatch(request, *args, **kwargs)


class TenantAccessMixin(LoginRequiredMixin):
    """
    CBV mixin enforcing multi-tenant isolation:
    1. Users must have an assigned store (store_admin or staff).
    2. Super admins are strictly blocked from accessing store-owned records (bills, inventory, etc.).
    3. Automatically scopes get_queryset() to request.user.store.
    4. Automatically binds form.instance.store = request.user.store on creation.
    5. Validates single object lookups (get_object) belong to the active tenant.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        # Rule 1: super_admin cannot see bills or stock of any store
        if request.user.role == 'super_admin':
            messages.error(request, "Super admins cannot access store-specific data directly.")
            return redirect('dashboard:super_admin_dashboard')

        # Store-level users must have an active store assigned
        if not request.user.store or not request.user.store.is_active:
            messages.error(request, "Your account is not assigned to an active pharmacy store.")
            return redirect('accounts:login')

        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        """Scope the base queryset strictly to the current user's store."""
        qs = super().get_queryset()
        if hasattr(qs, 'for_store'):
            return qs.for_store(self.request.user.store)
        return qs.filter(store=self.request.user.store)

    def get_object(self, queryset=None):
        """Ensure the requested object belongs to the current user's store."""
        obj = super().get_object(queryset)
        if getattr(obj, 'store', None) != self.request.user.store:
            raise Http404("Record not found in this pharmacy store.")
        return obj

    def form_valid(self, form):
        """Automatically attach current user's store to newly created instances."""
        if hasattr(form.instance, 'store_id') and not form.instance.store_id:
            form.instance.store = self.request.user.store
        return super().form_valid(form)
