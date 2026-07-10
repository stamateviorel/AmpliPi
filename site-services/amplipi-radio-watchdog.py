#!/usr/bin/env python3
"""LMS-health watchdog (v4 — SELF-HEALING: canonical config enforcement,
synthetic chain probe, auto-recovery for every known failure mode; mobile
push is a RECORD of what was auto-fixed, not a request for the owner to act).

After the 2026-07-04 silent-siren incident and the direct-output migration
(squeezelite -> ch0 dmix, no loopback/alsaloop), the remaining single point
of failure for ALL audio (radio, TTS announcements, burglar siren) is the
LMS server itself. Failure signature observed 2026-07-04 00:00:10:
a logrotate USR1 hit the squeezeboxserver_safe bash wrapper -> wrapper
respawn loop ("Can't listen on port 3483: Address already in use" every
5 s) while an orphaned server kept the ports but refused NEW track loads
(playlist play -> mode=stop) and logged into a deleted inode.

2026-07-06: added detection for squeezelite-general ALSA-stuck state.
When the VRT sessioned stream URL expires, LMS stops sending audio, and
squeezelite (formerly with -C 5) closed the ALSA device. On reopen,
ch0_dmix IPC shared memory could be in a stale state -> "playback open
error: No such device" loop. Fix: squeezelite-general.service no longer
uses -C 5 (device stays open permanently). Belt-and-suspenders: if ALSA
errors appear in squeezelite-general journal -> restart the unit (not LMS).

v3.1 (2026-07-10): ALSA-error window is --since-filtered to the unit's
current incarnation (stale pre-restart lines fired 1-2 bogus restarts).
v3.2 (2026-07-10): ALSA-stuck check covers BOTH squeezelite units.

v4.0 (2026-07-10) — "never rough again" self-healing:
  A. CANONICAL CONFIG ENFORCEMENT: /etc/asound.conf and both squeezelite
     unit files are compared each cycle against /home/pi/audio-canonical/*.
     Any drift (e.g. a stock-AmpliPi update rewriting asound.conf and
     dropping defaults.pcm.rate_converter -> LINEAR resampling -> crackle,
     bitten 2026-07-08..10) is restored automatically and the players are
     restarted. To change audio config INTENTIONALLY: edit the live file
     AND cp it over the canonical copy. 3 restores/hour -> MANUAL escalation
     (something keeps rewriting) and enforcement pauses.
  B. SYNTHETIC CHAIN PROBE every 5 cycles: aplay 1 s of silence through
     ch0 at 44100 (forces the speex converter to load; exercises
     plug -> softvol -> dmix -> DAC). Failure -> restart both players;
     still failing after that -> MANUAL escalation.
  C. RESOURCE PRESSURE: load1 > 3.0 or MemAvailable < 100 MB -> WARNING
     (the known causes - cups, desktop, celery - were removed 2026-07-10;
     this catches new ones before they become audible).
  D. MOBILE PUSH: every PROBLEM/RECOVERY/GUARD/WARNING/MANUAL line is also
     POSTed to openHAB item AmpliPi_Watchdog_Alert (rule
     amplipi_watchdog_alerts.js forwards as broadcast push). Dedup: 15 min
     per identical text, 60 s global gap. The 2026-07-06 outage ran 8 h
     unnoticed; that can no longer happen silently.

Checks every 60 s:
  0. canonical config drift (self-heal, see A)
  1. flood: "Address already in use" in the last minute of server.log
  2. orphan/dup: more than one main squeezeboxserver perl process
  3. player units: squeezelite-general / squeezelite-announce active
     (systemd Restart=always should hold them; log if not)
  4. per-unit ALSA stuck: >= 5 "alsa_open" errors in last 20 journal lines
     of the CURRENT incarnation -> restart that unit
  5. chain probe (every 5th cycle, see B)
Recovery for 1/2: full clean LMS restart (stop service, kill leftovers,
start), then resume radio playback if it was playing. Max once per 10 min.
Recovery for 4/5: restart squeezelite unit(s). Separate 10 min cooldowns.
"""
import os
import subprocess
import time
import json
import urllib.request

