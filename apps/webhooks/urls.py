from django.urls import path
from .views import PaystackWebhookView

urlpatterns = [
    path('paystack/', PaystackWebhookView.as_view(), name='paystack-webhook'),
]