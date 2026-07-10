# AmpliPi audio architecture — the definitive map (2026-07-10)

One page that explains the whole audio path, the rate policy, and every failure
mode we have hit — so no future change has to rediscover any of it. Live host:
`pi@192.168.1.138`. Mirrors in this repo: `site-config/` + `site-services/`.

## Signal chain (complete — there is nothing else)

```
Lyrion (LMS, port 9000, LSB unit "logitechmediaserver")
 ├── squeezelite-general  "General"  0d:b3:77:92:1f:4c   (radio)
 │     └─ ALSA: ch0      = plug → ch0_softvol (−7.1 dB pad) ──┐
 └── squeezelite-announce "Announce" 0d:b3:77:92:1f:4d   (TTS + siren)
       └─ ALSA: ch0boost = plug → ch0boost_softvol (0 dB) ────┤
                                                              ▼
                                        ch0_dmix (48000 Hz, ipc_key 2867)
                                                              ▼
                                        hw:sndrpihifiberry (onboard I2S PCM5102A)
                                                              ▼
                                        AmpliPi preamp source-0 input → zones
```

- openHAB reaches this via **two independent planes**: LMS JSON-RPC / squeezebox
  binding (what plays) and the AmpliPi REST API on :80 (zone volume/mute via
  preamp I2C — `rt.py`, NOT ALSA).
- The AmpliPi app manages **zero streams** (`streams=[]` in house.json). Both
  squeezelites are plain systemd **user** units (linger enabled).

## Rate policy (the "sampling" answer)

| Rule | Value | Why |
|---|---|---|
| Mix rate | **fixed 48000 Hz** (ch0_dmix slave) | sources vary; a mixer needs one rate; 48k suits the DAC |
| Conversion point | the `plug` layer of each client | squeezelite outputs source rate (no `-R`) |
| Converter quality | **`defaults.pcm.rate_converter "speexrate_medium"`** in asound.conf | without it libasound uses its built-in LINEAR interpolator → audible crackle on music |
| Device lifetime | both clients hold ch0_dmix open 24/7 (**no `-C`**) | close/reopen can wedge dmix IPC (ENODEV loop) |

**The one trap to remember:** sources are not all 48 kHz. VRT radio streams are
48 k (pass-through, no conversion); One World Radio / most webradio is 44.1 k
AAC (conversion active); TTS mp3s are 44.1/22.05 k. Any config that loses the
`rate_converter` line silently reverts music to linear resampling. Crackle on
44.1 k stations + clean 48 k stations = that line is missing.

## Failure modes we have actually hit (and their guards)

| # | Failure | Seen | Guard now |
|---|---|---|---|
| 1 | Duplicate dmix `ipc_key` across loopbacks → squeezelite crash-loop | 2026-06-08 | loopbacks deleted entirely; single dmix left |
| 2 | Linear resampler on 44.1→48 → crackling music | 2026-07-08..10 | `defaults.pcm.rate_converter speexrate_medium` (asound.conf, mirrored) |
| 3 | `-C 5` close-on-silence → stale dmix IPC → `alsa_open: No such device` loop (radio dead 8.2 h) | 2026-07-06 | no `-C` on either unit; watchdog ALSA-stuck auto-restart |
| 4 | Watchdog restarting on STALE journal lines after a real recovery | 2026-07-06 | v3.1 `--since <unit ActiveEnterTimestamp>` filter |
| 5 | Announce unwatched for ALSA-stuck (stays "active" while erroring) | risk, closed 2026-07-10 | v3.2 watches both units, per-unit cooldown |
| 6 | LMS logrotate USR1 half-kill (orphan holds ports, refuses new tracks) | 2026-07-04 | copytruncate logrotate + watchdog flood/dup checks |
| 7 | LMS double-boot race (`init.d/logitechmediaserver` S-links AND `lyrionmusicserver.service` enabled) | latent, found 2026-07-10 | lyrion disabled; LSB unit is the ONE LMS |
| 8 | RAM/CPU starvation → XRUNs (CUPS 205 MB; `-R hLE` idle burn; desktop stack) | 2026-06 / 2026-07 | cups masked; -R removed; desktop + 8 dead services pruned (console boot) |
| 9 | Preamp I2C wedge (Errno 121) — zone control dead, audio fine | 2026-06-04 | `rt.py _recover_preamps()` self-heal |
| 10 | ALSA config drift / hand edits lost | chronic | this repo mirrors `site-config/asound.conf` + units + watchdog; STRIPPED.md notes on-box |

