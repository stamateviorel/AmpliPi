# Site services (live outside the AmpliPi tree, in /home/pi)

These files complete the direct-output architecture documented in
../STRIPPED.md. They survive AmpliPi updates because they live in
/home/pi, not in the amplipi tree. Install:

| file | destination |
|---|---|
| amplipi-radio-watchdog.py | /home/pi/ |
| squeezelite-general.service | ~/.config/systemd/user/ (enable --now) |
| squeezelite-announce.service | ~/.config/systemd/user/ (enable --now) |
| radio-watchdog.service | ~/.config/systemd/user/ (enable --now) |
| logrotate-lyrionmusicserver | /etc/logrotate.d/lyrionmusicserver |

- squeezelite-general/announce: the two LMS players, outputting directly
  into the ch0 dmix (no loopback/alsaloop). Fixed MACs = stable LMS +
  openHAB identities.
- radio-watchdog: LMS-health watchdog. Detects the port-3483 respawn
  flood / duplicate-server state (a logrotate USR1 once half-killed LMS
  -> silent burglar siren) and does a clean LMS restart within a minute.
- logrotate: copytruncate — never signals, never kills.

Remove any /etc/logrotate.d/logitechmediaserver leftover (duplicate
rotation of the same log was part of the incident).
