#!/usr/bin/env python3
"""LMS-health watchdog (v3 — adds squeezelite ALSA-stuck recovery).

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

Checks every 60 s:
  1. flood: "Address already in use" in the last minute of server.log
  2. orphan/dup: more than one main squeezeboxserver perl process
  3. player units: squeezelite-general / squeezelite-announce active
     (systemd Restart=always should hold them; log if not)
  4. squeezelite-general ALSA stuck: >= 5 "alsa_open" errors in last
     20 journal lines -> restart squeezelite-general (not LMS)
Recovery for 1/2: full clean LMS restart (stop service, kill leftovers,
start), then resume radio playback if it was playing. Max once per 10 min.
Recovery for 4: restart squeezelite-general unit. Separate 10 min cooldown.
"""
import subprocess
import time
import json
import urllib.request

GENERAL = "0d:b3:77:92:1f:4c"
LMS = "http://localhost:9000/jsonrpc.js"
LOG = "/var/log/squeezeboxserver/server.log"
CYCLE_S = 60
COOLDOWN_S = 600
FLOOD_PATTERN = "Address already in use"
XDG_ENV = {"XDG_RUNTIME_DIR": "/run/user/1000", "HOME": "/home/pi",
            "USER": "pi", "PATH": "/usr/bin:/bin:/sbin"}


def log(msg):
    print(msg, flush=True)


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
    incarnation of the given squeezelite unit.

    v3.1: lines from before the unit's last start are excluded - after a real
    recovery the plain 20-line window still contained pre-restart error lines,
    which fired 1-2 unnecessary follow-up restarts (observed 2026-07-06
    14:36/14:46).
    v3.2: parameterized - announce shares the dmix and the same reopen failure
    mode; it was previously unwatched (only unit-active was checked, and a
    stuck client stays active while erroring)."""
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


def main():
    log("lms-health watchdog v3.2 started (cycle=%ss)" % CYCLE_S)
    time.sleep(60)  # boot grace
    last_recovery = 0.0
    last_sq_recovery = {}
    while True:
        try:
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

            for u in ("squeezelite-general", "squeezelite-announce"):
                if not unit_active(u):
                    log("WARNING: %s not active (systemd should restart it)"
                        % u)
        except Exception as exc:
            log("watchdog cycle error: %s" % exc)
        time.sleep(CYCLE_S)


if __name__ == "__main__":
    main()
