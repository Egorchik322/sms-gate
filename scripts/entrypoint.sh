#!/bin/sh
set -eu

runtime_dir=/run/sms-gateway
mkdir -p "$runtime_dir"
config_file="$runtime_dir/gammu-smsdrc"

sed \
  -e "s|@MODEM_DEVICE@|${MODEM_DEVICE:-/dev/huawei-e3272-sms}|g" \
  -e "s|@INBOX_PATH@|${GAMMU_INBOX_PATH:-/data/gammu/inbox}|g" \
  -e "s|@OUTBOX_PATH@|${GAMMU_OUTBOX_PATH:-/data/gammu/outbox}|g" \
  -e "s|@SENT_PATH@|${GAMMU_SENT_PATH:-/data/gammu/sent}|g" \
  -e "s|@ERROR_PATH@|${GAMMU_ERROR_PATH:-/data/gammu/error}|g" \
  config/gammu-smsdrc.template > "$config_file"

export GAMMU_CONFIG="$config_file"

mkdir -p "${GAMMU_INBOX_PATH:-/data/gammu/inbox}" "${GAMMU_OUTBOX_PATH:-/data/gammu/outbox}" \
  "${GAMMU_SENT_PATH:-/data/gammu/sent}" "${GAMMU_ERROR_PATH:-/data/gammu/error}" \
  "${GAMMU_ARCHIVE_PATH:-/data/gammu/processed}"

python3 -m app.main &
gateway_pid=$!
printf '%s\n' "$gateway_pid" > "$runtime_dir/gateway.proc"

gammu_pid=''
restart_delay=${GAMMU_RESTART_DELAY_SECONDS:-10}
stopping=false

pid_is_running() {
  pid=$1
  [ -r "/proc/$pid/stat" ] || return 1
  state=$(cut -d' ' -f3 "/proc/$pid/stat" 2>/dev/null || true)
  [ "$state" != Z ] && [ "$state" != X ]
}

start_gammu() {
  rm -f "$runtime_dir/gammu-smsd.pid" "$runtime_dir/gammu-smsd.proc"
  gammu-smsd --config "$config_file" --pid "$runtime_dir/gammu-smsd.pid" &
  gammu_pid=$!
  printf '%s\n' "$gammu_pid" > "$runtime_dir/gammu-smsd.proc"
}

terminate() {
  stopping=true
  if pid_is_running "$gateway_pid"; then
    kill -TERM "$gateway_pid" 2>/dev/null || true
  fi
  if [ -n "$gammu_pid" ] && pid_is_running "$gammu_pid"; then
    kill -TERM "$gammu_pid" 2>/dev/null || true
  fi
}
trap terminate TERM INT

while [ "$stopping" = false ]; do
  if ! pid_is_running "$gateway_pid"; then
    terminate
    wait "$gateway_pid" 2>/dev/null || true
    [ -z "$gammu_pid" ] || wait "$gammu_pid" 2>/dev/null || true
    exit 1
  fi

  if [ -z "$gammu_pid" ] || ! pid_is_running "$gammu_pid"; then
    if [ -n "$gammu_pid" ]; then
      wait "$gammu_pid" 2>/dev/null || true
    fi
    gammu_pid=''
    rm -f "$runtime_dir/gammu-smsd.pid" "$runtime_dir/gammu-smsd.proc"
    start_gammu
  fi
  sleep "$restart_delay"
done

wait "$gateway_pid" 2>/dev/null || true
[ -z "$gammu_pid" ] || wait "$gammu_pid" 2>/dev/null || true
exit 0
