# openHAB side of the watchdog push bridge

Lives on the openHAB host (192.168.1.181), NOT the Pi. Mirrored here so the
whole alert path is version-controlled in one place.

- `amplipi_watchdog_alerts.js` → `/etc/openhab/automation/jsr223/`
- Item (in `/etc/openhab/items/amplipi.items`):

```
// Watchdog alert bridge: the Pi radio-watchdog (amplipi-radio-watchdog.py v4) POSTs
// PROBLEM/RECOVERY/GUARD lines here; amplipi_watchdog_alerts.js forwards them as push.
String   AmpliPi_Watchdog_Alert "AmpliPi waakhond [%s]"    <soundvolume>
```

The watchdog POSTs plain text to `/rest/items/AmpliPi_Watchdog_Alert`; the rule
maps prefixes to emoji (🎵 PROBLEM/WARNING, ✅ RECOVERY, 🛠️ GUARD, 🚨 MANUAL)
and calls sendBroadcastNotification. Dedupe lives watchdog-side.
