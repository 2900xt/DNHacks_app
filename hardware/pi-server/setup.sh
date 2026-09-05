#!/usr/bin/env bash
# Provision a Raspberry Pi as the node's host: AP on 192.168.4.1 + the API on
# :8000 at boot. Run ON the Pi, from a checkout of this repo.
#
#   git clone <repo> ~/DNHacks_app && ~/DNHacks_app/hardware/pi-server/setup.sh
#
# NOT YET RUN AGAINST REAL HARDWARE — no Pi exists as of writing. Treat the
# nmcli block as the part most likely to need adjusting; everything else is
# ordinary systemd.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
SSID="${HOTSPOT_SSID:-chokepoint}"
PASS="${HOTSPOT_PASS:-chokepoint2026}"
CON="chokepoint-ap"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

echo "→ repo:  $REPO"
echo "→ user:  $RUN_USER"

# --- 1. deps ---------------------------------------------------------------
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip network-manager

# --- 2. the API's venv -----------------------------------------------------
# Built as the run user, not root: a root-owned .venv makes every later
# `pip install` on this Pi need sudo, which nobody remembers at 4am.
sudo -u "$RUN_USER" bash -c "
  cd '$REPO/services/api'
  [ -x .venv/bin/python ] || python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
"
[ -f "$REPO/.env" ] || sudo -u "$RUN_USER" cp "$REPO/.env.example" "$REPO/.env"

# --- 3. the access point ---------------------------------------------------
# 192.168.4.1 is pinned to match API_BASE in hardware/esp32-node/include/config.h.
# Pi OS Bookworm ships NetworkManager, so this is nmcli rather than the old
# hostapd + dnsmasq pair. If this Pi runs Bullseye or older, that pair is the
# fallback and this block will not apply cleanly.
IFACE="${IFACE:-$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="wifi"{print $1; exit}')}"
[ -n "$IFACE" ] || { echo "no wifi device. IFACE=<iface> sudo -E $0"; exit 1; }

nmcli connection delete "$CON" >/dev/null 2>&1 || true
nmcli connection add type wifi ifname "$IFACE" con-name "$CON" autoconnect yes ssid "$SSID" >/dev/null
nmcli connection modify "$CON" \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS" \
  ipv4.method shared ipv4.addresses 192.168.4.1/24 \
  ipv6.method disabled \
  connection.autoconnect-priority 100 >/dev/null
nmcli connection up "$CON" >/dev/null || echo "  ! AP did not come up; check 'nmcli device status'"

# --- 4. the service --------------------------------------------------------
sed -e "s|__REPO__|$REPO|g" -e "s|__USER__|$RUN_USER|g" \
  "$REPO/hardware/pi-server/chokepoint-api.service" > /etc/systemd/system/chokepoint-api.service
systemctl daemon-reload
systemctl enable --now chokepoint-api.service

# --- 5. prove it -----------------------------------------------------------
for _ in $(seq 1 15); do
  curl -sf http://127.0.0.1:8000/health >/dev/null && break || sleep 1
done
if curl -sf http://127.0.0.1:8000/health >/dev/null; then
  cat <<TXT

  ✓ API up, enabled at boot.

  SSID      $SSID
  PASS      $PASS
  This Pi   192.168.4.1:8000

  hardware/esp32-node/include/config.h already points here:
      #define API_BASE  "http://192.168.4.1:8000"

  Logs: journalctl -u chokepoint-api -f
TXT
else
  echo "  ! API did not answer /health. journalctl -u chokepoint-api -n 50"
  exit 1
fi
