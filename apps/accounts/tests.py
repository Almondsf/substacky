from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import CustomUser as User
from apps.tenants.models import Tenant


class RegistrationTests(APITestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name='Acme', slug='acme')

    def test_registered_user_is_always_member(self):
        response = self.client.post(reverse('register'), {
            'username': 'eve',
            'email': 'eve@example.com',
            'password': 'S3cure-pass!',
            'tenant': str(self.tenant.id),
            'role': 'admin',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.get(email='eve@example.com').role, User.Role.MEMBER)


class MeViewTests(APITestCase):

    def test_anonymous_is_rejected(self):
        response = self.client.get(reverse('me'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_returns_current_user(self):
        user = User.objects.create_user(username='bob', email='bob@example.com', password='x')
        self.client.force_authenticate(user)
        response = self.client.get(reverse('me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'bob@example.com')
