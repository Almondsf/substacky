from rest_framework import serializers
from apps.subscriptions.models import Plan, Subscription

class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ['id', 'name', 'price', 'tenant', 'interval', 'created_at']
        read_only_fields = ['id', 'tenant', 'created_at']
    
    
class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ['id', 'user', 'plan', 'status', 'created_at']
        # Status only changes through verified Paystack webhooks.
        read_only_fields = ['id', 'user', 'status', 'created_at']

    def validate_plan(self, plan):
        user = self.context['request'].user
        if plan.tenant_id != user.tenant_id:
            raise serializers.ValidationError('Plan does not belong to your tenant.')
        return plan
