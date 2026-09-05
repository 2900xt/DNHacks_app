# hardware/pi-server/

The node's host **after** the Pi is built. Not built yet — this is the plan and
the provisioning that implements it.

No server code lives here either. The server is
[`../../services/api/`](../../services/api/); this is a systemd unit, an AP
config, and a script that installs both.

## Why bother, when the laptop already works

One reason: **the venue's network stops being able to break the demo.** The Pi is
its own access point, so the node's path to the API never touches infrastructure
someone else controls. Secondary: the whole system becomes a thing you carry to
the table and plug in, rather than a laptop with terminals open on it.

That is worth doing *after* the demo works end to end on the laptop, and not one
minute before.

## Parts

| | |
|---|---|
| Board | Pi 4 or Pi Zero 2 W — anything with onboard wifi. A Zero 2 W is enough; the API is in-memory FastAPI |
| OS | Pi OS **Bookworm** or newer. Bookworm ships NetworkManager, which is what `setup.sh` drives |
| Power | 5 V supply, not a laptop USB port. An underpowered Pi browns out mid-demo and blames the SD card |
| Storage | Any 8 GB+ card |

## Provision

```bash
# on the Pi
git clone <this repo> ~/DNHacks_app
sudo ~/DNHacks_app/hardware/pi-server/setup.sh
```

That does four things:

1. Installs `python3-venv` and NetworkManager; builds the API's venv **as the
   login user**, not root.
2. Brings up an AP — SSID `chokepoint`, pinned to **192.168.4.1/24**.
3. Installs and enables `chokepoint-api.service` so the API returns after a
   power cut without anyone logging in.
4. Polls `/health` and fails loudly if the API never answered.

Override the network with `HOTSPOT_SSID=… HOTSPOT_PASS=… IFACE=… sudo -E ./setup.sh`.

## Why 192.168.4.1 specifically

Because [`../esp32-node/include/config.h`](../esp32-node/include/config.h) already
says so, and a flashed binary is expensive to correct at a venue. Pinning the Pi
to the address the firmware already believes in means the laptop → Pi migration
is a power cable, not a reflash. `laptop-server/hotspot.sh` uses the same address
for the same reason.

## Expect these

- **`ipv4.method shared` needs a working `dnsmasq` under NetworkManager.** It is
  what hands the ESP32 a lease. If the node associates but never gets an IP, this
  is why — `journalctl -u NetworkManager` says so plainly.
- **AP mode and client mode on one radio do not mix.** While the Pi is the AP it
  has no upstream internet on wifi. Provision it *before* you need it, or give it
  ethernet.
- **Bullseye and older have no NetworkManager**, and want `hostapd` + `dnsmasq`
  instead. `setup.sh` does not cover that path. Flash Bookworm.
- **Clock.** A Pi with no RTC and no internet boots to 1970. Harmless here only
  because the API stamps receipt time itself and `DEPOT_TRUST_DEVICE_TS` is off
  for real devices — but check it before blaming an MKT window.
- **Do not `git pull` on the Pi during the demo window.** The service runs
  straight out of the checkout.

## Checks

```bash
systemctl status chokepoint-api
journalctl -u chokepoint-api -f
nmcli device status                       # the wifi device should say "connected" on chokepoint-ap
curl -sf http://192.168.4.1:8000/health   # from a phone joined to the AP
```

## Fallback

If the Pi is not ready, `../laptop-server/` is a drop-in replacement at the same
address. If the network is not ready at all, `make depot-demo` replays 24h of
history with no radio involved. Neither beat in the demo requires this directory
to exist.
