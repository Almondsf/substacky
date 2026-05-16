from django.urls import path
from apps.subscriptions.views import SubscriptionListCreateView, PlanListCreateView

urlpatterns = [
    path('plans/', PlanListCreateView.as_view(), name='plan-list-create'),
    path('subscriptions/', SubscriptionListCreateView.as_view(), name='subscription-list-create'),
]