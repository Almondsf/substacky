from django.contrib import admin
from .models import Payment, Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'tenant', 'price', 'interval', 'paystack_plan_code')
    list_filter = ('tenant', 'interval')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'paystack_subscription_code', 'created_at')
    list_filter = ('status', 'plan__tenant')
    search_fields = ('user__email', 'paystack_subscription_code', 'paystack_reference')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('reference', 'tenant', 'user', 'amount', 'currency', 'paid_at')
    list_filter = ('tenant', 'currency')
    search_fields = ('reference', 'user__email')
