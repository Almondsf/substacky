from apps.subscriptions.models import Subscription
import logging

logger = logging.getLogger(__name__)

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
        status = payload.get('status')
        if subscription_code and status:
            Subscription.objects.filter(
                paystack_subscription_code=subscription_code
            ).update(status=status)