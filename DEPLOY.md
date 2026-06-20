# AmpliPi — Lyrion-only stripped build: deployment manual

This build is a drop-in replacement for the stock AmpliPi firmware.
No openHAB changes required. All zone volume/mute/routing continues to work
via the same REST API the AmpliPi binding already uses.

**What changed vs stock firmware:**
- Only LMS (Lyrion/squeezelite) stream type — all others removed
- Audio routes through Source 0 → HiFiBerry (I2S) only — CM6206 USB chip is idle
- 6 bug fixes: ALSA ipc_key, rate lock, restart backoff, process management, USB autosuspend
- `/api/announce` and `/api/play` return an error (use Lyrion TTS instead)
- Updater web UI gains a **Revert** tab (appears after first update)
- python-vlc, celery, redis, bluetooth, DLNA, Pandora dependencies removed

---

## Prerequisites

- SSH access to the AmpliPi Pi (`pi@<amplipi-ip>`, default password `amplipi`)
- AmpliPi running stock firmware (any recent version)
- openHAB server has access to this repo at `/home/openhab/work/AmpliPi`

---

## Method 1 — Deploy via updater web UI (recommended)

This is the safest method. The updater handles everything and creates a
rollback point automatically.

### Step 1 — Package the repo as a tar.gz

Run this on the openHAB server (where the repo lives):

```bash
cd /home/openhab/work
tar -czf /tmp/amplipi-lyrion-stripped.tar.gz \
  --transform 's|^AmpliPi|amplipi-lyrion-stripped|' \
  --exclude='AmpliPi/.git' \
  --exclude='AmpliPi/web/uploads' \
  --exclude='AmpliPi/web/backup' \
  --exclude='AmpliPi/__pycache__' \
  --exclude='AmpliPi/**/__pycache__' \
  AmpliPi/
```

### Step 2 — Upload via web UI

1. Open `http://<amplipi-ip>:5001/update` in a browser
2. Click the **Custom Update** tab
3. Select `/tmp/amplipi-lyrion-stripped.tar.gz`
4. Click **Start Update**
5. Watch the Update Log panel — installation takes ~2 minutes
6. The page will reload automatically when done

### Step 3 — Verify

```bash
# Check the API responds
curl -s http://<amplipi-ip>/api | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('streams:', [s['name']+'/'+s['type'] for s in d['streams']])
print('zones:', [z['name'] for z in d['zones']])
"
# Expected: streams: ['General/lms']  zones: ['Office', 'Wc up', ...]

# Check squeezelite is running and connected to Lyrion
ssh pi@<amplipi-ip> 'systemctl --user status amplipi | head -5'
```

---

## Method 2 — Deploy via SSH (direct copy)

Use this if the updater is not running or the unit is freshly flashed.

```bash
# 1. Copy files to AmpliPi
rsync -av --exclude='.git' --exclude='__pycache__' --exclude='web/uploads' \
  /home/openhab/work/AmpliPi/ pi@<amplipi-ip>:~/amplipi/

# 2. SSH in and run the installer
ssh pi@<amplipi-ip> << 'EOF'
  cd ~/amplipi

  # Install Python dependencies
  pip3 install --user -r requirements.txt

  # Copy ALSA config (the fixed version with unique ipc_keys + rate 48000)
  sudo cp config/asound.conf /etc/asound.conf

  # Copy udev rule (disables CM6206 USB autosuspend)
  sudo cp config/85-amplipi-usb-audio.rules /etc/udev/rules.d/85-amplipi-usb-audio.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger

  # Restart the AmpliPi service
  systemctl --user restart amplipi

  # Wait and verify
  sleep 5
  systemctl --user status amplipi | head -10
EOF
```

---

## Updating to a new version of this build

After the first deployment, future updates go through the updater web UI.
A backup of the current installation is created automatically before each update.

```
1. Package new version as tar.gz (same command as Method 1, Step 1)
2. Open http://<amplipi-ip>:5001/update
3. Custom Update tab → upload tar.gz → Start Update
4. Wait for completion and automatic restart
```

The **Revert** tab will appear in the updater after the first update,
showing the backup date and size.

---

## Reverting to the previous version

If an update breaks something:

```
1. Open http://<amplipi-ip>:5001/update
2. Click the Revert tab (only visible when a backup exists)
3. Click "Revert to Previous Version"
4. Confirm the dialog
5. Watch the Update Log panel
6. The unit restarts automatically when done
```

