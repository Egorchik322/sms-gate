#!/bin/sh
set -eu

# Resolve the current tty number without relying on ttyUSB ordering or by-id.
# udevadm is read-only here; the script never opens the modem port.
usb_path=${MODEM_USB_PATH:-}
vendor_id=${MODEM_VENDOR_ID:-12d1}
product_ids=${MODEM_PRODUCT_IDS:-1506}
interface_num=${MODEM_INTERFACE_NUM:-00}

if [ -z "$usb_path" ]; then
  printf '%s\n' 'MODEM_USB_PATH is required' >&2
  exit 2
fi

for device in /dev/ttyUSB*; do
  [ -e "$device" ] || continue
  properties=$(udevadm info --query=property --name="$device" 2>/dev/null || true)
  [ -n "$properties" ] || continue

  id_vendor=$(printf '%s\n' "$properties" | sed -n 's/^ID_VENDOR_ID=//p')
  id_product=$(printf '%s\n' "$properties" | sed -n 's/^ID_MODEL_ID=//p')
  id_interface=$(printf '%s\n' "$properties" | sed -n 's/^ID_USB_INTERFACE_NUM=//p')
  id_driver=$(printf '%s\n' "$properties" | sed -n 's/^ID_USB_DRIVER=//p')
  id_path=$(printf '%s\n' "$properties" | sed -n 's/^ID_PATH=//p')

  [ "$id_vendor" = "$vendor_id" ] || continue
  old_ifs=$IFS
  IFS=,
  product_match=false
  for product_id in $product_ids; do
    if [ "$id_product" = "$product_id" ]; then
      product_match=true
      break
    fi
  done
  IFS=$old_ifs
  [ "$product_match" = true ] || continue
  [ "$id_interface" = "$interface_num" ] || continue
  [ "$id_driver" = "option" ] || continue
  case "$id_path" in
    "$usb_path":*) printf '%s\n' "$device"; exit 0 ;;
  esac
done

printf '%s\n' 'No matching modem AT interface found' >&2
exit 1
