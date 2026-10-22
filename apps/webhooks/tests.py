import hashlib
import hmac
import json
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from apps.accounts.models import CustomUser as User
from apps.subscriptions.models import Plan, Subscription
from apps.tenants.models import Tenant
from apps.webhooks.models import WebhookEvent

SECRET = 'sk_test_secret'


@override_settings(PAYSTACK_SECRET_KEY=SECRET)
class PaystackWebhookTests(APITestCase):

    def setUp(self):
        tenant = Tenant.objects.create(name='Acme', slug='acme')
        user = User.objects.create_user(username='m', email='m@acme.com', password='x', tenant=tenant)
        plan = Plan.objects.create(tenant=tenant, name='Pro', price='5000.00')
        self.subscription = Subscription.objects.create(
            user=user, plan=plan, paystack_subscription_code='SUB_abc'
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
