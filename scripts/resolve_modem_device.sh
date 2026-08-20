#!/bin/sh
set -eu

# Resolve the single AT tty without relying on ttyUSB ordering or by-id.
# MODEM_USB_PATH is an optional preferred physical-path filter.
usb_path=${MODEM_USB_PATH:-}
vendor_id=${MODEM_VENDOR_ID:-12d1}
product_ids=${MODEM_PRODUCT_IDS:-1506}
interface_num=${MODEM_INTERFACE_NUM:-00}
newline='\
'

candidates=''
preferred=''

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
  [ "$id_interface" = "$interface_num" ] || continue
  [ "$id_driver" = "option" ] || continue

  product_match=false
  old_ifs=$IFS
  IFS=,
  for product_id in $product_ids; do
    if [ "$id_product" = "$product_id" ]; then
      product_match=true
      break
    fi
  done
  IFS=$old_ifs
  [ "$product_match" = true ] || continue

  candidates="${candidates}${candidates:+$newline}$device"
  case "$id_path" in
    "$usb_path":*) preferred="${preferred}${preferred:+$newline}$device" ;;
  esac
done

choose_one() {
  value=$1
  count=$(printf '%s\n' "$value" | sed '/^$/d' | wc -l)
  if [ "$count" -eq 1 ]; then
    printf '%s\n' "$value"
    exit 0
  fi
  if [ "$count" -gt 1 ]; then
    printf '%s\n' "Multiple matching modem AT interfaces found:" >&2
    printf '%s\n' "$value" >&2
    exit 3
  fi
}

if [ -n "$usb_path" ]; then
  choose_one "$preferred"
fi
choose_one "$candidates"
printf '%s\n' 'No matching modem AT interface found' >&2
exit 1
