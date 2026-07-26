#!/bin/sh
set -eu

APP_ENV="${APP_ENV:-development}"
POSTGRES_DB="${POSTGRES_DB:-metro}"
POSTGRES_USER="${POSTGRES_USER:-metro}"
DB_READY_EXTRA_SLEEP="${DB_READY_EXTRA_SLEEP:-2}"

if [ -z "${DJANGO_DEBUG:-}" ]; then
  if [ "$APP_ENV" = "production" ]; then
    export DJANGO_DEBUG=false
  else
    export DJANGO_DEBUG=true
  fi
fi

if [ "$APP_ENV" = "production" ] && [ "${DJANGO_SECRET_KEY:-}" = "dev-only-change-me" ]; then
  echo "DJANGO_SECRET_KEY must be set for production." >&2
  exit 1
fi

until pg_isready -h db -p 5432 -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  echo "Waiting for Postgres..."
  sleep 2
done

sleep "$DB_READY_EXTRA_SLEEP"

python manage.py migrate
python manage.py bootstrap_owner --if-configured

if [ "$APP_ENV" = "production" ]; then
  exec gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-3}"
fi

exec python manage.py runserver 0.0.0.0:8000
