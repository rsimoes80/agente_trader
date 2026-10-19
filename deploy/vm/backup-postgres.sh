#!/usr/bin/env bash
set -euo pipefail
umask 077
project_root="$(cd "$(dirname "$0")/../.." && pwd)"
backup_dir="$project_root/data/database_backups"
mkdir -p "$backup_dir"
backup_file="$backup_dir/agente_trader-$(date -u +%Y%m%dT%H%M%S)-$$.sql.gz"
docker exec postgres pg_dump -U agente_trader_app -d agente_trader --no-owner --no-acl | gzip > "$backup_file"
printf '%s\n' "$backup_file"
