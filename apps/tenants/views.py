from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import Tenant
from .serializers import TenantRegistrationSerializer

class TenantCreateView(generics.CreateAPIView):
    serializer_class = TenantRegistrationSerializer
    queryset = Tenant.objects.all()
    permission_classes = [AllowAny]
