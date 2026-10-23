import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_invite_email(invite):
    if settings.INVITE_ACCEPT_URL:
        action = f"Accept the invite: {settings.INVITE_ACCEPT_URL}?token={invite.token}"
    else:
        action = f"Your invite token: {invite.token}"
    inviter = invite.invited_by.email if invite.invited_by else 'An admin'
    body = "\n".join([
        f"{inviter} invited you to join {invite.tenant.name} on SubStacky as {invite.get_role_display().lower()}.",
        "",
        action,
        "",
        f"This invite expires on {invite.expires_at:%d %b %Y}.",
    ])
    try:
        send_mail(f"You're invited to join {invite.tenant.name}", body, None, [invite.email])
    except Exception:
        logger.exception(f"Failed to send invite to {invite.email}")
