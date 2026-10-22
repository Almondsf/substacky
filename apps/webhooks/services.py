from decimal import Decimal
from django.utils.dateparse import parse_datetime
from apps.subscriptions.models import Payment, Subscription
import logging

logger = logging.getLogger(__name__)

# Paystack subscription statuses -> our Subscription.Status values.
# non-renewing subscriptions stay active until the current period ends.
PAYSTACK_STATUS_MAP = {
    'active': Subscription.Status.ACTIVE,
    'non-renewing': Subscription.Status.ACTIVE,
    'attention': Subscription.Status.PAST_DUE,
    'completed': Subscription.Status.CANCELED,
    'complete': Subscription.Status.CANCELED,
    'cancelled': Subscription.Status.CANCELED,
}

class PaystackWebhookService:
    
    def handle_event(self, event_type, payload):
        handlers = {
            'charge.success': self.handle_charge_success,
            'invoice.payment_failed': self.handle_payment_failed,
            'subscription.create': self.handle_subscription_create,
            'subscription.updated': self.handle_subscription_updated,
            'subscription.disable': self.handle_subscription_updated,
            'subscription.not_renew': self.handle_subscription_updated,
        }
        handler = handlers.get(event_type)
        if handler:
            handler(payload)
        else:
            logger.info(f"Unhandled event type: {event_type}")
    
    def find_subscription(self, payload):
        # First payment from checkout carries our reference; renewals carry the
        # subscription code, or at least the customer and plan.
        reference = payload.get('reference')
        subscription_code = payload.get('subscription_code')
        email = (payload.get('customer') or {}).get('email')
        plan_code = (payload.get('plan') or {}).get('plan_code')

        if reference:
            subscription = Subscription.objects.filter(paystack_reference=reference).first()
            if subscription:
                return subscription
        if subscription_code:
            subscription = Subscription.objects.filter(paystack_subscription_code=subscription_code).first()
            if subscription:
                return subscription
        if email and plan_code:
            return Subscription.objects.filter(
                user__email=email, plan__paystack_plan_code=plan_code
            ).exclude(status=Subscription.Status.CANCELED).order_by('-created_at').first()
        return None

    def handle_charge_success(self, payload):
        subscription = self.find_subscription(payload)
        if not subscription:
            logger.warning(f"charge.success with no matching subscription: {payload.get('reference')}")
            return

        subscription.status = Subscription.Status.ACTIVE
        subscription.save(update_fields=['status'])

        reference = payload.get('reference')
        if reference:
            Payment.objects.get_or_create(reference=reference, defaults={
                'tenant_id': subscription.plan.tenant_id,
                'user_id': subscription.user_id,
                'subscription': subscription,
                'amount': Decimal(payload.get('amount') or 0) / 100,
                'currency': payload.get('currency') or 'NGN',
                'paid_at': parse_datetime(payload.get('paid_at') or payload.get('paidAt') or ''),
            })

    def handle_subscription_create(self, payload):
        # Paystack creates the recurring subscription after the first charge;
        # link its code to the newest checkout for that customer and plan.
        subscription_code = payload.get('subscription_code')
        email = (payload.get('customer') or {}).get('email')
        plan_code = (payload.get('plan') or {}).get('plan_code')
        if not (subscription_code and email and plan_code):
            return
        if Subscription.objects.filter(paystack_subscription_code=subscription_code).exists():
            return
        subscription = Subscription.objects.filter(
            user__email=email,
            plan__paystack_plan_code=plan_code,
            paystack_subscription_code__isnull=True,
        ).exclude(status=Subscription.Status.CANCELED).order_by('-created_at').first()
        if subscription:
            subscription.paystack_subscription_code = subscription_code
            subscription.paystack_email_token = payload.get('email_token')
            subscription.status = Subscription.Status.ACTIVE
            subscription.save(update_fields=['paystack_subscription_code', 'paystack_email_token', 'status'])
        else:
            logger.warning(f"No subscription to link for {subscription_code} ({email}, {plan_code})")
    
    def handle_payment_failed(self, payload):
        subscription_code = payload.get('subscription_code')
        if subscription_code:
            Subscription.objects.filter(
                paystack_subscription_code=subscription_code
            ).update(status=Subscription.Status.PAST_DUE)
    
    def handle_subscription_updated(self, payload):
        subscription_code = payload.get('subscription_code')
        paystack_status = payload.get('status')
        status = PAYSTACK_STATUS_MAP.get(paystack_status)
        if paystack_status and not status:
            logger.warning(f"Unknown Paystack subscription status: {paystack_status}")
        if subscription_code and status:
            Subscription.objects.filter(
                paystack_subscription_code=subscription_code
            ).update(status=status)