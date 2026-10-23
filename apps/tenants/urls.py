from django.urls import path
from .views import TenantCreateView, CurrentTenantView

urlpatterns = [
    path('register/', TenantCreateView.as_view(), name='tenant-register'),
    path('current/', CurrentTenantView.as_view(), name='tenant-current'),
]
