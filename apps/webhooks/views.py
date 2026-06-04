import hmac
import hashlib
import json
import logging
from django.conf import settings
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import WebhookEvent
from .services import PaystackWebhookService

logger = logging.getLogger(__name__)

VALID_EVENTS = {
    'charge.success',
    'invoice.payment_failed',
    'subscription.updated'
}

@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(APIView):
    authentication_classes = []
    permission_classes = []
    http_method_names = ['post']

    def post(self, request):
        paystack_signature = request.META.get('HTTP_X_PAYSTACK_SIGNATURE')
        if not paystack_signature:
            return Response({'error': 'No signature'}, status=status.HTTP_400_BAD_REQUEST)

        raw_body = request.body
        expected_signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
            raw_body,
            hashlib.sha512
        ).hexdigest()

        if not hmac.compare_digest(expected_signature, paystack_signature):
            return Response({'error': 'Invalid signature'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return Response({'error': 'Invalid JSON'}, status=status.HTTP_400_BAD_REQUEST)

        event_type = payload.get('event')

        if event_type not in VALID_EVENTS:
            return Response({'message': 'Ignored event'}, status=status.HTTP_200_OK)

        reference = payload.get('data', {}).get('reference')
        event_id = f"{event_type}:{reference}"

        if WebhookEvent.objects.filter(event_id=event_id).exists():
            return Response({'message': 'Event already processed'}, status=status.HTTP_200_OK)

        try:
            with transaction.atomic():
                WebhookEvent.objects.create(
                    event_id=event_id,
                    event_type=event_type,
                    payload=payload
                )
                PaystackWebhookService().handle_event(event_type, payload.get('data', {}))
        except Exception as e:
            logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
            return Response({'error': 'Processing failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'message': 'Webhook processed'}, status=status.HTTP_200_OK)