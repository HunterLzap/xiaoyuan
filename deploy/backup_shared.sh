#!/usr/bin/env bash
set -euo pipefail

SHARED_DIR="${SHARED_DIR:-/opt/xiaodan/shared}"
BACKUP_DIR="${BACKUP_DIR:-/opt/xiaodan/backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
DRY_RUN=0
BACKUP_NAME='20[0-9][0-9][01][0-9][0-3][0-9]-[0-2][0-9][0-5][0-9][0-5][0-9]'

usage() {
  printf '%s\n' \
    'Usage: backup_shared.sh [--shared-dir <path>] [--backup-dir <path>]' \
    '                        [--keep-days <N>] [--dry-run] [-h|--help]'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --shared-dir|--backup-dir|--keep-days)
      if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
        usage >&2
        exit 2
      fi
      case "$1" in
        --shared-dir) SHARED_DIR="$2" ;;
        --backup-dir) BACKUP_DIR="$2" ;;
        --keep-days) KEEP_DAYS="$2" ;;
      esac
      shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if [[ ! "$KEEP_DAYS" =~ ^[0-9]+$ ]]; then
  printf '%s\n' '--keep-days requires a non-negative integer.' >&2
  exit 2
fi

dest_dir="${BACKUP_DIR}/$(date +%Y%m%d-%H%M%S)"
if [[ "$DRY_RUN" -eq 1 ]]; then
  printf '[dry-run] Check sqlite3 and source directory %s\n' "$SHARED_DIR"
  printf '[dry-run] Create %s (700) and its data directory\n' "$dest_dir"
  printf '[dry-run] SQLite .backup %s/data/*.sqlite3 into %s/data/\n' "$SHARED_DIR" "$dest_dir"
  printf '[dry-run] Copy %s/data/*.json and optional .env (600) into %s\n' "$SHARED_DIR" "$dest_dir"
  printf '[dry-run] Remove timestamped backups older than %s days from %s\n' "$KEEP_DAYS" "$BACKUP_DIR"
  exit 0
fi

if ! command -v sqlite3 >/dev/null; then
  printf '%s\n' 'sqlite3 is required.' >&2
  exit 1
fi
if [[ ! -d "$SHARED_DIR" ]]; then
  printf 'Shared directory does not exist: %s\n' "$SHARED_DIR" >&2
  exit 1
fi

umask 077
mkdir -p -- "$BACKUP_DIR"
mkdir -m 700 -- "$dest_dir"
mkdir -- "$dest_dir/data"
shopt -s nullglob

for db in "$SHARED_DIR"/data/*.sqlite3; do
  target="$dest_dir/data/${db##*/}"
  target=${target//\\/\\\\}
  target=${target//\"/\\\"}
  sqlite3 "$db" ".backup \"$target\""
done
for json in "$SHARED_DIR"/data/*.json; do
  cp -- "$json" "$dest_dir/data/"
done
if [[ -f "$SHARED_DIR/.env" ]]; then
  cp -- "$SHARED_DIR/.env" "$dest_dir/.env"
  chmod 600 -- "$dest_dir/.env"
fi

find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name "$BACKUP_NAME" \
  ! -name "${dest_dir##*/}" ! -newermt "$KEEP_DAYS days ago" -exec rm -rf -- {} +
