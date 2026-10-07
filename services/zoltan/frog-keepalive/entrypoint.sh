#!/bin/sh
set -eu

umask 077

SSH_DIR=/home/keepalive/.ssh
KEY_FILE="$SSH_DIR/frog_keepalive"
KNOWN_HOSTS_FILE="$SSH_DIR/known_hosts"
LAST_SUCCESS_FILE=/data/last_success

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

require_uint() {
  value="$(eval "printf '%s' \"\${$1}\"")"
  case "$value" in
    ''|*[!0-9]*)
      log "ERROR: $1 must be a non-negative integer"
      exit 2
      ;;
  esac
}

FROG_HOST="${FROG_HOST:-frog01.mikr.us}"
FROG_PORT="${FROG_PORT:-11157}"
FROG_USER="${FROG_USER:-frog}"
FROG_HOST_KEY_SHA256="${FROG_HOST_KEY_SHA256:-}"
KEEPALIVE_INTERVAL_DAYS="${KEEPALIVE_INTERVAL_DAYS:-60}"
MAX_JITTER_SECONDS="${MAX_JITTER_SECONDS:-21600}"
RETRY_SECONDS="${RETRY_SECONDS:-3600}"
CHECK_SECONDS="${CHECK_SECONDS:-3600}"
CONNECT_TIMEOUT_SECONDS="${CONNECT_TIMEOUT_SECONDS:-20}"

for variable in FROG_PORT KEEPALIVE_INTERVAL_DAYS MAX_JITTER_SECONDS RETRY_SECONDS CHECK_SECONDS CONNECT_TIMEOUT_SECONDS; do
  require_uint "$variable"
done

if [ "$KEEPALIVE_INTERVAL_DAYS" -eq 0 ] || [ "$RETRY_SECONDS" -eq 0 ] || [ "$CHECK_SECONDS" -eq 0 ] || [ "$CONNECT_TIMEOUT_SECONDS" -eq 0 ]; then
  log "ERROR: interval, retry, check, and timeout values must be greater than zero"
  exit 2
fi

interval_seconds=$((KEEPALIVE_INTERVAL_DAYS * 86400))

case "$FROG_HOST_KEY_SHA256" in
  SHA256:*) ;;
  *)
    log "ERROR: FROG_HOST_KEY_SHA256 must be the trusted SHA256 host-key fingerprint"
    exit 2
    ;;
esac

mkdir -p "$SSH_DIR" /data
chmod 700 "$SSH_DIR"

if [ ! -f "$KEY_FILE" ]; then
  log "Generating the dedicated Frog keepalive key"
  ssh-keygen -q -t ed25519 -N '' -C frog-keepalive -f "$KEY_FILE"
fi

if [ ! -f "$KEY_FILE.pub" ]; then
  ssh-keygen -y -f "$KEY_FILE" | awk '{ print $1 " " $2 " frog-keepalive" }' > "$KEY_FILE.pub"
fi

chmod 600 "$KEY_FILE" "$KEY_FILE.pub"

print_authorized_key() {
  printf '%s ' 'restrict,command="/usr/bin/uptime"'
  cat "$KEY_FILE.pub"
}

verify_known_hosts() {
  if [ -s "$KNOWN_HOSTS_FILE" ]; then
    if ssh-keygen -lf "$KNOWN_HOSTS_FILE" -E sha256 2>/dev/null | awk '{ print $2 }' | grep -Fxq "$FROG_HOST_KEY_SHA256"; then
      return 0
    fi

    log "ERROR: persisted host key does not match FROG_HOST_KEY_SHA256; refusing to replace it"
    return 1
  fi

  scan_file="/tmp/frog-keyscan.$$"
  candidate_file="/tmp/frog-key-candidate.$$"
  verified_file="/tmp/frog-key-verified.$$"
  trap 'rm -f "$scan_file" "$candidate_file" "$verified_file"' EXIT HUP INT TERM

  log "Scanning $FROG_HOST:$FROG_PORT and verifying its host-key fingerprint"
  if ! ssh-keyscan -T "$CONNECT_TIMEOUT_SECONDS" -p "$FROG_PORT" "$FROG_HOST" > "$scan_file" 2>/dev/null; then
    log "ERROR: could not retrieve the Frog host key"
    return 1
  fi

  : > "$verified_file"
  while IFS= read -r host_key; do
    [ -n "$host_key" ] || continue
    printf '%s\n' "$host_key" > "$candidate_file"
    fingerprint="$(ssh-keygen -lf "$candidate_file" -E sha256 2>/dev/null | awk 'NR == 1 { print $2 }')"
    if [ "$fingerprint" = "$FROG_HOST_KEY_SHA256" ]; then
      printf '%s\n' "$host_key" >> "$verified_file"
    fi
  done < "$scan_file"

  if [ ! -s "$verified_file" ]; then
    log "ERROR: scanned host keys do not match FROG_HOST_KEY_SHA256"
    return 1
  fi

  mv "$verified_file" "$KNOWN_HOSTS_FILE"
  chmod 600 "$KNOWN_HOSTS_FILE"
  rm -f "$scan_file" "$candidate_file"
  trap - EXIT HUP INT TERM
}

