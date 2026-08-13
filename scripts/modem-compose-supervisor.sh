#!/bin/sh
set -eu

project_dir=${SMS_GATEWAY_PROJECT_DIR:-/workspace/sms-gateway}
interval=${MODEM_RESOLVE_INTERVAL_SECONDS:-5}
compose_service=${SMS_GATEWAY_COMPOSE_SERVICE:-sms-gateway}
last_identity=''

if ! command -v flock >/dev/null 2>&1; then
  printf '%s\n' 'flock is required' >&2
  exit 2
fi

cd "$project_dir"
exec 9>"${SMS_GATEWAY_LOCK_FILE:-/run/lock/sms-gateway-modem.lock}"
flock -n 9 || exit 0

while :; do
  device=''
  if device=$(./scripts/resolve_modem_device.sh 2>/dev/null); then
    properties=$(udevadm info --query=property --name="$device" 2>/dev/null || true)
    identity=$(printf '%s\n' "$device" "$properties" | sed -n '/^ID_PATH=/p; /^ID_MODEL_ID=/p; /^ID_USB_INTERFACE_NUM=/p; /^ID_USB_DRIVER=/p' | sha256sum | cut -d' ' -f1)
    if [ "$identity" != "$last_identity" ]; then
      MODEM_HOST_DEVICE="$device" docker compose up -d --force-recreate "$compose_service"
      last_identity=$identity
    fi
  else
    # Force recreation when the same tty number is allocated again after unplug.
    last_identity=''
  fi
  sleep "$interval"
done
