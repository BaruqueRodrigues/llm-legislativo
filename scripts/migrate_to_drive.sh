#!/usr/bin/env bash
# Initial migration: preserve resume metadata, then archive verified raw blobs.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_dir"
: "${DATA_ROOT:?Configure DATA_ROOT externo antes de executar}"
snapshot_dir="$DATA_ROOT/staging/cloud_storage/snapshots"
snapshot_exists=0
for snapshot_receipt in "$snapshot_dir"/*.json; do
  if [[ -f "$snapshot_receipt" ]]; then
    snapshot_exists=1
    break
  fi
done
if [[ "$snapshot_exists" -eq 0 ]]; then
  printf '%s\n' 'Iniciando snapshot de inventários e checkpoints no Drive.'
  python3 scripts/cloud_storage.py --data-root "$DATA_ROOT" backup-state
else
  printf '%s\n' 'Snapshot verificado já existe; retomando a migração dos blobs.'
fi
python3 scripts/cloud_storage.py --data-root "$DATA_ROOT" offload --all --evict
printf '%s\n' 'Migração concluída: todos os blobs elegíveis no início foram arquivados e verificados.'
