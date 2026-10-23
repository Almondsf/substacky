from django.conf import settings
from django.http import JsonResponse
from apps.tenants.models import Tenant

TENANT_HEADER = 'HTTP_X_TENANT'
RESERVED_SUBDOMAINS = {'www', 'api', 'admin'}


def tenant_slug_from_request(request):
    """The tenant slug from the X-Tenant header, or the subdomain of TENANT_BASE_DOMAIN."""
    slug = request.META.get(TENANT_HEADER, '').strip()
    if slug:
        return slug.lower()

    base_domain = settings.TENANT_BASE_DOMAIN
    if not base_domain:
        return None
    host = request.get_host().split(':')[0].lower()
    suffix = f".{base_domain}"
    if host.endswith(suffix):
        subdomain = host[:-len(suffix)]
        if subdomain and '.' not in subdomain and subdomain not in RESERVED_SUBDOMAINS:
            return subdomain
    return None


class TenantMiddleware:
    """Sets request.tenant (or None). An explicitly requested but unknown tenant is a 404."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        slug = tenant_slug_from_request(request)
        if slug:
            request.tenant = Tenant.objects.filter(slug=slug).first()
            if request.tenant is None:
                return JsonResponse({'detail': 'Tenant not found.'}, status=404)
        return self.get_response(request)
