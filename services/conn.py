import random
import subprocess
import time

import requests

import loggers
from config import configuration

# waste bandwidth of your enemies
_PROBE_URLS = [
    "https://www.google.com",
    "https://www.apple.com",
    "https://one.one.one.one",
    "https://www.amazon.com",
]

_TIMEOUT = 10  # seconds per request


def _probe_once() -> bool:
    """Return True if any of the randomly chosen URLs responds successfully."""
    url = random.choice(_PROBE_URLS)
    try:
        resp = requests.get(url, timeout=_TIMEOUT, allow_redirects=True)
        loggers.CONN.debug(f"Connectivity probe OK: {url} → {resp.status_code}")
        return True
    except Exception as e:
        loggers.CONN.warning(f"Connectivity probe FAILED: {url} → {e}")
        return False


def _reboot():
    loggers.CONN.critical(
        f"No connectivity for {configuration.CONNECTIVITY_REBOOT_AFTER // 60} consecutive "
        "minutes. Requesting graceful shutdown."
    )
    result = subprocess.run(["sudo", "/usr/bin/systemctl", "reboot"], capture_output=True, text=True)
    if result.returncode != 0:
        loggers.CONN.critical(
            f"Shutdown command failed (rc={result.returncode}): {result.stderr.strip()}"
        )


# ---------------------------------------------------------------------------
# State shared across calls (module-level so the thread can be stateless)
# ---------------------------------------------------------------------------
_first_failure_time: float | None = None  # timestamp of the first consecutive failure


def monitor_connectivity() -> None:
    """
    Called once per minute from the main monitor loop.

    Tracks a rolling window of consecutive failures.  If connectivity has been
    absent for CONNECTIVITY_REBOOT_AFTER seconds straight, reboots the Pi.
    """
    global _first_failure_time

    success = _probe_once()

    if success:
        if _first_failure_time is not None:
            outage_seconds = int(time.time() - _first_failure_time)
            loggers.CONN.info(
                f"Connectivity restored after ~{outage_seconds}s outage."
            )
        _first_failure_time = None
        return

    # --- failure path ---
    now = time.time()
    if _first_failure_time is None:
        _first_failure_time = now
        loggers.CONN.warning("Connectivity lost – starting failure timer.")
        return

    outage_seconds = now - _first_failure_time
    minutes_down = int(outage_seconds // 60)
    loggers.CONN.warning(
        f"Still no connectivity – down for ~{minutes_down} min "
        f"(threshold: {configuration.CONNECTIVITY_REBOOT_AFTER // 60} min)."
    )

    if outage_seconds >= configuration.CONNECTIVITY_REBOOT_AFTER:
        _reboot()