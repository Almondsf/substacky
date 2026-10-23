from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication


class TenantJWTAuthentication(JWTAuthentication):
    """JWT auth that rejects users acting on a tenant (from TenantMiddleware) they don't belong to."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        tenant = getattr(request, 'tenant', None)
        if tenant is not None and user.tenant_id != tenant.id and not user.is_superuser:
            raise PermissionDenied('You do not belong to this tenant.')
        return user, token
