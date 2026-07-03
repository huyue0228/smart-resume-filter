#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${RUN_SEED_BASE:-1}" = "1" ]; then
  python manage.py seed_base
fi

exec "$@"
