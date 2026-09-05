#!/usr/bin/env bash
# Serve services/api on an address the ESP32 node can actually reach, and print
# the exact config.h line to paste.
#
# The trap this avoids: `make dev` already binds 0.0.0.0, so people assume the
# node can reach it and spend twenty minutes debugging firmware. The usual
# culprits are (a) a firewall dropping :8000, (b) the laptop and the node being
# on different SSIDs, (c) AP isolation on venue wifi — which no amount of
# firmware work will fix. Check them here, before flashing.
set -uo pipefail
cd "$(dirname "$0")/../.."

PORT="${API_PORT:-8000}"

# Pick the address the node will dial. IFACE=wlan0 ./up.sh to force one.
ip_for() { ip -4 -o addr show dev "$1" scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1; }
if [ -n "${IFACE:-}" ]; then
  LAN_IP=$(ip_for "$IFACE")
else
  # Hotspot first: if we are the AP, that address is the one the node joins,
  # and it is not the default route.
  LAN_IP=$(ip -4 -o addr show scope global 2>/dev/null | awk '$4 ~ /^192\.168\.4\./ {print $4}' | cut -d/ -f1 | head -1)
  [ -n "$LAN_IP" ] || LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
fi

if [ -z "${LAN_IP:-}" ]; then
  echo "! could not determine a LAN address. Re-run as: IFACE=<iface> $0"
  ip -4 -o addr show scope global | awk '{printf "    %s  %s\n", $2, $4}'
  exit 1
fi

printf '\n  API   http://%s:%s\n' "$LAN_IP" "$PORT"
printf '  Flash this into hardware/esp32-node/include/config.h:\n\n'
printf '      #define API_BASE  "http://%s:%s"\n\n' "$LAN_IP" "$PORT"

# A firewall that drops :8000 looks exactly like broken firmware from the node.
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --query-port="$PORT/tcp" >/dev/null 2>&1 \
    || echo "  ! firewalld is up and $PORT/tcp is not open:
      sudo firewall-cmd --add-port=$PORT/tcp   # this boot only
"
elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw status | grep -q "$PORT" || echo "  ! ufw is active and $PORT is not allowed:
      sudo ufw allow $PORT/tcp
"
fi

API_HOST=0.0.0.0 API_PORT="$PORT" exec ./services/api/dev.sh
