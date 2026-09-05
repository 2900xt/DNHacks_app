#!/usr/bin/env bash
# Turn the laptop into the AP the node joins, on 192.168.4.1 — the same address
# the Pi will use later, so config.h does not change when the Pi arrives.
#
# Use when: venue wifi is down, has AP isolation (clients cannot see each other),
# or is a captive portal the ESP32 cannot log into. That is most conference wifi.
#
# Costs you internet on the wifi radio for as long as it is up. Plug in ethernet
# or accept being offline. `./hotspot.sh down` gives the radio back.
set -euo pipefail

SSID="${HOTSPOT_SSID:-chokepoint}"
PASS="${HOTSPOT_PASS:-chokepoint2026}"   # WPA2 minimum is 8 chars
CON="chokepoint-ap"

command -v nmcli >/dev/null || { echo "needs NetworkManager (nmcli)"; exit 1; }

if [ "${1:-up}" = "down" ]; then
  nmcli connection down "$CON" 2>/dev/null || true
  echo "hotspot down"
  exit 0
fi

IFACE="${IFACE:-$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="wifi"{print $1; exit}')}"
[ -n "$IFACE" ] || { echo "no wifi device found. IFACE=<iface> $0"; exit 1; }

# Recreate rather than reuse: a stale profile with the old address is a worse
# five minutes than a redundant nmcli call.
nmcli connection delete "$CON" >/dev/null 2>&1 || true
nmcli connection add type wifi ifname "$IFACE" con-name "$CON" autoconnect no ssid "$SSID" >/dev/null
nmcli connection modify "$CON" \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS" \
  ipv4.method shared ipv4.addresses 192.168.4.1/24 \
  ipv6.method disabled >/dev/null
nmcli connection up "$CON" >/dev/null

cat <<TXT

  SSID      $SSID
  PASS      $PASS
  This host 192.168.4.1

  hardware/m5stack-node/include/config.h:
      #define WIFI_SSID  "$SSID"
      #define WIFI_PASS  "$PASS"
      #define API_BASE   "http://192.168.4.1:8000"

  Now: ./up.sh    (down again: ./hotspot.sh down)
TXT
