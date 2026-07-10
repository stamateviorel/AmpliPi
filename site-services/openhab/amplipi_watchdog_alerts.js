// =============================================================================
// amplipi_watchdog_alerts.js — Pi radio-watchdog → mobile push bridge
//
// The AmpliPi Pi runs amplipi-radio-watchdog.py (v4): LMS health, squeezelite
// ALSA-stuck recovery, asound.conf config guard, synthetic ch0 chain probe,
// resource pressure. It POSTs each PROBLEM/RECOVERY/GUARD/WARNING line to
// AmpliPi_Watchdog_Alert (REST, dedupe done watchdog-side: 15 min per text,
// 60 s global). This rule turns those into mobile push so audio failures are
// never silent again (the 2026-07-06 radio outage ran 8 h unnoticed).
//
// Related: items/amplipi.items, pi:/home/pi/amplipi-radio-watchdog.py,
//          /home/openhab/work/amplipi-rebase/AUDIO_ARCHITECTURE.md
// =============================================================================

const ruleName = "AmpliPiWatchdogAlerts";
const { rules, triggers } = require('openhab');
const { sendBroadcastNotification } = require('shared_utils');

rules.JSRule({
  name: "AmpliPi watchdog alert push",
  description: "Forwards radio-watchdog PROBLEM/RECOVERY/GUARD lines as mobile push",
  triggers: [triggers.ItemCommandTrigger('AmpliPi_Watchdog_Alert')],
  execute: (event) => {
    try {
      const msg = String(event.receivedCommand || '').trim();
      if (!msg) return;
      const emoji = msg.startsWith('RECOVERY') ? '✅'
                  : msg.startsWith('GUARD')    ? '🛠️'
                  : msg.startsWith('MANUAL')   ? '🚨'
                  : '🎵';
      sendBroadcastNotification(`${emoji} AmpliPi: ${msg}`, 'soundvolume', 'amplipi-watchdog');
      console.info(`${ruleName}: pushed "${msg}"`);
    } catch (e) {
      if (String(e.message || e).includes('Context is already closed')) return;
      console.error(`${ruleName}: ${e}`);
    }
  }
});

console.info(`${ruleName}: loaded`);
