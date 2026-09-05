# hardware/laptop-server/

The host the node reports to **right now**, until the Pi exists.

No server code lives here — the server is [`../../services/api/`](../../services/api/).
This directory is two scripts that put it on an address an ESP32 can dial.

## Use it

```bash
./up.sh                 # serve on the LAN, print the API_BASE line to flash
./hotspot.sh            # optional: become the AP on 192.168.4.1
./hotspot.sh down       # give the wifi radio back
```

`up.sh` prints the exact line to paste into
[`../esp32-node/include/config.h`](../esp32-node/include/config.h), then execs
`services/api/dev.sh` bound to `0.0.0.0`.

## When to reach for the hotspot

Venue wifi fails the node in three ways that all look like firmware bugs:

- **AP isolation** — clients cannot reach each other. Your laptop is on the
  network, the node is on the network, and the POST still times out.
- **Captive portal** — the ESP32 has no browser and will never accept the terms.
- **It is simply down**, at 13:00, along with everyone else's demo.

`hotspot.sh` sidesteps all three by making the laptop the network. It pins itself
to **192.168.4.1** on purpose: that is the address `pi-server/` will take, so
moving to the Pi later does not invalidate a flashed binary.

## Gotchas

- **`make dev` is not enough.** It binds `0.0.0.0` already, but a laptop firewall
  will drop `:8000` from anything but localhost, and that failure is silent from
  the device side. `up.sh` checks firewalld and ufw and tells you the command.
- **Laptop sleep kills the demo.** A closed lid drops the AP and the API together.
  Before demoing: `systemd-inhibit --what=sleep:idle sleep infinity &`, or just
  disable sleep in the desktop settings.
- **DHCP leases are not sticky.** The laptop's LAN IP changes between the hotel
  and the venue; `192.168.4.1` under `hotspot.sh` does not. Prefer the hotspot for
  anything you have flashed.
- **The replay path needs none of this.** `make depot-demo` works with no radio,
  no node, and no network. Keep it as the fallback — see
  [`../esp32-node/README.md`](../esp32-node/README.md).

## Verify the node can reach you

From another machine on the same network (a phone works):

```bash
curl -sf http://<printed-ip>:8000/health && echo reachable
```

If that fails, no amount of firmware debugging will help.
