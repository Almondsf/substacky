# SubStacky

Multi-tenant subscription API built on Django REST Framework and Paystack. Each tenant (a publication, creator or business) defines plans; their users subscribe, pay through Paystack, and get access to gated content.

## Features

- **Tenants and teams:** tenant signup with a first admin, email invites, member roles
- **Plans and checkout:** plans sync to Paystack; checkout returns a Paystack payment link
- **Webhooks:** signed and deduplicated; handle activation, renewals, failures and cancellation
- **Dunning:** past-due emails with a card-update link, auto-cancel after a grace period
- **Content gating:** `HasActiveSubscription` permission and an access endpoint for frontends
- **Admin dashboard API:** subscribers, payments, MRR and 30-day revenue
- **Tenant resolution:** via the `X-Tenant` header or a subdomain

## Quick start (Docker)

```bash
cp .env.example .env        # set SECRET_KEY and PAYSTACK_SECRET_KEY
docker compose up --build
```

The API runs at http://localhost:8000 and the interactive docs at http://localhost:8000/api/docs/. Migrations run automatically on start. Create an admin user with:

```bash
docker compose exec web python manage.py createsuperuser
```

## Local development

Requires Python 3.12 and PostgreSQL.

```bash
python -m venv venv
venv/Scripts/activate       # Windows; use venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env        # point DB_* at your Postgres
python manage.py migrate
python manage.py runserver
```

`manage.py` uses `config.settings.dev`. WSGI/ASGI (gunicorn) default to `config.settings.prod`.

## Configuration

All settings come from environment variables or `.env`. See [.env.example](.env.example).

| Variable | Required | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | yes | Django secret key |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | yes | PostgreSQL connection |
| `PAYSTACK_SECRET_KEY` | yes | Paystack API key; also verifies webhook signatures |
| `ALLOWED_HOSTS` | prod | Comma-separated hostnames |
| `PAYSTACK_CALLBACK_URL` | no | Where Paystack returns customers after checkout |
| `INVITE_ACCEPT_URL` | no | Frontend page that accepts `?token=` invites |
| `TENANT_BASE_DOMAIN` | no | Resolve tenants from subdomains, e.g. `acme.example.com` |
| `DUNNING_GRACE_DAYS` | no | Days past due before cancellation (default 7) |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | no | SMTP; emails print to the console by default |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `CSRF_TRUSTED_ORIGINS` | no | Production HTTPS settings |

## Paystack setup

1. In the Paystack dashboard, set the webhook URL to `https://<your-api>/api/webhooks/paystack/`.
2. Plans created through the API are created on Paystack automatically.
3. Subscription lifecycle:

   ```
   POST /checkout/  -> pending subscription + authorization_url
   customer pays    -> charge.success       -> active, payment recorded
                    -> subscription.create  -> Paystack subscription linked
   renewal fails    -> invoice.payment_failed -> past_due + email
   still unpaid after DUNNING_GRACE_DAYS -> process_dunning cancels it
   ```

## Scheduled jobs

Run daily (cron, a scheduler, or a platform job):

```bash
python manage.py process_dunning            # add --dry-run to preview
# with Docker:
docker compose run --rm -e RUN_MIGRATIONS=0 web python manage.py process_dunning
```

## Tenants

Every request may name a tenant with the `X-Tenant: <slug>` header, or with a subdomain when `TENANT_BASE_DOMAIN` is set. On a tenant request:

- unknown tenants return 404
- authenticated users from another tenant get 403
- registration joins that tenant
- `GET /api/tenants/current/` returns the tenant and its plans, with no login required

## API overview

Full, interactive reference: `/api/docs/`.

| Endpoint | Who | Description |
| --- | --- | --- |
| `POST /api/tenants/register/` | anyone | Create tenant + first admin |
| `GET /api/tenants/current/` | anyone | Current tenant and its plans |
| `POST /api/accounts/register/` | anyone | Sign up as a member |
| `POST /api/accounts/login/` | anyone | Get JWT access/refresh tokens |
| `GET/PATCH /api/accounts/me/` | user | Own profile |
| `GET/POST /api/accounts/invites/` | admin | List or send invites |
| `GET/POST /api/accounts/invites/accept/` | anyone | Preview or accept an invite |
| `GET /api/accounts/members/` | admin | Team members; `PATCH`/`DELETE` by id |
| `GET/POST /api/subscriptions/plans/` | user / admin | List plans; admins create them |
| `POST /api/subscriptions/checkout/` | user | Start a subscription |
| `GET /api/subscriptions/subscriptions/` | user | Own subscriptions |
| `POST /api/subscriptions/subscriptions/<id>/cancel/` | user | Cancel |
| `GET /api/subscriptions/access/` | user | What the user can access |
| `GET /api/subscriptions/payments/` | user | Own payment history |
| `GET /api/subscriptions/tenant/subscriptions/` | admin | All subscribers (`?status=`) |
| `GET /api/subscriptions/tenant/payments/` | admin | All payments |
| `GET /api/subscriptions/tenant/metrics/` | admin | MRR, revenue, status counts |
| `POST /api/webhooks/paystack/` | Paystack | Signed webhook receiver |

## Gating your own views

```python
from core.permissions import HasActiveSubscription

class PremiumPostView(APIView):
    permission_classes = [HasActiveSubscription]
    required_plans = [PREMIUM_PLAN_ID]   # optional: limit to specific plans
```

## Tests

```bash
python manage.py test
```

CI runs the tests against PostgreSQL, checks for missing migrations and OpenAPI warnings, and smoke-tests the Docker stack.
