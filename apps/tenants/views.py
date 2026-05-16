from rest_framework import generics
from .models import Tenant
from .serializers import TenantSerializer

class TenantCreateView(generics.CreateAPIView):
    serializer_class = TenantSerializer
    queryset = Tenant.objects.all()