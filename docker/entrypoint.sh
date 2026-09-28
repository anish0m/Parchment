#!/bin/sh
set -e

# Workers set DJANGO_MIGRATE=0 so only the web container migrates.
if [ "${DJANGO_MIGRATE:-1}" = "1" ]; then
    python manage.py migrate --noinput
    # The database cache used for rate limits in production (a no-op otherwise).
    python manage.py createcachetable
fi

# Dev runs from a bind mount and serves static files itself, so it skips this.
if [ "${DJANGO_COLLECTSTATIC:-1}" = "1" ]; then
    python manage.py collectstatic --noinput
fi

exec "$@"
