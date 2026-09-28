#!/bin/sh
# Backs up the database (pg_dump custom format) and uploaded files on a schedule,
# keeping BACKUP_KEEP_DAYS days of copies in /backups. Runs in the `backup` service
# of docker-compose.prod.yml; PG* variables say which database to dump. A one-off
# backup: docker compose -f docker-compose.prod.yml run --rm backup once
set -u

INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
mkdir -p /backups

backup() {
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    dump="/backups/parchment-db-$stamp.dump"
    if pg_dump --format=custom --file="$dump.partial"; then
        mv "$dump.partial" "$dump"
        echo "backup: wrote $dump ($(du -h "$dump" | cut -f1))"
    else
        rm -f "$dump.partial"
        echo "backup: pg_dump failed" >&2
    fi
    if [ -d /media ]; then
        media="/backups/parchment-media-$stamp.tar.gz"
        if tar -czf "$media.partial" -C /media .; then
            mv "$media.partial" "$media"
            echo "backup: wrote $media"
        else
            rm -f "$media.partial"
            echo "backup: archiving uploads failed" >&2
        fi
    fi
    find /backups -name 'parchment-*' -type f -mtime +"$KEEP_DAYS" -print -delete
}

# Wait for the database, then back up now and every INTERVAL seconds.
# `backup.sh once` takes a single backup and exits.
until pg_isready --quiet; do sleep 2; done
if [ "${1:-}" = "once" ]; then
    backup
    exit 0
fi
while true; do
    backup
    sleep "$INTERVAL"
done
