#!/bin/sh
# Checking Ledger backup service.
#
# Runs in its own container, separate from the app. It reads the data folder
# (mounted read-only), encrypts everything on this machine with restic, and
# uploads the encrypted result to S3-compatible storage such as Cloudflare R2.
# The storage provider only ever receives encrypted data.
#
#   backup.sh            back up now, then every day at BACKUP_TIME
#   backup.sh once       back up now and exit
#   backup.sh snapshots  list the backups that exist
#   backup.sh check      verify the stored backups are intact
#   backup.sh restore [snapshot]
#                        copy a backup (default: the latest) into the restore
#                        folder. It never writes into the live data folder.
set -eu

DATA_DIR="${DATA_DIR:-/data}"
STATUS_FILE="${STATUS_FILE:-/status/status.json}"
RESTORE_DIR="${RESTORE_DIR:-/restore}"
BACKUP_TIME="${BACKUP_TIME:-03:15}"
KEEP_DAILY="${KEEP_DAILY:-30}"
KEEP_WEEKLY="${KEEP_WEEKLY:-12}"
KEEP_MONTHLY="${KEEP_MONTHLY:-24}"
BACKUP_PRUNE="${BACKUP_PRUNE:-1}"
NAME="checking-ledger"
export RESTIC_CACHE_DIR="${RESTIC_CACHE_DIR:-/tmp/restic-cache}"
export HOME="${HOME:-/tmp}"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(now)" "$*"; }
fail() { log "ERROR: $*"; exit 2; }

# ------------------------------------------------------------------ settings
check_settings() {
  [ -n "${RESTIC_REPOSITORY:-}" ] || fail "RESTIC_REPOSITORY isn't set. Copy backup.env.example to backup.env and fill it in."
  if [ -n "${RESTIC_PASSWORD_FILE:-}" ]; then
    [ -r "$RESTIC_PASSWORD_FILE" ] || fail "Can't read RESTIC_PASSWORD_FILE."
    length=$(tr -d '\n' < "$RESTIC_PASSWORD_FILE" | wc -c)
  else
    length=$(printf '%s' "${RESTIC_PASSWORD:-}" | wc -c)
  fi
  [ "$length" -ge 20 ] || fail "RESTIC_PASSWORD must be at least 20 characters. It is the only thing protecting your backups."
  case "$RESTIC_REPOSITORY" in
    *http://*)
      # BACKUP_ALLOW_HTTP exists only so the tests can use a storage server
      # on the same machine. Never set it for real storage.
      [ "${BACKUP_ALLOW_HTTP:-0}" = 1 ] || fail "The storage address must use https:// (for R2: s3:https://...) so the connection is encrypted." ;;
  esac
  case "$RESTIC_REPOSITORY" in
    s3:*)
      [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ] || fail "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY aren't set."
      export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-auto}" ;;
  esac
  case "$BACKUP_TIME" in
    [01][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]) ;;
    *) fail "BACKUP_TIME should look like 03:15 (24-hour clock)." ;;
  esac
  for n in "$KEEP_DAILY" "$KEEP_WEEKLY" "$KEEP_MONTHLY"; do
    case "$n" in ''|*[!0-9]*) fail "KEEP_DAILY, KEEP_WEEKLY and KEEP_MONTHLY must be whole numbers." ;; esac
  done
}

# -------------------------------------------------------------------- status
# The app shows this file on its History page. It holds no secrets.
last_success() {
  [ -f "$STATUS_FILE" ] || return 0
  sed -n 's/.*"last_success": *"\([0-9TZ:-]*\)".*/\1/p' "$STATUS_FILE" | head -n 1
}

write_status() {
  ok="$1"
  message=$(printf '%s' "$2" | tr '\n\t' '  ' | tr -cd 'A-Za-z0-9 .,:_/()-' | cut -c1-200)
  attempt=$(now)
  if [ "$ok" = true ]; then success="$attempt"; else success=$(last_success); fi
  count=$(restic snapshots --json --no-lock 2>/dev/null | grep -o '"short_id"' | wc -l | tr -d ' ') || count=0
  tmp="$STATUS_FILE.tmp"
  if printf '{"version": 1, "ok": %s, "last_attempt": "%s", "last_success": "%s", "snapshots": %s, "message": "%s"}\n' \
       "$ok" "$attempt" "$success" "${count:-0}" "$message" > "$tmp" 2>/dev/null && mv "$tmp" "$STATUS_FILE"; then
    :
  else
    log "Couldn't write $STATUS_FILE (is the backup-status folder owned by PUID?)."
  fi
}

