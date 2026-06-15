#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="$BACKUP_DIR/cosyvoice_backup_$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR"
cd "$ROOT_DIR"

tar -czf "$TARGET" \
  backend/storage \
  outputs \
  voices

echo "$TARGET"
