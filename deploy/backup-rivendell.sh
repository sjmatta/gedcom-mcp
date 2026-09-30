#!/usr/bin/env bash
# GEDCOM-only snapshots through Rivendell's existing encrypted Restic repositories.
# Uses the same host lock as whole-stack backups, without depending on its audit.
set -Eeuo pipefail
umask 077
root="${GEDCOM_BACKUP_ROOT:-/home/sjmatta/docker}"
store="${GEDCOM_HOST_STORE:-/home/sjmatta/.local/share/gedcom-mcp/store}"
mkdir -p "$root/backups" "$store/replication"
exec 9>"$root/backups/all-backups.lock"
flock -w 3600 9 || { echo "Timed out waiting for Rivendell backup lock"; exit 1; }
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
snapshot="snapshot-$stamp.sqlite"
docker exec gedcom-mcp python -m gedcom_server.recovery snapshot \
  /state/tree.sqlite "/state/replication/$snapshot"
for target in s3 nas; do
  container="restic-$target"
  if [[ "$target" == nas ]]; then
    [[ "$(findmnt -rn -t nfs,nfs4 -T /mnt/nas-backup/restic -o SOURCE)" == '192.168.5.37:/volume1/DockerBackup' ]] \
      || { echo "Expected NAS mount unavailable"; exit 1; }
  fi
  [[ "$(docker inspect -f '{{.State.Running}}' "$container")" == true ]] \
    || docker start "$container" >/dev/null
  docker exec "$container" restic backup --host rivendell --tag gedcom-mcp \
    "/source/external/gedcom-mcp-data/store/replication/$snapshot"
  # Prove that the saved database can be downloaded, not merely listed.
  restore="$(mktemp "$store/replication/.restore-XXXXXX")"
  trap 'rm -f "$restore"' EXIT
  docker exec "$container" restic dump --host rivendell --tag gedcom-mcp latest \
    "/source/external/gedcom-mcp-data/store/replication/$snapshot" >"$restore"
  cmp "$store/replication/$snapshot" "$restore"
  rm -f "$restore"
  trap - EXIT
  docker exec "$container" restic forget --host rivendell --tag gedcom-mcp \
    --group-by host,tags --keep-last 3 --keep-daily 30 --keep-monthly 12
  # Pruning shared repository packs stays with the existing whole-stack job.
done
# Only remove old replication staging files after BOTH destinations succeeded.
find "$store/replication" -maxdepth 1 -name 'snapshot-*.sqlite' -type f \
  ! -name "$snapshot" -delete
echo "GEDCOM revision snapshot saved and read back from NAS and S3: $snapshot"
