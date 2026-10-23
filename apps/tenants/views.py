from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.subscriptions.serializers import PlanSerializer
from .models import Tenant
from .serializers import TenantRegistrationSerializer, TenantSerializer

class TenantCreateView(generics.CreateAPIView):
    serializer_class = TenantRegistrationSerializer
    queryset = Tenant.objects.all()
    permission_classes = [AllowAny]


class CurrentTenantView(APIView):
    """Public info for the request's tenant (X-Tenant header or subdomain), e.g. for a pricing page."""
    permission_classes = [AllowAny]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        tenant = request.tenant
        if tenant is None:
            return Response(
                {'detail': 'No tenant in request. Send X-Tenant or use a tenant subdomain.'},
                status=status.HTTP_404_NOT_FOUND
            )
        data = TenantSerializer(tenant).data
        data['plans'] = PlanSerializer(tenant.plans.order_by('price'), many=True).data
        return Response(data)
