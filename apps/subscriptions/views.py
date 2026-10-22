from rest_framework import generics
from apps.subscriptions.models import Plan, Subscription
from apps.subscriptions.serializers import PlanSerializer, SubscriptionSerializer
from rest_framework.permissions import IsAuthenticated
from core.permissions import IsTenantAdmin

class PlanListCreateView(generics.ListCreateAPIView):
    serializer_class = PlanSerializer
    
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsTenantAdmin()]
        return [IsAuthenticated()]
    
    def get_queryset(self):
        tenant = self.request.user.tenant
        return Plan.objects.filter(tenant=tenant)
    
    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)


class PlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PlanSerializer
    lookup_field = 'pk'
    
    def get_permissions(self):
        if self.request.method in ['PUT', 'PATCH', 'DELETE']:
            return [IsTenantAdmin()]
        return [IsAuthenticated()]
    
    def get_queryset(self):
        return Plan.objects.filter(tenant=self.request.user.tenant)
    
class SubscriptionListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer
    
    def get_queryset(self):
        user = self.request.user
        return Subscription.objects.filter(user=user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SubscriptionDetailView(generics.RetrieveAPIView):
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'pk'
    
    def get_queryset(self):
        return Subscription.objects.filter(user=self.request.user)