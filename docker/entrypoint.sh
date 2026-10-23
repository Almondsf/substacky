#!/bin/sh
set -e

# Set RUN_MIGRATIONS=0 to skip (e.g. for one-off commands or extra replicas).
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
