#!/usr/bin/env bash
set -euo pipefail

STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=${BACKUP_DIR:-/mnt/d/Projet_dev_ck/onec_smart/backups}
CONTAINER=${DB_CONTAINER:-onec_smart-db-1}
DB=${DB_NAME:-onec_cpk}
USER=${DB_USER:-christian}

mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/onec_cpk_${STAMP}.sql"

docker exec "$CONTAINER" pg_dump -U "$USER" -d "$DB" > "$FILE"

echo "Backup created: $FILE"
