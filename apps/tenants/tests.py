from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.models import CustomUser as User
from apps.subscriptions.models import Plan
from apps.tenants.models import Tenant


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


class TenantResolutionTests(APITestCase):

    def setUp(self):
        self.acme = Tenant.objects.create(name='Acme', slug='acme')
        self.other = Tenant.objects.create(name='Other', slug='other')
        Plan.objects.create(tenant=self.acme, name='Pro', price='5000.00')
        Plan.objects.create(tenant=self.acme, name='Basic', price='1000.00')
        Plan.objects.create(tenant=self.other, name='Hidden', price='1.00')
        self.user = User.objects.create_user(
            username='m', email='m@acme.com', password='x', tenant=self.acme
        )

    def bearer(self, user):
        return {'HTTP_AUTHORIZATION': f'Bearer {RefreshToken.for_user(user).access_token}'}

    def test_header_resolves_tenant_with_public_plans(self):
        response = self.client.get(reverse('tenant-current'), HTTP_X_TENANT='acme')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['slug'], 'acme')
        self.assertEqual([p['name'] for p in response.data['plans']], ['Basic', 'Pro'])

    def test_unknown_tenant_is_404(self):
        response = self.client.get(reverse('tenant-current'), HTTP_X_TENANT='nope')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_no_tenant_in_request(self):
        response = self.client.get(reverse('tenant-current'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(TENANT_BASE_DOMAIN='substacky.test')
    def test_subdomain_resolves_tenant(self):
        response = self.client.get(reverse('tenant-current'), HTTP_HOST='acme.substacky.test')
        self.assertEqual(response.data['slug'], 'acme')

    @override_settings(TENANT_BASE_DOMAIN='substacky.test')
    def test_reserved_subdomain_is_not_a_tenant(self):
        Tenant.objects.create(name='WWW', slug='www')
        response = self.client.get(reverse('tenant-current'), HTTP_HOST='www.substacky.test')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_user_rejected_on_another_tenant(self):
        response = self.client.get(reverse('me'), HTTP_X_TENANT='other', **self.bearer(self.user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_allowed_on_own_tenant(self):
        response = self.client.get(reverse('me'), HTTP_X_TENANT='acme', **self.bearer(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_without_tenant_header_still_works(self):
        response = self.client.get(reverse('me'), **self.bearer(self.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_registration_joins_request_tenant(self):
        response = self.client.post(reverse('register'), {
            'username': 'n', 'email': 'n@acme.com', 'password': 'S3cure-pass!',
        }, HTTP_X_TENANT='acme')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.get(email='n@acme.com').tenant, self.acme)

    def test_registration_rejects_mismatched_tenant(self):
        response = self.client.post(reverse('register'), {
            'username': 'n', 'email': 'n@acme.com', 'password': 'S3cure-pass!', 'tenant': str(self.other.id),
        }, HTTP_X_TENANT='acme')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_scoped_views_return_nothing_without_tenant(self):
        loner = User.objects.create_user(username='l', email='l@x.com', password='x')
        self.client.force_authenticate(loner)
        self.assertEqual(self.client.get(reverse('plan-list-create')).data, [])
