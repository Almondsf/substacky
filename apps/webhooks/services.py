from apps.subscriptions.models import Subscription
import logging

logger = logging.getLogger(__name__)

# Paystack subscription statuses -> our Subscription.Status values.
# non-renewing subscriptions stay active until the current period ends.
PAYSTACK_STATUS_MAP = {
    'active': Subscription.Status.ACTIVE,
    'non-renewing': Subscription.Status.ACTIVE,
    'attention': Subscription.Status.PAST_DUE,
    'completed': Subscription.Status.CANCELED,
    'cancelled': Subscription.Status.CANCELED,
}

class PaystackWebhookService:
    
    def handle_event(self, event_type, payload):
        handlers = {
            'charge.success': self.handle_charge_success,
            'invoice.payment_failed': self.handle_payment_failed,
            'subscription.updated': self.handle_subscription_updated,
        }
        handler = handlers.get(event_type)
        if handler:
            handler(payload)
        else:
            logger.info(f"Unhandled event type: {event_type}")
    
    def handle_charge_success(self, payload):
        subscription_code = payload.get('subscription_code')
        if subscription_code:
            Subscription.objects.filter(
                paystack_subscription_code=subscription_code
            ).update(status=Subscription.Status.ACTIVE)
    
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