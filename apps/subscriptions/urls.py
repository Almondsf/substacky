from django.urls import path
from apps.subscriptions.views import (
    SubscriptionListView, PlanListCreateView, PlanDetailView, SubscriptionDetailView, CheckoutView, AccessView, SubscriptionCancelView,
    PaymentListView, TenantSubscriptionListView, TenantPaymentListView, TenantMetricsView,
)

urlpatterns = [
    path('plans/', PlanListCreateView.as_view(), name='plan-list-create'),
    path('subscriptions/', SubscriptionListView.as_view(), name='subscription-list'),
    path('plans/<uuid:pk>/', PlanDetailView.as_view(), name='plan-detail'),
    path('subscriptions/<uuid:pk>/', SubscriptionDetailView.as_view(), name='subscription-detail'),
    path('subscriptions/<uuid:pk>/cancel/', SubscriptionCancelView.as_view(), name='subscription-cancel'),
    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('access/', AccessView.as_view(), name='access'),
    path('payments/', PaymentListView.as_view(), name='payment-list'),
    path('tenant/subscriptions/', TenantSubscriptionListView.as_view(), name='tenant-subscription-list'),
    path('tenant/payments/', TenantPaymentListView.as_view(), name='tenant-payment-list'),
    path('tenant/metrics/', TenantMetricsView.as_view(), name='tenant-metrics'),
]
