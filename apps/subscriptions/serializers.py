from rest_framework import serializers
from apps.subscriptions.models import Payment, Plan, Subscription

class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ['id', 'name', 'price', 'tenant', 'interval', 'paystack_plan_code', 'created_at']
        read_only_fields = ['id', 'tenant', 'paystack_plan_code', 'created_at']
    
    
class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ['id', 'user', 'plan', 'status', 'paystack_reference', 'created_at']
        # Subscriptions are created via checkout and only change through verified Paystack webhooks.
        read_only_fields = fields


class CheckoutSerializer(serializers.Serializer):
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all())

    def validate_plan(self, plan):
        user = self.context['request'].user
        if plan.tenant_id != user.tenant_id:
            raise serializers.ValidationError('Plan does not belong to your tenant.')
        if Subscription.objects.filter(
            user=user, plan=plan, status=Subscription.Status.ACTIVE
        ).exists():
            raise serializers.ValidationError('You already have an active subscription to this plan.')
        return plan


class TenantSubscriptionSerializer(SubscriptionSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)

    class Meta(SubscriptionSerializer.Meta):
        fields = SubscriptionSerializer.Meta.fields + ['user_email']
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'subscription', 'reference', 'amount', 'currency', 'paid_at', 'created_at']
        read_only_fields = fields
