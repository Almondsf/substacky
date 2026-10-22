from rest_framework.permissions import BasePermission
from apps.accounts.models import CustomUser


class IsTenantAdmin(BasePermission):
    
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.tenant_id is not None
            and request.user.role == CustomUser.Role.ADMIN
        )
