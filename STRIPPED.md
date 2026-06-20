# Stripped build — Lyrion (LMS/squeezelite) only

Removed stream types: airplay, aux, bluetooth, dlna, fm_radio, internet_radio,
media_device, pandora, plexamp, rca, spotify_connect.

Kept: lms (squeezelite/Lyrion) only. fileplayer is also removed — /api/announce
returns an error by design; openHAB TTS announcements use the Lyrion sink
(squeezebox:squeezeboxplayer:Amplipi:general) instead, which keeps working.

Bug fixes applied (2026-05-31):
- asound.conf: unique ipc_key per loopback (was all 1028), rate 48000 in dmixer
- process_monitor.py: exponential backoff before restart (was zero-delay)
- internet_radio.py: careful shutdown instead of bare kill()
- lms.py: preexec_fn=os.setpgrp on both Popen calls; safe killpg
- 85-amplipi-usb-audio.rules: USB autosuspend disabled for CM6206
- runvlc.py: explicit release of old VLC instance before restart

Reliability patch (2026-06-04):
- rt.py: zone-control I2C writes self-heal a wedged/hung preamp. On persistent
  EREMOTEIO (Errno 121) the existing bus-reopen retry now escalates to an
  in-place preamp reset + re-flush of cached registers 0x00-0x0A (the same
  recovery a full reboot performs, but without rebooting). Rate-limited 20s so a
  benign glitch never resets audio. Observed live 2026-06-04 07:31 (zone control
  dead until manual reboot). Also hot-patched into the live stock 0.4.10 firmware.

Deployed LIVE 2026-06-10 (replaced stock 0.4.10):
- Staged via hardlink clone + tar transfer, gated on py3.7 compileall + imports +
  venv dep coverage before any downtime. Audio gap during swap: ~25 s.
- house.json pruned to lms-only streams (aux + 4x rca removed) — REQUIRED:
  build_stream() raises on unknown types and ctrl loads config without try/except.
  Backup: ~/.config/amplipi/house.json.pre-stripped-20260610
- Stock install kept intact at /home/pi/amplipi-stock-backup-20260610 (venv reused
  via hardlinks — its deps are a superset of this build's requirements.txt).
- Revert: stop user units, mv dirs back, restore house.json backup, start units.

Recovery-only web UI (2026-06-10, second pass):
- web/dist replaced by a single redirect page → http://<host>:5001/update
  (control UI removed entirely; zones are managed via openHAB; Lyrion stays on :9000).
  Stock dist kept at web/dist.stock-0.4.10 on the unit.
- Updater UI: "Latest Release"/"Other Releases" (stock OTA) + "Support Tunnel" tabs
  hidden; Custom Update is the default tab; Revert tab appears after the first
  custom update creates a backup.
- Updater backend: POST /update/download (stock OTA fetch) returns 403.

Passwordless (2026-06-10, third pass — incident-driven):
- Timeline: removing nginx basic-auth coincided with a web password being set via
  the updater Admin Settings at 14:03 (users.json password_hash) → app auth turned
  on → the openHAB binding (no auth support, polls /api via :80) got 401s and zone
  control broke for ~15 min. The front display survived (uses the internal access_key).
- Resolution per owner decision: NO passwords anywhere.
  - admin password_hash removed from users.json (backup: users.json.bak-20260610-with-password)
  - POST /password (updater) returns 403; set_password_hash() in auth.py is a no-op
    with a warning; the Set Password card in Admin Settings is hidden.
  - nginx on :80 is a plain proxy (no basic-auth; htpasswd deleted;
    backup conf: /etc/nginx/sites-available/amplipi-auth.bak-with-password-20260610).
- To re-enable password auth: restore stock bodies of set_password_hash (auth.py)
  + set_admin_password (updater/asgi.py) + unhide the form — AND give openHAB an
  authenticated path first (e.g. nginx cookie-injection of a dedicated api-type
  user's access_key for <openhab-host> only), or zone control breaks again.