run_login() {
  log "Connecting to $FROG_USER@$FROG_HOST:$FROG_PORT"

  # Requesting `false` proves that Frog is overriding arbitrary commands with
  # the authorized_keys forced command. A correctly restricted key prints
  # uptime and exits 0; an unrestricted key runs false and fails this check.
  if /usr/bin/ssh \
    -T \
    -i "$KEY_FILE" \
    -o IdentitiesOnly=yes \
    -o BatchMode=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile="$KNOWN_HOSTS_FILE" \
    -o GlobalKnownHostsFile=/dev/null \
    -o PasswordAuthentication=no \
    -o KbdInteractiveAuthentication=no \
    -o ConnectTimeout="$CONNECT_TIMEOUT_SECONDS" \
    -p "$FROG_PORT" \
    "$FROG_USER@$FROG_HOST" false; then
    date +%s > "$LAST_SUCCESS_FILE.tmp"
    mv "$LAST_SUCCESS_FILE.tmp" "$LAST_SUCCESS_FILE"
    log "Keepalive login succeeded and the forced command was confirmed"
    next_due=$(($(cat "$LAST_SUCCESS_FILE") + interval_seconds))
    log "Next login becomes due at $(date -u -d "@$next_due" '+%Y-%m-%dT%H:%M:%SZ'), followed by up to $MAX_JITTER_SECONDS seconds of jitter"
    return 0
  fi

  log "ERROR: login failed or the key did not enforce the forced command"
  return 1
}

log "Restricted authorized_keys entry to install on Frog:"
print_authorized_key

if [ "${1:-daemon}" = public-key ]; then
  exit 0
fi

if ! verify_known_hosts; then
  if [ "${1:-daemon}" = daemon ]; then
    log "Host-key verification will retry after the container restarts in $RETRY_SECONDS seconds"
    sleep "$RETRY_SECONDS"
  fi
  exit 1
fi

case "${1:-daemon}" in
  public-key)
    # Handled before host verification so this remains an offline operation.
    exit 0
    ;;
  once)
    run_login
    exit $?
    ;;
  daemon) ;;
  *)
    log "ERROR: expected one of: daemon, once, public-key"
    exit 2
    ;;
esac

while :; do
  now="$(date +%s)"
  last_success=0

  if [ -s "$LAST_SUCCESS_FILE" ]; then
    last_success="$(cat "$LAST_SUCCESS_FILE")"
    case "$last_success" in
      ''|*[!0-9]*)
        log "ERROR: invalid last-success state; refusing to overwrite it"
        exit 1
        ;;
    esac
  fi

  due_at=$((last_success + interval_seconds))
  if [ "$now" -ge "$due_at" ]; then
    jitter=0
    if [ "$last_success" -ne 0 ] && [ "$MAX_JITTER_SECONDS" -ne 0 ]; then
      random_value="$(od -An -N4 -tu4 /dev/urandom | tr -d ' ')"
      jitter=$((random_value % (MAX_JITTER_SECONDS + 1)))
    fi

    if [ "$jitter" -gt 0 ]; then
      log "Login is due; delaying this attempt by $jitter seconds"
      sleep "$jitter"
    fi

    if ! run_login; then
      log "Retrying in $RETRY_SECONDS seconds"
      sleep "$RETRY_SECONDS"
    fi
    continue
  fi

  sleep_for=$((due_at - now))
  if [ "$sleep_for" -gt "$CHECK_SECONDS" ]; then
    sleep_for="$CHECK_SECONDS"
  fi
  sleep "$sleep_for"
done
