from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import CustomUser as User


class TenantRegistrationTests(APITestCase):

    def payload(self, **overrides):
        data = {
            'name': 'Acme',
            'slug': 'acme',
            'admin_email': 'owner@acme.com',
            'admin_username': 'owner',
            'admin_password': 'S3cure-pass!',
        }
        data.update(overrides)
        return data

    def test_creates_tenant_with_admin(self):
        response = self.client.post(reverse('tenant-register'), self.payload())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('admin_password', response.data)
        admin = User.objects.get(email='owner@acme.com')
        self.assertEqual(admin.role, User.Role.ADMIN)
        self.assertEqual(str(admin.tenant_id), response.data['id'])

    def test_duplicate_admin_email_rejected(self):
        User.objects.create_user(username='taken', email='owner@acme.com', password='x')
        response = self.client.post(reverse('tenant-register'), self.payload())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('admin_email', response.data)
