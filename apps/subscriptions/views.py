import uuid
from datetime import timedelta
from decimal import Decimal
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.subscriptions.access import active_subscriptions
from apps.subscriptions.models import Payment, Plan, Subscription
from apps.subscriptions.paystack import PaystackClient
from apps.subscriptions.serializers import (
    PlanSerializer, SubscriptionSerializer, CheckoutSerializer,
    TenantSubscriptionSerializer, PaymentSerializer,
)
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


class AccessView(APIView):
    """What the current user can access: lets frontends gate content."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plan_ids = active_subscriptions(request.user).values_list('plan_id', flat=True).distinct()
        plan_ids = [str(plan_id) for plan_id in plan_ids]
        return Response({'has_access': bool(plan_ids), 'active_plans': plan_ids})


class SubscriptionCancelView(APIView):
    """Cancel a subscription; recurring ones are also disabled on Paystack."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        subscription = get_object_or_404(Subscription, pk=pk, user=request.user)
        if subscription.status == Subscription.Status.CANCELED:
            return Response({'detail': 'Subscription is already canceled.'}, status=status.HTTP_400_BAD_REQUEST)

        if subscription.paystack_subscription_code:
            if not subscription.paystack_email_token:
                return Response(
                    {'detail': 'Subscription cannot be canceled yet; try again shortly.'},
                    status=status.HTTP_409_CONFLICT
                )
            PaystackClient().disable_subscription(
                subscription.paystack_subscription_code, subscription.paystack_email_token
            )

        subscription.status = Subscription.Status.CANCELED
        subscription.save(update_fields=['status'])
        return Response(SubscriptionSerializer(subscription).data)


class PaymentListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user)


class TenantSubscriptionListView(generics.ListAPIView):
    """All subscriptions in the admin's tenant; filter with ?status=active."""
    permission_classes = [IsTenantAdmin]
    serializer_class = TenantSubscriptionSerializer

    def get_queryset(self):
        queryset = Subscription.objects.filter(
            plan__tenant=self.request.user.tenant
        ).select_related('user').order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset


class TenantPaymentListView(generics.ListAPIView):
    permission_classes = [IsTenantAdmin]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        return Payment.objects.filter(tenant=self.request.user.tenant)


def monthly_price(plan):
    if plan.interval == Plan.Interval.YEARLY:
        return plan.price / 12
    return plan.price


class TenantMetricsView(APIView):
    """Headline billing numbers for the admin's tenant."""
    permission_classes = [IsTenantAdmin]

    def get(self, request):
        tenant = request.user.tenant
        subscriptions = Subscription.objects.filter(plan__tenant=tenant)
        active = subscriptions.filter(status=Subscription.Status.ACTIVE).select_related('plan')

        by_status = {choice: 0 for choice in Subscription.Status.values}
        for row in subscriptions.values('status').annotate(count=Count('id')):
            by_status[row['status']] = row['count']

        plans = {}
        for subscription in active:
            plan = subscription.plan
            entry = plans.setdefault(plan.id, {
                'plan': str(plan.id), 'name': plan.name, 'active_subscriptions': 0, 'mrr': Decimal('0'),
            })
            entry['active_subscriptions'] += 1
            entry['mrr'] += monthly_price(plan)

        since = timezone.now() - timedelta(days=30)
        revenue = Payment.objects.filter(tenant=tenant).filter(
            Q(paid_at__gte=since) | Q(paid_at__isnull=True, created_at__gte=since)
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        mrr = sum((entry['mrr'] for entry in plans.values()), Decimal('0'))
        for entry in plans.values():
            entry['mrr'] = str(entry['mrr'].quantize(Decimal('0.01')))

        return Response({
            'active_subscribers': active.values('user').distinct().count(),
            'subscriptions_by_status': by_status,
            'mrr': str(mrr.quantize(Decimal('0.01'))),
            'revenue_last_30_days': str(revenue.quantize(Decimal('0.01'))),
            'plans': list(plans.values()),
        })