# -------------------------------------------------------------------- backup
# Every step is checked by hand: "set -e" does not apply inside a function
# that is called from an "if", so a failed step must return on its own.
ensure_repository() {
  problem=$(restic cat config 2>&1 >/dev/null) && return 0
  case "$problem" in
    *"wrong password"*)
      echo "RESTIC_PASSWORD does not match the backups already stored there"
      return 1 ;;
    *"Is there a repository at"*|*"does not exist"*)
      # Nothing is stored there yet. Creating a repository never overwrites
      # an existing one: restic refuses if it finds one.
      log "No backups stored at that address yet. Creating the repository."
      restic init || return 1 ;;
    *)
      echo "$problem"
      return 1 ;;
  esac
}

# Returns 0 when everything worked, 1 when the backup itself failed, and 3
# when the backup is safely stored but removing old backups failed.
backup_steps() {
  ensure_repository || return 1
  restic unlock || return 1
  restic backup "$DATA_DIR" --host "$NAME" --tag "$NAME" \
    --exclude "$DATA_DIR/.secret_key" --exclude "$DATA_DIR/.tmp-*" || return 1
  # Once a week, confirm that what is stored can still be read back.
  if [ "$(date +%u)" = 7 ]; then restic check || return 1; fi
  if [ "$BACKUP_PRUNE" = 1 ]; then
    restic forget --host "$NAME" --tag "$NAME" --group-by host,tags \
      --keep-daily "$KEEP_DAILY" --keep-weekly "$KEEP_WEEKLY" --keep-monthly "$KEEP_MONTHLY" --prune || return 3
  fi
  return 0
}

run_backup() {
  [ -d "$DATA_DIR" ] || { log "The data folder $DATA_DIR isn't there."; write_status false "The data folder is missing"; return 1; }
  output=$(mktemp)
  log "Backup starting."
  result=0
  backup_steps > "$output" 2>&1 || result=$?
  cat "$output"
  reason=$(grep -v '^[[:space:]]*$' "$output" | tail -n 1)
  rm -f "$output"
  case "$result" in
    0) write_status true ""
       log "Backup finished." ;;
    3) write_status true "Backed up, but removing old backups failed: $reason"
       log "Backup finished, but removing old backups failed." ;;
    *) write_status false "$reason"
       log "Backup FAILED."
       return 1 ;;
  esac
}

seconds_until_next() {
  current=$(date +%s)
  target=$(date -d "$(date +%Y-%m-%d) $BACKUP_TIME:00" +%s)
  [ "$target" -gt "$current" ] || target=$((target + 86400))
  echo $((target - current))
}

# ------------------------------------------------------------------ commands
command="${1:-run}"
check_settings
mkdir -p "$RESTIC_CACHE_DIR"

case "$command" in
  run)
    trap 'log "Stopping."; exit 0' TERM INT
    run_backup || true
    while true; do
      wait_for=$(seconds_until_next)
      log "Next backup at $BACKUP_TIME (in $((wait_for / 60)) minutes)."
      sleep "$wait_for" &
      wait $! || true
      run_backup || true
    done ;;
  once)
    run_backup ;;
  snapshots)
    restic snapshots --host "$NAME" ;;
  check)
    restic check ;;
  restore)
    snapshot="${2:-latest}"
    [ -d "$RESTORE_DIR" ] || fail "The restore folder $RESTORE_DIR isn't there."
    restic restore "$snapshot" --host "$NAME" --target "$RESTORE_DIR"
    log "Restored into the restore folder. Your live data was not touched." ;;
  *)
    fail "Unknown command '$command'. Use run, once, snapshots, check, or restore." ;;
esac
