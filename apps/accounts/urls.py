from django.urls import path
from .views import (
    RegistrationView, MeView, InviteListCreateView, InviteRevokeView, InviteAcceptView,
    MemberListView, MemberDetailView,
)
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('register/', RegistrationView.as_view(), name='register'),
    path('login/', TokenObtainPairView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('me/', MeView.as_view(), name='me'),
    path('invites/', InviteListCreateView.as_view(), name='invite-list-create'),
    path('invites/accept/', InviteAcceptView.as_view(), name='invite-accept'),
    path('invites/<uuid:pk>/', InviteRevokeView.as_view(), name='invite-revoke'),
    path('members/', MemberListView.as_view(), name='member-list'),
    path('members/<uuid:pk>/', MemberDetailView.as_view(), name='member-detail'),
]
