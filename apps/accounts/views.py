from django.db import transaction
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.models import CustomUser as User, Invite
from apps.accounts.notifications import send_invite_email
from apps.accounts.serializers import (
    RegistrationSerializer, EmailTokenObtainPairSerializer, UserSerializer,
    InviteSerializer, InviteAcceptSerializer, MemberSerializer,
)
from core.permissions import IsTenantAdmin
from rest_framework_simplejwt.views import TokenObtainPairView


class RegistrationView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegistrationSerializer
    permission_classes = [AllowAny]



class EmailTokenObtainPairView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer

class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class InviteListCreateView(generics.ListCreateAPIView):
    """Tenant admins list and send invites. Re-inviting an email replaces its open invite."""
    serializer_class = InviteSerializer
    permission_classes = [IsTenantAdmin]

    def get_queryset(self):
        return Invite.objects.filter(tenant=self.request.user.tenant, accepted_at__isnull=True)

    def perform_create(self, serializer):
        tenant = self.request.user.tenant
        with transaction.atomic():
            Invite.objects.filter(
                tenant=tenant, email__iexact=serializer.validated_data['email'], accepted_at__isnull=True
            ).delete()
            invite = serializer.save(tenant=tenant, invited_by=self.request.user)
        send_invite_email(invite)


class InviteRevokeView(generics.DestroyAPIView):
    permission_classes = [IsTenantAdmin]

    def get_queryset(self):
        return Invite.objects.filter(tenant=self.request.user.tenant, accepted_at__isnull=True)


class InviteAcceptView(APIView):
    """GET ?token= previews an invite; POST accepts it and creates the account."""
    permission_classes = [AllowAny]
    serializer_class = InviteAcceptSerializer

    def get(self, request):
        token = request.query_params.get('token', '')
        invite = Invite.objects.select_related('tenant').filter(token=token).first()
        if not invite or not invite.is_pending:
            return Response({'detail': 'This invite is invalid or has expired.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'tenant': invite.tenant.name,
            'email': invite.email,
            'role': invite.role,
            'expires_at': invite.expires_at,
        })

    def post(self, request):
        serializer = InviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class MemberListView(generics.ListAPIView):
    serializer_class = MemberSerializer
    permission_classes = [IsTenantAdmin]

    def get_queryset(self):
        return User.objects.filter(tenant=self.request.user.tenant).order_by('created_at')


class MemberDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Change a member's role, or remove them from the tenant."""
    serializer_class = MemberSerializer
    permission_classes = [IsTenantAdmin]
    http_method_names = ['get', 'patch', 'delete']

    def get_queryset(self):
        return User.objects.filter(tenant=self.request.user.tenant)

    def perform_update(self, serializer):
        if serializer.instance == self.request.user:
            raise serializers.ValidationError({'role': 'You cannot change your own role.'})
        serializer.save()

    def perform_destroy(self, instance):
        if instance == self.request.user:
            raise serializers.ValidationError({'detail': 'You cannot remove yourself.'})
        # Detach rather than delete, so the user's account and history survive.
        instance.tenant = None
        instance.role = User.Role.MEMBER
        instance.save(update_fields=['tenant', 'role'])
