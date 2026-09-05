# Runbook

Things that will go wrong at 3am, and what to do.

## The service won't start
1. `cp .env.example .env` — did someone add a key you don't have?
2. Port already bound: `lsof -i :8000` then kill it.

## The UI shows nothing
1. `curl localhost:8000/health`
2. Check `PUBLIC_API_URL` in `.env` — on a second machine it must be the LAN IP,
   not `localhost`.
3. CORS: the API must allow the UI's origin. This bites every single time.

## The device isn't showing up
1. `ls /dev/ttyUSB* /dev/ttyACM*`
2. Permissions: `sudo usermod -aG uucp,dialout $USER` (log out and back in), or
   `sudo chmod 666 /dev/ttyUSB0` as a hackathon-grade fix.
3. Still nothing — switch to replay data and keep moving. Do not lose an hour here.

## Everything is broken and there are 4 hours left
Go to the brain repo and run `/cut`. Ship the degraded version.

## Add your own
Every time you lose more than 15 minutes to something, write it here. The next
person losing that time will be you, at 5am.
