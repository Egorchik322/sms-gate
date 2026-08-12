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

mkdir -p "${GAMMU_INBOX_PATH:-/data/gammu/inbox}" "${GAMMU_OUTBOX_PATH:-/data/gammu/outbox}" \
  "${GAMMU_SENT_PATH:-/data/gammu/sent}" "${GAMMU_ERROR_PATH:-/data/gammu/error}" \
  "${GAMMU_ARCHIVE_PATH:-/data/gammu/processed}"

gammu-smsd --config "$config_file" --pid "$runtime_dir/gammu-smsd.pid" &
gammu_pid=$!
printf '%s\n' "$gammu_pid" > "$runtime_dir/gammu-smsd.proc"

python3 -m app.main &
gateway_pid=$!
printf '%s\n' "$gateway_pid" > "$runtime_dir/gateway.proc"

terminate() {
  kill -TERM "$gateway_pid" 2>/dev/null || true
  kill -TERM "$gammu_pid" 2>/dev/null || true
}
trap terminate TERM INT

while kill -0 "$gateway_pid" 2>/dev/null && kill -0 "$gammu_pid" 2>/dev/null; do
  sleep 2
done
terminate
wait "$gateway_pid" 2>/dev/null || true
wait "$gammu_pid" 2>/dev/null || true
exit 1
