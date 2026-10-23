class TenantScopedMixin:
    """
    Restrict a generic view's queryset to the requesting user's tenant.

    Set `tenant_field` when the tenant is reached through a relation
    (e.g. 'plan__tenant'). Users without a tenant see nothing.
    """
    tenant_field = 'tenant'

    def get_queryset(self):
        queryset = super().get_queryset()
        tenant_id = self.request.user.tenant_id
        if tenant_id is None:
            return queryset.none()
        return queryset.filter(**{f"{self.tenant_field}_id": tenant_id})
