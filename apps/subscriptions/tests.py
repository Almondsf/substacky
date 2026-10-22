import json
from decimal import Decimal
from unittest.mock import MagicMock, patch
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import CustomUser as User
from apps.subscriptions.models import Plan, Subscription
from apps.subscriptions.paystack import PaystackClient, PaystackError
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

    def test_subscriptions_cannot_be_created_directly(self):
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse('subscription-list'), {'plan': str(self.plan.id)})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


@patch('apps.subscriptions.views.PaystackClient')
class PlanPaystackSyncTests(SubscriptionTestCase):

    def test_plan_created_on_paystack(self, client_cls):
        client_cls.return_value.create_plan.return_value = 'PLN_123'
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            reverse('plan-list-create'), {'name': 'Gold', 'price': '2500.00', 'interval': 'yearly'}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['paystack_plan_code'], 'PLN_123')
        client_cls.return_value.create_plan.assert_called_once()
        self.assertEqual(client_cls.return_value.create_plan.call_args.kwargs['interval'], 'yearly')

    def test_plan_not_saved_when_paystack_fails(self, client_cls):
        client_cls.return_value.create_plan.side_effect = PaystackError()
        self.client.force_authenticate(self.admin)
        response = self.client.post(reverse('plan-list-create'), {'name': 'Gold', 'price': '2500.00'})
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(Plan.objects.filter(name='Gold').exists())


@patch('apps.subscriptions.views.PaystackClient')
class CheckoutTests(SubscriptionTestCase):

    def setUp(self):
        super().setUp()
        self.plan.paystack_plan_code = 'PLN_pro'
        self.plan.save()

    def test_checkout_returns_authorization_url(self, client_cls):
        client_cls.return_value.initialize_transaction.return_value = {
            'authorization_url': 'https://checkout.paystack.com/abc'
        }
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse('checkout'), {'plan': str(self.plan.id)})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['authorization_url'], 'https://checkout.paystack.com/abc')

        sub = Subscription.objects.get(user=self.member)
        self.assertEqual(sub.status, Subscription.Status.PENDING)
        self.assertEqual(sub.paystack_reference, response.data['reference'])
        kwargs = client_cls.return_value.initialize_transaction.call_args.kwargs
        self.assertEqual(kwargs['email'], 'member@acme.com')
        self.assertEqual(kwargs['plan_code'], 'PLN_pro')
        self.assertEqual(kwargs['reference'], sub.paystack_reference)

    def test_paystack_failure_rolls_back_subscription(self, client_cls):
        client_cls.return_value.initialize_transaction.side_effect = PaystackError()
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse('checkout'), {'plan': str(self.plan.id)})
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(Subscription.objects.exists())

    def test_cannot_checkout_other_tenants_plan(self, client_cls):
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse('checkout'), {'plan': str(self.foreign_plan.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        client_cls.return_value.initialize_transaction.assert_not_called()

    def test_cannot_checkout_plan_already_active(self, client_cls):
        Subscription.objects.create(user=self.member, plan=self.plan, status=Subscription.Status.ACTIVE)
        self.client.force_authenticate(self.member)
        response = self.client.post(reverse('checkout'), {'plan': str(self.plan.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_anonymous_cannot_checkout(self, client_cls):
        response = self.client.post(reverse('checkout'), {'plan': str(self.plan.id)})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PaystackClientTests(APITestCase):

    def fake_response(self, body):
        response = MagicMock()
        response.read.return_value = json.dumps(body).encode()
        response.__enter__.return_value = response
        return response

    @patch('apps.subscriptions.paystack.urllib.request.urlopen')
    def test_create_plan_sends_kobo_and_paystack_interval(self, urlopen):
        urlopen.return_value = self.fake_response({'status': True, 'data': {'plan_code': 'PLN_1'}})
        code = PaystackClient(secret_key='sk', base_url='https://api.test').create_plan(
            'Gold', Decimal('2500.50'), 'yearly'
        )
        self.assertEqual(code, 'PLN_1')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.test/plan')
        self.assertEqual(request.get_header('Authorization'), 'Bearer sk')
        self.assertEqual(json.loads(request.data), {'name': 'Gold', 'amount': 250050, 'interval': 'annually'})

    @patch('apps.subscriptions.paystack.urllib.request.urlopen')
    def test_rejected_request_raises(self, urlopen):
        urlopen.return_value = self.fake_response({'status': False, 'message': 'Invalid key'})
        with self.assertRaises(PaystackError):
            PaystackClient(secret_key='sk', base_url='https://api.test').create_plan('Gold', 1, 'monthly')