## Watchdog (v4 — SELF-HEALING) — what it does every 60 s

Design rule: **every detectable problem has an automatic remediation**; mobile
push (via openHAB item `AmpliPi_Watchdog_Alert` → `amplipi_watchdog_alerts.js`)
is a *record* of what was auto-fixed, not a request for the owner to act.
Only 🚨 `MANUAL:` lines mean human attention is needed.

| Check | Auto-remediation |
|---|---|
| 0. Canonical config drift (`/etc/asound.conf` + both unit files vs `/home/pi/audio-canonical/`) | restore canonical + daemon-reload + restart players. 3 restores/hour → 🚨 MANUAL + pause (something keeps rewriting) |
| 1. LMS port-3483 flood | clean LMS restart (stop, pkill leftovers, start, resume play) |
| 2. Duplicate/orphan LMS processes | same clean LMS restart |
| 3. Player units not active | systemd Restart=always holds them; WARNING push if not |
| 4. ALSA-stuck per unit (≥5 `alsa_open` errors, `--since`-filtered) | restart that unit (per-unit 10-min cooldown) |
| 5. Synthetic chain probe every 5 min (1 s silence through ch0 at 44.1k — forces the speex converter to load, exercises plug→softvol→dmix→DAC, inaudible) | restart both players; still failing → 🚨 MANUAL |
| 6. load1 > 3.0 or MemAvailable < 100 MB | WARNING push (new resource hogs, before they become audible) |

Push dedupe: 15 min per identical text, 60 s global gap (RECOVERY lines exempt
— fix-confirmations always reach the phone).

**To change audio config intentionally**: edit the live file AND
`cp` it over `/home/pi/audio-canonical/<file>` — otherwise the watchdog reverts
it within 60 s (verified live 2026-07-10: drift → restored in 20 s).

Script: `/home/pi/amplipi-radio-watchdog.py` (mirror: `site-services/`,
canonicals mirrored in `site-config/audio-canonical/`).

## Recovery cheat-sheet

```bash
# Sound dead / weird — first look:
ssh pi@192.168.1.138 'journalctl --user -u squeezelite-general -u squeezelite-announce -u radio-watchdog -n 30 --no-pager'
# Nuclear (order matters: LMS first, then players):
ssh pi@192.168.1.138 'sudo systemctl restart logitechmediaserver && sleep 15 && XDG_RUNTIME_DIR=/run/user/1000 systemctl --user restart squeezelite-general squeezelite-announce'
# Zone control dead but audio fine = preamp I2C wedge:
curl -X POST http://192.168.1.138/api/reboot
# Full stock rollback lives at /home/pi/amplipi-stock-backup-20260610 (see STRIPPED.md)
```

## Deliberately NOT done (so nobody "fixes" these later)

- **PipeWire migration**: OS is Debian 10 armhf; dmix now has exactly two
  clients and one mix point. Risk ≫ benefit. Revisit only with a full OS
  rebuild.
- **`-R` (soxr) inside squeezelite**: redundant now that plug uses speex; soxr
  on the always-open Announce silence stream burned ~13% CPU continuously
  (removed 2026-07-08).
- **48 kHz TTS generation**: openHAB TTS engines emit fixed formats; speex
  conversion of speech is transparent. Not worth engine surgery.
