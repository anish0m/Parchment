#!/bin/sh
set -e

# Workers set DJANGO_MIGRATE=0 so only the web container migrates.
if [ "${DJANGO_MIGRATE:-1}" = "1" ]; then
    python manage.py migrate --noinput
fi

# Dev runs from a bind mount and serves static files itself, so it skips this.
if [ "${DJANGO_COLLECTSTATIC:-1}" = "1" ]; then
    python manage.py collectstatic --noinput
fi

exec "$@"
