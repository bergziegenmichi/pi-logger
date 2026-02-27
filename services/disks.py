import subprocess
from pathlib import Path

import psutil

import loggers
from config import configuration
from utils.email_utils import log_critical_with_email


def get_disk_usage(path: str) -> dict[str, float] | None:
    try:
        usage = psutil.disk_usage(path)
        return {
            "percent": usage.percent,
            "free_gb": usage.free // (2**30),
            "total_gb": usage.total // (2**30)
        }
    except Exception:
        return None


def get_smart_health(device: str) -> str:
    """Returns 'PASSED', 'FAILED', 'UNKNOWN', 'TIMEOUT' or 'ERROR'"""
    try:
        res = subprocess.run(
            ["sudo", "smartctl", "-H", device],
            capture_output=True, text=True, timeout=10
        )
        if "PASSED" in res.stdout:
            return "PASSED"
        elif "FAILED" in res.stdout:
            return "FAILED"
        else:
            return "UNKNOWN"

    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except:
        return "ERROR"


def get_sd_health(test_file_path) -> str:
    """Checks if the SD card has locked itself into Read-Only mode."""
    test_file = Path(test_file_path)
    try:
        # Attempt to write and delete a temporary file
        test_file.touch(exist_ok=True)
        test_file.unlink()
        return "PASSED"
    except OSError as e:
        # Errno 30 is 'Read-only file system'
        if e.errno == 30:
            return "FAILED"
        return "ERROR"


def monitor_disks():
    for drive in configuration.EXTERNAL_DRIVES:
        usage = get_disk_usage(drive["mount"])
        if usage["percent"] > configuration.DISK_THRESHOLD:
            loggers.DISKS.warning(f"DISK FULL: {drive['name']} is {usage['percent']}% full ({usage['free_gb']}GB left)")
        else:
            loggers.DISKS.info(f"{drive['name']} Usage: {usage['percent']}% ({usage['free_gb']}GB free)")
        if drive["type"] == "smart":
            health = get_smart_health(drive["device"])
            if health == "PASSED":
                loggers.DISKS.info(f"DRIVE {drive["name"]} passed the SMART test")
            elif health == "FAILED":
                loggers.DISKS.critical(f"DRIVE FAILURE IMMINENT: {drive['name']} ({drive['device']}) FAILED SMART CHECK!")
            elif health == "ERROR":
                loggers.DISKS.error(f"SMART ERROR: Could not communicate with {drive['device']}. Check USB cable.")
            elif health == "TIMEOUT":
                loggers.DISKS.error(f"SMART check timed out for {drive['device']}")
            elif health == "UNKNOWN":
                loggers.DISKS.error(f"UNKNOWN SMART STATUS: smartctl returned unknown status for {drive["device"]}")
        elif drive["type"] == "sd":
            health = get_sd_health(drive["write_test_file"])
            if health == "PASSED":
                loggers.DISKS.info(f"SD card {drive["name"]} passed the write test")
            elif health == "FAILED":
                log_critical_with_email(loggers.DISKS,f"SD card {drive["name"]} did not pass the write test. It is now in READ-ONLY mode!",
                                        alternate_email_message=f"SD card {drive["name"]} failed the write test, because it is in READ-ONLY mode!.\n"
                                                                f"Immediate backup and replacement required.")
            elif health == "ERROR":
                log_critical_with_email(loggers.DISKS,f"UNKNOWN ERROR while performing write test on {drive["name"]}",
                                        alternate_email_message=f"SD card {drive["name"]} failed the write test with an unknown error.\n"
                                                                f"It may be in READ-ONLY mode! Immediate replacement required.")
