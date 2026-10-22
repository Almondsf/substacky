from apps.subscriptions.models import Subscription


def active_subscriptions(user):
    if not user.is_authenticated:
        return Subscription.objects.none()
    return Subscription.objects.filter(
        user=user,
        status=Subscription.Status.ACTIVE,
        plan__tenant_id=user.tenant_id,
    )


def has_active_subscription(user, plans=None):
    """True if the user has an active subscription, optionally to one of `plans` (Plans or ids)."""
    subscriptions = active_subscriptions(user)
    if plans is not None:
        subscriptions = subscriptions.filter(plan__in=plans)
    return subscriptions.exists()
