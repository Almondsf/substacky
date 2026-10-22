import json
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from unittest.mock import MagicMock, patch
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate
from apps.accounts.models import CustomUser as User
from apps.subscriptions.models import Payment, Plan, Subscription
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


class ContentGatingTests(SubscriptionTestCase):

    def gated_view(self, required_plans=None):
        from rest_framework.views import APIView
        from core.permissions import HasActiveSubscription

        class GatedView(APIView):
            permission_classes = [HasActiveSubscription]

            def get(self, request):
                return Response({'ok': True})

        GatedView.required_plans = required_plans
        return GatedView.as_view()

    def get_gated(self, user, required_plans=None):
        request = APIRequestFactory().get('/gated/')
        force_authenticate(request, user=user)
        return self.gated_view(required_plans)(request)

    def test_no_subscription_is_denied(self):
        self.assertEqual(self.get_gated(self.member).status_code, status.HTTP_403_FORBIDDEN)

    def test_pending_or_past_due_is_denied(self):
        for sub_status in (Subscription.Status.PENDING, Subscription.Status.PAST_DUE):
            Subscription.objects.create(user=self.member, plan=self.plan, status=sub_status)
        self.assertEqual(self.get_gated(self.member).status_code, status.HTTP_403_FORBIDDEN)

    def test_active_subscription_is_allowed(self):
        Subscription.objects.create(user=self.member, plan=self.plan, status=Subscription.Status.ACTIVE)
        self.assertEqual(self.get_gated(self.member).status_code, status.HTTP_200_OK)

    def test_required_plans_enforced(self):
        premium = Plan.objects.create(tenant=self.tenant, name='Premium', price='9000.00')
        Subscription.objects.create(user=self.member, plan=self.plan, status=Subscription.Status.ACTIVE)
        self.assertEqual(
            self.get_gated(self.member, required_plans=[premium.id]).status_code,
            status.HTTP_403_FORBIDDEN
        )
        self.assertEqual(
            self.get_gated(self.member, required_plans=[self.plan.id, premium.id]).status_code,
            status.HTTP_200_OK
        )

    def test_access_endpoint(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(reverse('access')).data, {'has_access': False, 'active_plans': []})
        Subscription.objects.create(user=self.member, plan=self.plan, status=Subscription.Status.ACTIVE)
        response = self.client.get(reverse('access'))
        self.assertEqual(response.data, {'has_access': True, 'active_plans': [str(self.plan.id)]})


@patch('apps.subscriptions.views.PaystackClient')
class CancelTests(SubscriptionTestCase):

    def cancel(self, sub, user=None):
        self.client.force_authenticate(user or self.member)
        return self.client.post(reverse('subscription-cancel', args=[sub.id]))

    def test_cancel_recurring_disables_on_paystack(self, client_cls):
        sub = Subscription.objects.create(
            user=self.member, plan=self.plan, status=Subscription.Status.ACTIVE,
            paystack_subscription_code='SUB_1', paystack_email_token='tok'
        )
        response = self.cancel(sub)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], Subscription.Status.CANCELED)
        client_cls.return_value.disable_subscription.assert_called_once_with('SUB_1', 'tok')

    def test_cancel_pending_skips_paystack(self, client_cls):
        sub = Subscription.objects.create(user=self.member, plan=self.plan)
        self.assertEqual(self.cancel(sub).status_code, status.HTTP_200_OK)
        client_cls.return_value.disable_subscription.assert_not_called()

    def test_paystack_failure_keeps_subscription_active(self, client_cls):
        client_cls.return_value.disable_subscription.side_effect = PaystackError()
        sub = Subscription.objects.create(
            user=self.member, plan=self.plan, status=Subscription.Status.ACTIVE,
            paystack_subscription_code='SUB_1', paystack_email_token='tok'
        )
        self.assertEqual(self.cancel(sub).status_code, status.HTTP_502_BAD_GATEWAY)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)

    def test_missing_email_token_conflicts(self, client_cls):
        sub = Subscription.objects.create(
            user=self.member, plan=self.plan, status=Subscription.Status.ACTIVE,
            paystack_subscription_code='SUB_1'
        )
        self.assertEqual(self.cancel(sub).status_code, status.HTTP_409_CONFLICT)

    def test_already_canceled(self, client_cls):
        sub = Subscription.objects.create(user=self.member, plan=self.plan, status=Subscription.Status.CANCELED)
        self.assertEqual(self.cancel(sub).status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_cancel_someone_elses(self, client_cls):
        sub = Subscription.objects.create(user=self.admin, plan=self.plan, status=Subscription.Status.ACTIVE)
        self.assertEqual(self.cancel(sub).status_code, status.HTTP_404_NOT_FOUND)


class TenantAdminTests(SubscriptionTestCase):

    def setUp(self):
        super().setUp()
        self.yearly = Plan.objects.create(
            tenant=self.tenant, name='Annual', price='12000.00', interval=Plan.Interval.YEARLY
        )
        self.active = Subscription.objects.create(user=self.member, plan=self.plan, status=Subscription.Status.ACTIVE)
        Subscription.objects.create(user=self.member, plan=self.yearly, status=Subscription.Status.ACTIVE)
        Subscription.objects.create(user=self.admin, plan=self.plan, status=Subscription.Status.PAST_DUE)
        outsider = User.objects.create_user(username='o', email='o@other.com', password='x', tenant=self.other_tenant)
        Subscription.objects.create(user=outsider, plan=self.foreign_plan, status=Subscription.Status.ACTIVE)
        Payment.objects.create(
            tenant=self.tenant, user=self.member, subscription=self.active, reference='p1', amount='5000.00',
            paid_at=timezone.now() - timedelta(days=3)
        )
        Payment.objects.create(
            tenant=self.tenant, user=self.member, subscription=self.active, reference='p0', amount='5000.00',
            paid_at=timezone.now() - timedelta(days=40)
        )
        Payment.objects.create(tenant=self.other_tenant, reference='px', amount='100.00')

    def test_member_cannot_view_tenant_endpoints(self):
        self.client.force_authenticate(self.member)
        for name in ('tenant-subscription-list', 'tenant-payment-list', 'tenant-metrics'):
            self.assertEqual(self.client.get(reverse(name)).status_code, status.HTTP_403_FORBIDDEN)

    def test_tenant_subscriptions_scoped_and_filterable(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('tenant-subscription-list'))
        self.assertEqual(len(response.data), 3)
        response = self.client.get(reverse('tenant-subscription-list'), {'status': 'past_due'})
        self.assertEqual([s['user_email'] for s in response.data], ['admin@acme.com'])

    def test_tenant_payments_scoped(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse('tenant-payment-list'))
        self.assertEqual({p['reference'] for p in response.data}, {'p0', 'p1'})

    def test_metrics(self):
        self.client.force_authenticate(self.admin)
        data = self.client.get(reverse('tenant-metrics')).data
        self.assertEqual(data['active_subscribers'], 1)
        self.assertEqual(data['subscriptions_by_status']['active'], 2)
        self.assertEqual(data['subscriptions_by_status']['past_due'], 1)
        self.assertEqual(data['mrr'], '6000.00')  # 5000 monthly + 12000/12
        self.assertEqual(data['revenue_last_30_days'], '5000.00')
        self.assertEqual(len(data['plans']), 2)

    def test_user_sees_only_own_payments(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(reverse('payment-list')).data, [])
        self.client.force_authenticate(self.member)
        self.assertEqual(len(self.client.get(reverse('payment-list')).data), 2)