The revert restores: `amplipi/`, `streams/`, `config/`, `pyproject.toml`,
`requirements.txt`. User config (`~/.config/amplipi/`) is never touched.

---

## Full reflash (factory reset)

Use this if the unit is completely broken and SSH is still accessible.

```bash
ssh pi@<amplipi-ip> << 'EOF'
  cd ~/amplipi

  # Stop services
  systemctl --user stop amplipi amplipi-updater amplipi-tasks

  # Remove user config (zones, presets, stream assignments)
  rm -rf ~/.config/amplipi/

  # Re-run the installer
  python3 scripts/configure.py

  systemctl --user status amplipi | head -5
EOF
```

This restores the default config: 1 LMS stream "General", 6 unnamed zones,
all on source 0, all muted.

---

## Verifying the installation

Run these checks after any deployment:

```bash
# 1. API responds with correct stream types
curl -s http://<amplipi-ip>/api | python3 -c "
import json,sys
d = json.load(sys.stdin)
streams = d['streams']
assert len(streams) == 1, f'Expected 1 stream, got {len(streams)}'
assert streams[0]['type'] == 'lms', f'Expected lms, got {streams[0][\"type\"]}'
print('OK: 1 lms stream —', streams[0]['name'])
print('OK:', len(d['zones']), 'zones')
"

# 2. Updater responds
curl -s http://<amplipi-ip>:5001/update/version

# 3. squeezelite is running and connected to Lyrion
ssh pi@<amplipi-ip> 'ps aux | grep squeezelite | grep -v grep'

# 4. HiFiBerry is the active audio output (not CM6206)
ssh pi@<amplipi-ip> 'aplay -l | grep -E "hifiberry|cmedia"'
# HiFiBerry should appear. CM6206 may appear but will be idle.

# 5. Zone volume control works from openHAB
# In openHAB: adjust a zone slider — verify it moves
```

---

## Troubleshooting

### squeezelite not visible in Lyrion

```bash
ssh pi@<amplipi-ip>
# Check squeezelite process
ps aux | grep squeezelite
# Check LMS connection log
tail -50 ~/.config/amplipi/srcs/v0/lms_log.txt
# Restart amplipi service
systemctl --user restart amplipi
```

### No audio output

```bash
ssh pi@<amplipi-ip>
# Check HiFiBerry is loaded
aplay -l | grep hifiberry
# Check ALSA loopback module is loaded
lsmod | grep snd_aloop
# Check alsaloop is running (bridges loopback to HiFiBerry)
ps aux | grep alsaloop | grep -v grep
```

### Volume control not working from openHAB

The AmpliPi binding uses `PATCH /api/zones/{id}`. Verify the API responds:

```bash
# Set zone 0 to 50% volume
curl -s -X PATCH http://<amplipi-ip>/api/zones/0 \
  -H "Content-Type: application/json" \
  -d '{"vol_f": 0.5}' | python3 -c "import json,sys; print(json.load(sys.stdin))"
```

### Updater revert tab not showing

The Revert tab only appears after the **first update via the web UI**.
On initial deployment via SSH (Method 2), no backup exists yet.
Do one update via the web UI to create the first backup.

### Services stuck after update

```bash
ssh pi@<amplipi-ip>
systemctl --user restart amplipi amplipi-updater
systemctl --user status amplipi | head -20
```

---

## File locations on the AmpliPi Pi

| Path | Purpose |
|---|---|
| `~/amplipi/` | Application code (this repo) |
| `~/.config/amplipi/` | User config: zones, streams, presets, stream state |
| `~/.config/amplipi/srcs/v0/` | squeezelite log + LMS metadata |
| `/etc/asound.conf` | ALSA routing config (fixed ipc_keys + rate) |
| `/etc/udev/rules.d/85-amplipi-usb-audio.rules` | CM6206 naming + USB autosuspend disable |
| `~/amplipi/web/backup/previous.tar.gz` | Pre-update backup (created by updater) |
| `~/amplipi/web/uploads/update.tar.gz` | Last uploaded update package |

---

## Key differences from stock firmware for support

If contacting MicroNova support, note:
- This is a modified build — do not use the stock OTA update URL
- `/api/announce` returns an error by design (use Lyrion TTS)
- Only `lms` stream type is available
- The Revert tab in the updater is a local addition
