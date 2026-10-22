from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import CustomUser as User
from apps.subscriptions.models import Plan, Subscription
from apps.tenants.models import Tenant


class SubscriptionTestCase(APITestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(name='Acme', slug='acme')
        self.other_tenant = Tenant.objects.create(name='Other', slug='other')
        self.admin = User.objects.create_user(
            username='admin', email='admin@acme.com', password='x',
            tenant=self.tenant, role=User.Role.ADMIN
        )
        self.member = User.objects.create_user(
            username='member', email='member@acme.com', password='x', tenant=self.tenant
        )
        self.plan = Plan.objects.create(tenant=self.tenant, name='Pro', price='5000.00')
        self.foreign_plan = Plan.objects.create(tenant=self.other_tenant, name='Other Pro', price='100.00')


class PlanTests(SubscriptionTestCase):

    def test_member_cannot_create_plan(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse('plan-list-create'), {'name': 'Hack', 'price': '1.00'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_plan_list_is_tenant_scoped(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(reverse('plan-list-create'))
        self.assertEqual([p['id'] for p in response.data], [str(self.plan.id)])

    def test_plan_detail_by_uuid(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(reverse('plan-detail', args=[self.plan.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_foreign_plan_detail_is_hidden(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(reverse('plan-detail', args=[self.foreign_plan.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class SubscriptionTests(SubscriptionTestCase):

    def test_subscription_detail_by_uuid(self):
        sub = Subscription.objects.create(user=self.member, plan=self.plan)
        self.client.force_authenticate(self.member)
        response = self.client.get(reverse('subscription-detail', args=[sub.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_user_cannot_activate_own_subscription(self):
        sub = Subscription.objects.create(user=self.member, plan=self.plan)
        self.client.force_authenticate(self.member)
        response = self.client.patch(
            reverse('subscription-detail', args=[sub.id]), {'status': 'active'}
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.PENDING)

    def test_cannot_subscribe_to_other_tenants_plan(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(
            reverse('subscription-list-create'), {'plan': str(self.foreign_plan.id)}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
