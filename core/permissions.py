from rest_framework.permissions import BasePermission
from apps.accounts.models import CustomUser


class IsTenantAdmin(BasePermission):
    
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.tenant_id is not None
            and request.user.role == CustomUser.Role.ADMIN
        )


class HasActiveSubscription(BasePermission):
    """
    Gate a view behind an active subscription.

    Set `required_plans` on the view (Plan ids) to require specific plans;
    otherwise any active subscription in the user's tenant grants access.
    """
    message = 'An active subscription is required.'

    def has_permission(self, request, view):
        from apps.subscriptions.access import has_active_subscription
        return has_active_subscription(request.user, getattr(view, 'required_plans', None))
