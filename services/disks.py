import json
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


def get_smart_health(device: str) -> dict:
    """
    Returns {"status": "PASSED"|"FAILED"|"UNKNOWN"|"TIMEOUT"|"ERROR"|"DEVICE_OPEN_FAILED",
             "warnings": [str, ...]}

    Uses -j (JSON) output instead of -H text matching: ATA and SCSI/SAS report
    health completely differently in plaintext ("PASSED"/"FAILED" vs "SMART
    Health Status: OK"), so the old text-matching version silently returned
    UNKNOWN for every healthy SAS drive.
    """
    try:
        res = subprocess.run(
            ["sudo", "smartctl", "-a", "-j", device],
            capture_output=True, text=True, timeout=15
        )
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "warnings": []}
    except Exception:
        return {"status": "ERROR", "warnings": []}

    if not res.stdout.strip():
        return {"status": "ERROR", "warnings": []}

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return {"status": "ERROR", "warnings": []}

    if bool(res.returncode & 0b10):  # bit 1: device open failed
        return {"status": "DEVICE_OPEN_FAILED", "warnings": []}

    status_block = data.get("smart_status", {})
    if "passed" not in status_block:
        return {"status": "UNKNOWN", "warnings": []}

    result = {"status": "PASSED" if status_block["passed"] else "FAILED", "warnings": []}

    device_type = data.get("device", {}).get("type")
    temp = data.get("temperature", {}).get("current")
    if temp is not None and temp >= 55:
        result["warnings"].append(f"high temperature: {temp}C")

    if device_type == "ata":
        attrs = {a["id"]: a for a in data.get("ata_smart_attributes", {}).get("table", [])}
        for attr_id, name in {5: "Reallocated_Sector_Ct", 197: "Current_Pending_Sector",
                               198: "Offline_Uncorrectable", 187: "Reported_Uncorrect"}.items():
            a = attrs.get(attr_id)
            if a and a.get("raw", {}).get("value", 0) > 0:
                result["warnings"].append(f"{name}: {a['raw']['value']}")

    elif device_type == "scsi":
        defects = data.get("scsi_grown_defect_list", 0)
        if defects:
            result["warnings"].append(f"grown_defect_list: {defects}")
        log = data.get("scsi_error_counter_log", {})
        for op in ("read", "write", "verify"):
            errs = log.get(op, {}).get("total_uncorrected_errors", 0)
            if errs:
                result["warnings"].append(f"{op}_uncorrected_errors: {errs}")

    return result


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
        if usage is None:
            loggers.DISKS.error(f"Could not read disk usage for {drive['name']} ({drive['mount']}) -- not mounted?")
        elif usage["percent"] > configuration.DISK_THRESHOLD:
            loggers.DISKS.warning(f"DISK FULL: {drive['name']} is {usage['percent']}% full ({usage['free_gb']}GB left)")
        else:
            loggers.DISKS.info(f"{drive['name']} usage: {usage['percent']}% ({usage['free_gb']}GB free)")

        if drive["type"] == "smart":
            name, dev = drive["name"], drive["device"]
            health = get_smart_health(dev)
            status = health["status"]

            if status == "PASSED":
                loggers.DISKS.info(f"DRIVE {name} passed the SMART test")
            elif status == "FAILED":
                log_critical_with_email(
                    loggers.DISKS,
                    f"DRIVE FAILURE IMMINENT: {name} ({dev}) FAILED SMART CHECK!",
                    alternate_email_message=f"Drive {name} ({dev}) failed its SMART health check.\n"
                                             f"Back up its data immediately and prepare to replace it."
                )
            elif status == "DEVICE_OPEN_FAILED":
                loggers.DISKS.error(f"SMART ERROR: Could not open {dev} for {name}. Check cabling/HBA.")
            elif status == "ERROR":
                loggers.DISKS.error(f"SMART ERROR: Could not communicate with {dev} ({name}).")
            elif status == "TIMEOUT":
                loggers.DISKS.error(f"SMART check timed out for {dev} ({name})")
            elif status == "UNKNOWN":
                loggers.DISKS.error(f"UNKNOWN SMART STATUS: smartctl returned no usable status for {dev} ({name})")

            for warning in health["warnings"]:
                loggers.DISKS.warning(f"SMART WARNING ({name}/{dev}): {warning}")

        elif drive["type"] == "sd":
            name = drive["name"]
            health = get_sd_health(drive["write_test_file"])
            if health == "PASSED":
                loggers.DISKS.info(f"SD card {name} passed the write test")
            elif health == "FAILED":
                log_critical_with_email(
                    loggers.DISKS,
                    f"SD card {name} did not pass the write test. It is now in READ-ONLY mode!",
                    alternate_email_message=f"SD card {name} failed the write test, because it is in READ-ONLY mode!.\n"
                                             f"Immediate backup and replacement required."
                )
            elif health == "ERROR":
                log_critical_with_email(
                    loggers.DISKS,
                    f"UNKNOWN ERROR while performing write test on {name}",
                    alternate_email_message=f"SD card {name} failed the write test with an unknown error.\n"
                                             f"It may be in READ-ONLY mode! Immediate replacement required."
                )