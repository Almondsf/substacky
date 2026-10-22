import uuid
from django.db import transaction
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.subscriptions.models import Plan, Subscription
from apps.subscriptions.paystack import PaystackClient
from apps.subscriptions.serializers import PlanSerializer, SubscriptionSerializer, CheckoutSerializer
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
        data = serializer.validated_data
        plan_code = PaystackClient().create_plan(
            name=data['name'],
            amount=data['price'],
            interval=data.get('interval', Plan.Interval.MONTHLY)
        )
        serializer.save(tenant=self.request.user.tenant, paystack_plan_code=plan_code)


class PlanDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = PlanSerializer
    lookup_field = 'pk'
    
    def get_permissions(self):
        if self.request.method in ['PUT', 'PATCH', 'DELETE']:
            return [IsTenantAdmin()]
        return [IsAuthenticated()]
    
    def get_queryset(self):
        return Plan.objects.filter(tenant=self.request.user.tenant)
    
class SubscriptionListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SubscriptionSerializer
    
    def get_queryset(self):
        user = self.request.user
        return Subscription.objects.filter(user=user)


class SubscriptionDetailView(generics.RetrieveAPIView):
    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'pk'
    
    def get_queryset(self):
        return Subscription.objects.filter(user=self.request.user)


class CheckoutView(APIView):
    """Start a subscription: creates a pending Subscription and a Paystack checkout."""
    permission_classes = [IsAuthenticated]
    serializer_class = CheckoutSerializer

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        plan = serializer.validated_data['plan']
        reference = f"sub_{uuid.uuid4().hex}"

        # If Paystack fails, the pending subscription is rolled back.
        with transaction.atomic():
            subscription = Subscription.objects.create(
                user=request.user, plan=plan, paystack_reference=reference
            )
            checkout = PaystackClient().initialize_transaction(
                email=request.user.email,
                amount=plan.price,
                reference=reference,
                plan_code=plan.paystack_plan_code,
                metadata={'subscription_id': str(subscription.id)}
            )

        return Response({
            'subscription': SubscriptionSerializer(subscription).data,
            'authorization_url': checkout['authorization_url'],
            'reference': reference,
        }, status=status.HTTP_201_CREATED)
