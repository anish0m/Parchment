#!/bin/sh
set -e

python manage.py migrate --noinput

# Dev runs from a bind mount and serves static files itself, so it skips this.
if [ "${DJANGO_COLLECTSTATIC:-1}" = "1" ]; then
    python manage.py collectstatic --noinput
fi

exec "$@"
