import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)

PAYSTACK_INTERVALS = {
    'monthly': 'monthly',
    'yearly': 'annually',
}


class PaystackError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = 'Payment provider request failed.'
    default_code = 'paystack_error'


def to_subunit(amount):
    """Paystack expects amounts in the currency subunit (kobo)."""
    return int(Decimal(amount) * 100)


class PaystackClient:

    def __init__(self, secret_key=None, base_url=None):
        self.secret_key = secret_key or settings.PAYSTACK_SECRET_KEY
        self.base_url = base_url or settings.PAYSTACK_BASE_URL

    def _request(self, method, path, payload=None):
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode('utf-8') if payload is not None else None,
            headers={
                'Authorization': f"Bearer {self.secret_key}",
                'Content-Type': 'application/json',
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.error(f"Paystack request to {path} failed: {e}")
            raise PaystackError()

        if not body.get('status'):
            logger.error(f"Paystack rejected {path}: {body.get('message')}")
            raise PaystackError(body.get('message') or None)
        return body['data']

    def _post(self, path, payload):
        return self._request('POST', path, payload)

    def create_plan(self, name, amount, interval):
        data = self._post('/plan', {
            'name': name,
            'amount': to_subunit(amount),
            'interval': PAYSTACK_INTERVALS[interval],
        })
        return data['plan_code']

    def initialize_transaction(self, email, amount, reference, plan_code=None, metadata=None):
        payload = {
            'email': email,
            'amount': to_subunit(amount),
            'reference': reference,
            'metadata': metadata or {},
        }
        if plan_code:
            payload['plan'] = plan_code
        if settings.PAYSTACK_CALLBACK_URL:
            payload['callback_url'] = settings.PAYSTACK_CALLBACK_URL
        return self._post('/transaction/initialize', payload)

    def disable_subscription(self, code, email_token):
        return self._post('/subscription/disable', {'code': code, 'token': email_token})

    def get_manage_link(self, code):
        """A Paystack-hosted page where the customer can update their card."""
        return self._request('GET', f"/subscription/{code}/manage/link")['link']
