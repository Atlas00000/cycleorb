#!/usr/bin/env bash
# INF-P5-T05: nightly Postgres dump + the write-once landing zone, kept 14 days locally, copied off-host when
# CORB_BACKUP_TARGET is set (any rsync destination, e.g. user@backup-host:/srv/cycleorb).
set -euo pipefail

ROOT=${CORB_ROOT:-/opt/cycleorb}
DEST=${CORB_BACKUP_DIR:-/var/backups/cycleorb}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$DEST"

set -a; . "$ROOT/infra/.env"; set +a
docker exec cycleorb-db-1 pg_dump -U "${CORB_DB_USER:-corb}" -d "${CORB_DB_NAME:-corb}" -Fc > "$DEST/corb_$STAMP.dump"
tar -C "$ROOT/var" -czf "$DEST/landing_$STAMP.tgz" landing
find "$DEST" -type f -mtime +14 -delete

if [ -n "${CORB_BACKUP_TARGET:-}" ]; then
  rsync -a "$DEST/" "$CORB_BACKUP_TARGET/"
fi
echo "backup $STAMP ok"
