from django.urls import path
from .views import TenantCreateView

urlpatterns = [
    path('register/', TenantCreateView.as_view(), name='tenant-register'),
]