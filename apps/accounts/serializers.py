from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.serializers import ModelSerializer
from apps.accounts.models import CustomUser as User, Invite
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class RegistrationSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'username', 'email', 'password', 'tenant', 'role']
        read_only_fields = ['id', 'role']
        extra_kwargs = {'password': {'write_only': True}}

    def validate(self, attrs):
        # On a tenant domain / X-Tenant request, users join that tenant.
        request_tenant = getattr(self.context.get('request'), 'tenant', None)
        if request_tenant:
            if attrs.get('tenant') and attrs['tenant'] != request_tenant:
                raise serializers.ValidationError({'tenant': 'Does not match the tenant of this request.'})
            attrs['tenant'] = request_tenant
        return attrs

    def create(self, validated_data):
        # Self-registered users are always members; admins are created with their tenant.
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            password=validated_data['password'],
            tenant=validated_data.get('tenant'),
            role=User.Role.MEMBER
        )
        return user



class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.EMAIL_FIELD


class UserSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'username', 'email', 'tenant', 'role']
        read_only_fields = ['id', 'tenant', 'role']


class InviteSerializer(ModelSerializer):
    is_pending = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invite
        fields = ['id', 'email', 'role', 'invited_by', 'created_at', 'expires_at', 'accepted_at', 'is_pending']
        read_only_fields = ['id', 'invited_by', 'created_at', 'expires_at', 'accepted_at']

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value


class InviteAcceptSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True)
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate_token(self, value):
        invite = Invite.objects.select_related('tenant').filter(token=value).first()
        if not invite or not invite.is_pending:
            raise serializers.ValidationError('This invite is invalid or has expired.')
        self.invite = invite
        return value

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value

    def validate(self, attrs):
        email = self.invite.email
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        validate_password(attrs['password'], User(username=attrs['username'], email=email))
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        # Lock the invite so two concurrent accepts can't both succeed.
        invite = Invite.objects.select_for_update().get(pk=self.invite.pk)
        if not invite.is_pending:
            raise serializers.ValidationError({'token': 'This invite is invalid or has expired.'})
        user = User.objects.create_user(
            username=validated_data['username'],
            email=invite.email,
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            tenant=invite.tenant,
            role=invite.role,
        )
        invite.accepted_at = timezone.now()
        invite.save(update_fields=['accepted_at'])
        return user


class MemberSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'username', 'email', 'role', 'created_at']
        read_only_fields = ['id', 'first_name', 'last_name', 'username', 'email', 'created_at']
