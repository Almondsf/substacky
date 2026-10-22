from django.urls import path
from apps.subscriptions.views import SubscriptionListCreateView, PlanListCreateView, PlanDetailView, SubscriptionDetailView

urlpatterns = [
    path('plans/', PlanListCreateView.as_view(), name='plan-list-create'),
    path('subscriptions/', SubscriptionListCreateView.as_view(), name='subscription-list-create'),
    path('plans/<uuid:pk>/', PlanDetailView.as_view(), name='plan-detail'),
    path('subscriptions/<uuid:pk>/', SubscriptionDetailView.as_view(), name='subscription-detail'),
]