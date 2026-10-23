import logging
from django.core.mail import send_mail
from apps.subscriptions.paystack import PaystackClient, PaystackError

logger = logging.getLogger(__name__)


def _send(subscription, subject, body):
    try:
        send_mail(subject, body, None, [subscription.user.email])
    except Exception:
        # A mail outage must never break billing state changes.
        logger.exception(f"Failed to send '{subject}' to {subscription.user.email}")


def send_payment_failed_email(subscription, grace_days):
    plan = subscription.plan
    manage_link = None
    if subscription.paystack_subscription_code:
        try:
            manage_link = PaystackClient().get_manage_link(subscription.paystack_subscription_code)
        except PaystackError:
            pass

    lines = [
        f"Hi {subscription.user.first_name or subscription.user.username},",
        "",
        f"We couldn't process your payment for {plan.name} ({plan.tenant.name}).",
        f"Please update your payment details within {grace_days} days to keep your subscription.",
    ]
    if manage_link:
        lines += ["", f"Update your card: {manage_link}"]
    _send(subscription, f"Payment failed for {plan.name}", "\n".join(lines))


def send_subscription_canceled_email(subscription):
    plan = subscription.plan
    body = "\n".join([
        f"Hi {subscription.user.first_name or subscription.user.username},",
        "",
        f"Your {plan.name} subscription to {plan.tenant.name} has been canceled "
        "because we couldn't collect payment.",
        "You can subscribe again at any time.",
    ])
    _send(subscription, f"Your {plan.name} subscription was canceled", body)
