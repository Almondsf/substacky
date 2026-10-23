import secrets
import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.contrib.auth.models import AbstractUser
from apps.tenants.models import Tenant

class CustomUser(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        MEMBER = 'member', 'Member'

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']


def generate_invite_token():
    return secrets.token_urlsafe(32)


def default_invite_expiry():
    return timezone.now() + timedelta(days=settings.INVITE_EXPIRY_DAYS)


class Invite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='invites')
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=CustomUser.Role.choices, default=CustomUser.Role.MEMBER)
    token = models.CharField(max_length=64, unique=True, default=generate_invite_token, editable=False)
    invited_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='sent_invites')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=default_invite_expiry)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_pending(self):
        return self.accepted_at is None and self.expires_at > timezone.now()
