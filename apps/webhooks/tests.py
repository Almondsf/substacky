import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import CustomUser as User
from apps.subscriptions.models import Payment, Plan, Subscription
from apps.subscriptions.paystack import PaystackError
from apps.tenants.models import Tenant
from apps.webhooks.models import WebhookEvent

SECRET = 'sk_test_secret'


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
class WebhookTestCase(APITestCase):

    def setUp(self):
        tenant = Tenant.objects.create(name='Acme', slug='acme')
        user = User.objects.create_user(username='m', email='m@acme.com', password='x', tenant=tenant)
        self.user = user
        self.plan = Plan.objects.create(
            tenant=tenant, name='Pro', price='5000.00', paystack_plan_code='PLN_pro'
        )
        self.subscription = Subscription.objects.create(
            user=user, plan=self.plan, paystack_subscription_code='SUB_abc'
        )

    def post_event(self, payload, signature=None):
        body = json.dumps(payload).encode()
        if signature is None:
            signature = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
        return self.client.generic(
            'POST', reverse('paystack-webhook'), body,
            content_type='application/json', HTTP_X_PAYSTACK_SIGNATURE=signature
        )

    def assert_status(self, expected):
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, expected)


class PaystackWebhookTests(WebhookTestCase):

    def test_missing_signature_rejected(self):
        response = self.client.post(reverse('paystack-webhook'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_signature_rejected(self):
        response = self.post_event({'event': 'charge.success', 'data': {}}, signature='bad')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(WebhookEvent.objects.exists())

    def test_unknown_event_ignored(self):
        response = self.post_event({'event': 'transfer.success', 'data': {}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(WebhookEvent.objects.exists())

    def test_charge_success_activates(self):
        self.post_event({'event': 'charge.success', 'data': {
            'reference': 'ref1', 'subscription_code': 'SUB_abc'
        }})
        self.assert_status(Subscription.Status.ACTIVE)

    def test_payment_failed_marks_past_due(self):
        self.post_event({'event': 'invoice.payment_failed', 'data': {
            'reference': 'ref2', 'subscription_code': 'SUB_abc'
        }})
        self.assert_status(Subscription.Status.PAST_DUE)

    def test_duplicate_event_processed_once(self):
        payload = {'event': 'charge.success', 'data': {'reference': 'ref1', 'subscription_code': 'SUB_abc'}}
        self.post_event(payload)
        response = self.post_event(payload)
        self.assertEqual(response.data['message'], 'Event already processed')
        self.assertEqual(WebhookEvent.objects.count(), 1)

    def test_events_without_reference_do_not_collide(self):
        self.post_event({'event': 'subscription.updated', 'data': {
            'subscription_code': 'SUB_abc', 'status': 'active'
        }})
        self.post_event({'event': 'subscription.updated', 'data': {
            'subscription_code': 'SUB_abc', 'status': 'cancelled'
        }})
        self.assertEqual(WebhookEvent.objects.count(), 2)
        self.assert_status(Subscription.Status.CANCELED)

    def test_paystack_statuses_are_mapped(self):
        cases = {
            'attention': Subscription.Status.PAST_DUE,
            'non-renewing': Subscription.Status.ACTIVE,
            'completed': Subscription.Status.CANCELED,
        }
        for paystack_status, expected in cases.items():
            self.post_event({'event': 'subscription.updated', 'data': {
                'subscription_code': 'SUB_abc', 'status': paystack_status
            }})
            self.assert_status(expected)

    def test_unknown_paystack_status_leaves_subscription_alone(self):
        self.post_event({'event': 'subscription.updated', 'data': {
            'subscription_code': 'SUB_abc', 'status': 'weird'
        }})
        self.assert_status(Subscription.Status.PENDING)


class CheckoutWebhookTests(WebhookTestCase):
    """Webhooks that complete a checkout started via /checkout/."""

    def setUp(self):
        super().setUp()
        self.subscription = Subscription.objects.create(
            user=self.user, plan=self.plan, paystack_reference='sub_ref'
        )

    def test_charge_success_activates_by_reference(self):
        self.post_event({'event': 'charge.success', 'data': {'reference': 'sub_ref'}})
        self.assert_status(Subscription.Status.ACTIVE)

    def test_subscription_create_links_code(self):
        Subscription.objects.filter(paystack_subscription_code='SUB_abc').delete()
        self.post_event({'event': 'subscription.create', 'data': {
            'subscription_code': 'SUB_new',
            'email_token': 'tok_new',
            'customer': {'email': 'm@acme.com'},
            'plan': {'plan_code': 'PLN_pro'},
        }})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.paystack_subscription_code, 'SUB_new')
        self.assertEqual(self.subscription.paystack_email_token, 'tok_new')
        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)

    def test_subscription_disable_cancels(self):
        self.subscription.paystack_subscription_code = 'SUB_new'
        self.subscription.save()
        self.post_event({'event': 'subscription.disable', 'data': {
            'subscription_code': 'SUB_new', 'status': 'complete'
        }})
        self.assert_status(Subscription.Status.CANCELED)


class PaymentRecordingTests(WebhookTestCase):

    def test_charge_success_records_payment_once(self):
        payload = {'event': 'charge.success', 'data': {
            'reference': 'ref_pay', 'subscription_code': 'SUB_abc', 'amount': 500000,
            'currency': 'NGN', 'paid_at': '2026-10-01T10:00:00.000Z',
        }}
        self.post_event(payload)
        self.post_event(payload)
        payment = Payment.objects.get()
        self.assertEqual(payment.amount, Decimal('5000.00'))
        self.assertEqual(payment.subscription, self.subscription)
        self.assertEqual(payment.user, self.user)
        self.assertEqual(payment.tenant, self.plan.tenant)
        self.assertIsNotNone(payment.paid_at)

    def test_renewal_matched_by_customer_and_plan(self):
        self.post_event({'event': 'charge.success', 'data': {
            'reference': 'renewal_1', 'amount': 500000,
            'customer': {'email': 'm@acme.com'}, 'plan': {'plan_code': 'PLN_pro'},
        }})
        self.assertEqual(Payment.objects.get().subscription, self.subscription)
        self.assert_status(Subscription.Status.ACTIVE)

    def test_unmatched_charge_records_nothing(self):
        self.post_event({'event': 'charge.success', 'data': {'reference': 'stray', 'amount': 100}})
        self.assertFalse(Payment.objects.exists())


@patch('apps.subscriptions.notifications.PaystackClient')
class PaymentFailedTests(WebhookTestCase):

    def fail_payment(self, nested=True):
        data = {'invoice_code': 'INV_1', 'subscription': {'subscription_code': 'SUB_abc'}} if nested \
            else {'reference': 'r', 'subscription_code': 'SUB_abc'}
        with self.captureOnCommitCallbacks(execute=True):
            self.post_event({'event': 'invoice.payment_failed', 'data': data})

    def test_invoice_payload_marks_past_due_and_emails(self, client_cls):
        client_cls.return_value.get_manage_link.return_value = 'https://paystack.com/manage/xyz'
        self.fail_payment()
        self.assert_status(Subscription.Status.PAST_DUE)
        self.assertIsNotNone(self.subscription.past_due_since)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['m@acme.com'])
        self.assertIn('https://paystack.com/manage/xyz', mail.outbox[0].body)

    def test_email_sent_without_manage_link_when_paystack_fails(self, client_cls):
        client_cls.return_value.get_manage_link.side_effect = PaystackError()
        self.fail_payment(nested=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('Update your card', mail.outbox[0].body)

    def test_repeat_failure_does_not_reset_clock_or_email_again(self, client_cls):
        self.fail_payment()
        self.subscription.refresh_from_db()
        first_since = self.subscription.past_due_since
        with self.captureOnCommitCallbacks(execute=True):
            self.post_event({'event': 'subscription.updated', 'data': {
                'subscription_code': 'SUB_abc', 'status': 'attention'
            }})
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.past_due_since, first_since)
        self.assertEqual(len(mail.outbox), 1)

    def test_recovery_clears_past_due(self, client_cls):
        self.fail_payment()
        self.post_event({'event': 'charge.success', 'data': {'reference': 'retry', 'subscription_code': 'SUB_abc'}})
        self.assert_status(Subscription.Status.ACTIVE)
        self.assertIsNone(self.subscription.past_due_since)
