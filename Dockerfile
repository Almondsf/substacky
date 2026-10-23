FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Settings require these at import time; dummy values are enough for collectstatic.
RUN SECRET_KEY=build ALLOWED_HOSTS=localhost PAYSTACK_SECRET_KEY=build \
    DB_NAME=x DB_USER=x DB_PASSWORD=x DB_HOST=x DB_PORT=5432 \
    python manage.py collectstatic --noinput

RUN useradd --create-home app && chown -R app /app && chmod +x docker/entrypoint.sh
USER app

EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