GENERAL = "0d:b3:77:92:1f:4c"
LMS = "http://localhost:9000/jsonrpc.js"
LOG = "/var/log/squeezeboxserver/server.log"
CYCLE_S = 60
COOLDOWN_S = 600
PROBE_EVERY = 5  # cycles
FLOOD_PATTERN = "Address already in use"
XDG_ENV = {"XDG_RUNTIME_DIR": "/run/user/1000", "HOME": "/home/pi",
            "USER": "pi", "PATH": "/usr/bin:/bin:/sbin"}

OPENHAB_ALERT_URL = "http://192.168.1.181:8080/rest/items/AmpliPi_Watchdog_Alert"

CANON_DIR = "/home/pi/audio-canonical"
CANON = {
    "/etc/asound.conf": CANON_DIR + "/asound.conf",
    "/home/pi/.config/systemd/user/squeezelite-general.service":
        CANON_DIR + "/squeezelite-general.service",
    "/home/pi/.config/systemd/user/squeezelite-announce.service":
        CANON_DIR + "/squeezelite-announce.service",
}

_pushed = {}
_last_push_global = 0.0


def push_alert(msg):
    """Best-effort mobile push via openHAB (never blocks/breaks the loop)."""
    global _last_push_global
    now = time.time()
    if now - _pushed.get(msg, 0.0) < 900:
        return
    # RECOVERY confirmations always get through (fix-record must reach the phone)
    if not msg.startswith("RECOVERY") and now - _last_push_global < 60:
        return
    _pushed[msg] = now
    _last_push_global = now
    try:
        req = urllib.request.Request(
            OPENHAB_ALERT_URL, data=msg.encode(),
            headers={"Content-Type": "text/plain"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


def log(msg):
    print(msg, flush=True)
    if msg.startswith(("PROBLEM", "RECOVERY", "GUARD", "WARNING", "MANUAL")):
        push_alert(msg)


def lms_request(player, cmd, timeout=5):
    body = json.dumps({"id": 1, "method": "slim.request",
                       "params": [player, cmd]}).encode()
    req = urllib.request.Request(LMS, data=body,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def flood_lines_recent():
    """Count flood lines in the last ~40 lines of server.log (recent only)."""
    try:
        out = subprocess.run(["tail", "-40", LOG], stdout=subprocess.PIPE,
                             timeout=10).stdout.decode(errors="replace")
        return out.count(FLOOD_PATTERN)
    except Exception:
        return 0


def main_server_count():
    """Main perl LMS processes (not the safe wrapper, not helpers)."""
    try:
        out = subprocess.run(["pgrep", "-f",
                              "perl /usr/sbin/squeezeboxserver --prefsdir"],
                             stdout=subprocess.PIPE, timeout=10)
        pids = [p for p in out.stdout.decode().split() if p.strip()]
        return len(pids)
    except Exception:
        return -1


def unit_active(name):
    r = subprocess.run(["systemctl", "--user", "is-active", name],
                       stdout=subprocess.PIPE, env=XDG_ENV, timeout=10)
    return r.stdout.decode().strip() == "active"


def general_mode():
    try:
        return lms_request(GENERAL, ["status", "-", 1])["result"].get("mode")
    except Exception:
        return None


def unit_start_time(name):
    """Local 'YYYY-MM-DD HH:MM:SS' when the unit last became active, or None."""
    try:
        r = subprocess.run(["systemctl", "--user", "show", "-p",
                            "ActiveEnterTimestamp", "--value", name],
                           stdout=subprocess.PIPE, env=XDG_ENV, timeout=10)
        parts = r.stdout.decode().strip().split()
        # "Mon 2026-07-06 14:46:49 CEST" -> "2026-07-06 14:46:49"
        if len(parts) >= 3:
            return "%s %s" % (parts[1], parts[2])
    except Exception:
        pass
    return None


def squeezelite_alsa_errors_recent(unit):
    """Count ALSA open errors in the last 20 journal lines of the CURRENT
    incarnation of the given squeezelite unit (see v3.1/v3.2 notes above)."""
    try:
        cmd = ["journalctl", "--user-unit", unit,
               "-n", "20", "--no-pager", "-q"]
        since = unit_start_time(unit)
        if since:
            cmd += ["--since", since]
        out = subprocess.run(cmd, stdout=subprocess.PIPE, env=XDG_ENV,
                             timeout=10).stdout.decode(errors="replace")
        return out.count("alsa_open")
    except Exception:
        return 0


def restart_squeezelite_unit(unit):
    """Restart a squeezelite unit to clear a stuck ALSA dmix state."""
    log("RECOVERY: restarting %s (stuck ALSA state)" % unit)
    subprocess.run(["systemctl", "--user", "restart", unit],
                   timeout=30, env=XDG_ENV)
    time.sleep(5)
    mode = general_mode()
    log("RECOVERY: %s restarted, LMS mode=%s" % (unit, mode))


def clean_restart_lms(was_playing):
    log("RECOVERY: clean LMS restart (stop, kill leftovers, start)")
    subprocess.run(["sudo", "systemctl", "stop", "logitechmediaserver"],
                   timeout=60)
    time.sleep(2)
    # bracket pattern so we never match our own cmdline
    subprocess.run(["sudo", "pkill", "-f", "squeezeboxserv[e]r"], timeout=10)
    time.sleep(3)
    subprocess.run(["sudo", "systemctl", "start", "logitechmediaserver"],
                   timeout=60)
    time.sleep(20)
    if was_playing:
        try:
            lms_request(GENERAL, ["play"])
            log("RECOVERY: radio playback resumed")
        except Exception as exc:
            log("RECOVERY: resume play failed: %s" % exc)


def config_selfheal():
    """Restore any drifted audio config from the canonical copies and restart
    the players so they reopen on the restored config. Returns True if
    anything was restored. Canonical missing -> that file is not enforced."""
    restored = []
    for live, canon in CANON.items():
        try:
            want = open(canon).read()
        except Exception:
            continue
        try:
            have = open(live).read()
        except Exception:
            have = None
        if have != want:
            try:
                if live.startswith("/etc/"):
                    subprocess.run(["sudo", "cp", canon, live], timeout=10)
                else:
                    subprocess.run(["cp", canon, live], timeout=10)
                restored.append(os.path.basename(live))
            except Exception as exc:
                log("MANUAL: could not restore %s from canonical: %s"
                    % (live, exc))
    if restored:
        log("GUARD: config drift detected + restored from canonical: %s"
            % ", ".join(restored))
        subprocess.run(["systemctl", "--user", "daemon-reload"],
                       env=XDG_ENV, timeout=30)
        for u in ("squeezelite-announce", "squeezelite-general"):
            subprocess.run(["systemctl", "--user", "restart", u],
                           env=XDG_ENV, timeout=30)
        log("RECOVERY: players restarted on canonical config")
    return bool(restored)


def chain_probe():
    """End-to-end synthetic check: write 1 s of silence through ch0 at
    44100 Hz. Forces the speex rate converter to load and exercises
    plug -> softvol -> ch0_dmix -> DAC. Inaudible (silence mixes in)."""
    try:
        r = subprocess.run(
            ["timeout", "5", "aplay", "-D", "ch0", "-f", "S16_LE",
             "-r", "44100", "-c", "2", "-q", "-d", "1", "/dev/zero"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def resource_pressure():
    load1 = None
    mem_kb = None
    try:
        load1 = os.getloadavg()[0]
    except Exception:
        pass
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                mem_kb = int(line.split()[1])
                break
    except Exception:
        pass
    return load1, mem_kb


def main():
    log("lms-health watchdog v4.0 started (cycle=%ss)" % CYCLE_S)
    time.sleep(60)  # boot grace
    last_recovery = 0.0
    last_sq_recovery = {}
    last_probe_recovery = 0.0
    probe_escalated = False
    last_config_restore = 0.0
    config_restores = []
    config_flap_escalated = False
    cycle = 0
    while True:
        try:
            cycle += 1
            now = time.time()

            # --- 0. canonical config enforcement (self-heal) ---
            config_restores = [t for t in config_restores if now - t < 3600]
            if now - last_config_restore > COOLDOWN_S:
                if len(config_restores) >= 3:
                    if not config_flap_escalated:
                        log("MANUAL: audio config restored %d times in the "
                            "last hour - something keeps rewriting it; "
                            "enforcement paused" % len(config_restores))
                        config_flap_escalated = True
                elif config_selfheal():
                    last_config_restore = now
                    config_restores.append(now)
                    config_flap_escalated = False

            flood = flood_lines_recent()
            servers = main_server_count()
            problem = None
            if flood >= 3:
                problem = "port-3483 flood (%d recent lines)" % flood
            elif servers > 1:
                problem = "%d main LMS processes (dup/orphan)" % servers
            elif servers == 0:
                problem = "no main LMS process"

            if problem:
                log("PROBLEM: %s" % problem)
                if time.time() - last_recovery > COOLDOWN_S:
                    was_playing = general_mode() == "play"
                    clean_restart_lms(was_playing)
                    last_recovery = time.time()
                else:
                    log("in cooldown; skipping recovery")

            # Belt-and-suspenders: catch squeezelite ALSA-stuck state.
            # squeezelite-general no longer uses -C 5, so this should be rare,
            # but if the dmix IPC goes stale (e.g. after amplipi restart or a
            # Pi hardware glitch), we auto-recover without touching LMS.
            for unit in ("squeezelite-general", "squeezelite-announce"):
                alsa_errors = squeezelite_alsa_errors_recent(unit)
                if alsa_errors >= 5:
                    log("PROBLEM: %s ALSA stuck "
                        "(%d alsa_open errors in last 20 lines)"
                        % (unit, alsa_errors))
                    if time.time() - last_sq_recovery.get(unit, 0.0) > COOLDOWN_S:
                        restart_squeezelite_unit(unit)
                        last_sq_recovery[unit] = time.time()
                    else:
                        log("in squeezelite cooldown; skipping recovery")

            # --- 5. synthetic end-to-end probe ---
            if cycle % PROBE_EVERY == 0:
                if chain_probe():
                    probe_escalated = False
                else:
                    log("PROBLEM: ch0 chain probe failed (cannot play "
                        "through plug->speex->dmix->DAC)")
                    if time.time() - last_probe_recovery > COOLDOWN_S:
                        for u in ("squeezelite-announce",
                                  "squeezelite-general"):
                            restart_squeezelite_unit(u)
                        last_probe_recovery = time.time()
                    elif not probe_escalated:
                        log("MANUAL: ch0 probe still failing after player "
                            "restart - check DAC/dmix/alsa-plugins")
                        probe_escalated = True

            # --- resource pressure (known causes pruned 2026-07-10;
            #     this catches NEW ones before they become audible) ---
            load1, mem_kb = resource_pressure()
            if load1 is not None and load1 > 3.0:
                log("WARNING: load average %.2f - audio starvation risk"
                    % load1)
            if mem_kb is not None and mem_kb < 100 * 1024:
                log("WARNING: MemAvailable %d MB - audio starvation risk"
                    % (mem_kb // 1024))

            for u in ("squeezelite-general", "squeezelite-announce"):
                if not unit_active(u):
                    log("WARNING: %s not active (systemd should restart it)"
                        % u)
        except Exception as exc:
            log("watchdog cycle error: %s" % exc)
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    main()
