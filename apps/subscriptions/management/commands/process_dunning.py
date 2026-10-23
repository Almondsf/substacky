from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.subscriptions.models import Subscription
from apps.subscriptions.notifications import send_subscription_canceled_email
from apps.subscriptions.paystack import PaystackClient, PaystackError


class Command(BaseCommand):
    help = 'Cancel subscriptions that stayed past due longer than DUNNING_GRACE_DAYS. Run daily.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='List what would be canceled.')

    def handle(self, *args, dry_run=False, **options):
        cutoff = timezone.now() - timedelta(days=settings.DUNNING_GRACE_DAYS)
        overdue = Subscription.objects.filter(
            status=Subscription.Status.PAST_DUE, past_due_since__lte=cutoff
        ).select_related('user', 'plan__tenant')

        canceled = failed = 0
        for subscription in overdue:
            if dry_run:
                self.stdout.write(f"Would cancel {subscription.id} ({subscription.user.email})")
                continue
            if subscription.paystack_subscription_code and subscription.paystack_email_token:
                try:
                    PaystackClient().disable_subscription(
                        subscription.paystack_subscription_code, subscription.paystack_email_token
                    )
                except PaystackError:
                    # Leave it past due so the next run retries.
                    failed += 1
                    self.stderr.write(f"Paystack disable failed for {subscription.id}")
                    continue
            subscription.set_status(Subscription.Status.CANCELED)
            send_subscription_canceled_email(subscription)
            canceled += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Canceled {canceled} subscription(s), {failed} failed."))
