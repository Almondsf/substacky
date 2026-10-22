from django.db import transaction
from rest_framework import serializers
from apps.accounts.models import CustomUser as User
from .models import Tenant

class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ['id', 'name', 'slug', 'created_at']
        read_only_fields = ['id', 'created_at']


class TenantRegistrationSerializer(TenantSerializer):
    """Creates a tenant together with its first admin user."""
    admin_email = serializers.EmailField(write_only=True)
    admin_username = serializers.CharField(write_only=True)
    admin_password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta(TenantSerializer.Meta):
        fields = TenantSerializer.Meta.fields + ['admin_email', 'admin_username', 'admin_password']

    def validate_admin_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_admin_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('A user with this username already exists.')
        return value

    @transaction.atomic
    def create(self, validated_data):
        email = validated_data.pop('admin_email')
        username = validated_data.pop('admin_username')
        password = validated_data.pop('admin_password')
        tenant = Tenant.objects.create(**validated_data)
        User.objects.create_user(
            username=username,
            email=email,
            password=password,
            tenant=tenant,
            role=User.Role.ADMIN
        )
        return tenant
