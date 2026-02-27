#!/usr/bin/env python3
import json
import logging
import smtplib
import ssl
import subprocess
import threading
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import psutil
import requests
from requests import RequestException

from config import credentials
from config import configuration
from logger_utils import get_service_logger

LOGGER_DNS = get_service_logger("dns")
LOGGER_SYS = get_service_logger("sys")
LOGGER_EMAIL = get_service_logger("email")
LOGGER_DISKS = get_service_logger("disks")
LOGGER_MAIN = get_service_logger("main")


def send_email(subject: str, content: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = configuration.SENDER_EMAIL
    msg["To"] = configuration.RECEIVER_EMAIL
    msg.set_content(content)

    LOGGER_EMAIL.info(f"Trying to send report email: {subject}")

    try:
        context = ssl.create_default_context()

        with smtplib.SMTP_SSL(configuration.SMTP_SERVER, configuration.SMTP_PORT, context=context, timeout=30) as server:
            LOGGER_EMAIL.info("Connection established")
            server.login(credentials.EMAIL_USERNAME, credentials.EMAIL_PASSWORD)
            LOGGER_EMAIL.info("Logged in successfully")
            server.send_message(msg)
            LOGGER_EMAIL.info("Message sent successfully")
    except Exception as e:
        LOGGER_EMAIL.error(f"Error: {e}")

def get_report(day: datetime):
    date = day.strftime(configuration.LOG_SUFFIX_FORMAT)
    report_lines = []
    services_logged = []
    for service_dir in configuration.BASE_LOG_DIR.iterdir():
        if not service_dir.is_dir():
            continue
        service_name = service_dir.name
        log_file = service_dir / f"service.log.{date}"
        if log_file.exists():
            services_logged.append(service_name)
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    for level in configuration.DAILY_REPORT_LEVELS:
                        if f"[{level}]" in line:
                            report_lines.append(f"[{service_name.upper()}] {line.strip()}")
                            break

    if not services_logged:
        return f"No log files found for {date}."

    if not report_lines:
        return f"All systems nominal for {date}. No issues detected. Read log files for services: {services_logged}. Reporting log levels: {configuration.DAILY_REPORT_LEVELS}"

    return f"Report for {date}, including services {services_logged} and log levels {configuration.DAILY_REPORT_LEVELS} \n\n\n" + "\n".join(report_lines)


def log_critical_with_email(logger: logging.Logger, message: str, alternate_email_message: str = ""):
    logger.critical(message)

    subject = f"CRITICAL ERROR {datetime.now().strftime(configuration.HUMAN_READABLE_DATETIME_FORMAT)}"

    email_message = alternate_email_message if alternate_email_message != "" else message

    send_email(subject, email_message)


def send_daily_report(day: datetime):
    report = get_report(day)
    date = day.strftime("%d.%m.%Y")

    subject = f"Raspberry pi report for {date}"

    send_email(subject, report)


def austrian_time() -> datetime:
    return datetime.now(ZoneInfo("Europe/Vienna"))


def get_ip() -> str:
    """Gets public IP. Throws exception on failure."""
    urls = ["https://ifconfig.me", "https://api.ipify.org"]
    for url in urls:
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.text.strip()
        except RequestException as e:
            LOGGER_DNS.warning(f"Failed to get IP from {url}: {e}")
    raise requests.ConnectionError("Could not retrieve public IP from any provider.")

def read_ip_state() -> tuple[str, datetime]:
    """Reads state file. Returns (ip, timestamp). Handles missing file."""
    if not configuration.IP_STATE_FILE.exists():
        return "", datetime.min.replace(tzinfo=ZoneInfo("Europe/Vienna"))

    try:
        with open(configuration.IP_STATE_FILE, "r") as f:
            state = json.load(f)
        return state["ip"], datetime.fromisoformat(state["ts"])
    except (json.JSONDecodeError, KeyError):
        LOGGER_DNS.warning("State file corrupted. Resetting.")
        return "", datetime.min.replace(tzinfo=ZoneInfo("Europe/Vienna"))

def write_ip_state(ip: str) -> None:
    """Saves the current IP and timestamp."""
    state = {
        "ip": ip,
        "ts": austrian_time().isoformat()
    }
    with open(configuration.IP_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def update_dns_record(ip: str) -> bool:
    url = f"https://api.cloudflare.com/client/v4/zones/{configuration.CLOUDFLARE_ZONE_ID}/dns_records/{configuration.CLOUDFLARE_RECORD_ID}"

    payload = {
        "name": configuration.CLOUDFLARE_RECORD_NAME,
        "ttl": 1,
        "type": "A",
        "content": ip,
        "proxied": True
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credentials.CLOUDFLARE_API_TOKEN}"
    }

    try:
        response = requests.put(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("success", False):
            return True
        else:
            LOGGER_DNS.error(f"Cloudflare API returned failure: {data}")
            return False

    except RequestException as e:
        LOGGER_DNS.error(f"Network error updating DNS: {e}")
        return False

def monitor_dns_record():
    LOGGER_DNS.info("Starting DNS record check.")

    try:
        current_ip = get_ip()
        LOGGER_DNS.info(f"Current WAN IP: {current_ip}")
    except Exception as e:
        LOGGER_DNS.error(f"Failed to determine IP. Aborting. Error: {e}")
        return

    old_ip, last_ts = read_ip_state()


    time_diff = austrian_time() - last_ts

    should_refresh = False
    critical_refresh = False

    if current_ip == old_ip:
        LOGGER_DNS.info("IP has not changed.")

        if time_diff > timedelta(seconds=configuration.DNS_FORCE_REFRESH_INTERVAL):
            LOGGER_DNS.info(f"Force refresh triggered (Last update: {time_diff}).")
            should_refresh = True
        else:
            LOGGER_DNS.info(f"Nothing to do, exiting now (Last update: {time_diff}).")

    else:
        LOGGER_DNS.info(f"IP changed from {old_ip} to {current_ip}.")
        should_refresh = True
        critical_refresh = True

    if should_refresh:
        success = update_dns_record(current_ip)

        if success:
            LOGGER_DNS.info("DNS record successfully updated. Exiting now.")
            write_ip_state(current_ip)

        elif critical_refresh:
            LOGGER_DNS.error("Failed to update DNS record to new IP! Retrying...")
            for i in range(1,4):
                time.sleep(30)
                if update_dns_record(current_ip):
                    LOGGER_DNS.info(f"Retry #{i} successful. Exiting now.")
                    write_ip_state(current_ip)
                    return
                LOGGER_DNS.error(f"Retry #{i} failed.")
            log_critical_with_email(LOGGER_DNS, "All retries failed. Service is now unreachable. Immediate action must be taken. Exiting now.",
                                    alternate_email_message= "Failed to update Cloudflare DNS record to new IP Address multiple times.\n"
                                                             "If everything still works, a later attempt was successful.\n"
                                                             f"If not, manually edit the Cloudflare DNS record. Current IP is {current_ip}")
        else:
            LOGGER_DNS.warning("Failed to refresh DNS record, but IP did not change. Should not be a problem for now. Exiting now.")

def get_ram_usage() -> float:
    return psutil.virtual_memory().percent

def get_cpu_usage() -> float:
    return psutil.cpu_percent(interval=0.1)

def get_cpu_temp() -> float | None:
    temps = psutil.sensors_temperatures(fahrenheit=False)
    if not temps:
        return None
    for name in ["cpu_thermal", "soc_thermal", "bcm2835_thermal"]:
        if name in temps:
            return temps[name][0].current
    return None

def get_hardware_status() -> dict[str, bool] | None:
    try:
        raw = subprocess.check_output(["vcgencmd", "get_throttled"], text=True)
        bitmask = int(raw.split('=')[1].strip(), 16)

        # Current States
        undervolt_now = bool(bitmask & 0x1)
        freq_cap_now = bool(bitmask & 0x2)
        throttle_now = bool(bitmask & 0x4)
        soft_temp_now = bool(bitmask & 0x8)

        # Historical States (Happened since boot)
        undervolt_past = bool(bitmask & 0x10000)
        throttle_past = bool(bitmask & 0x40000)

        return {
            "undervolt": undervolt_now,
            "throttled": throttle_now,
            "capped": freq_cap_now,
            "soft_limit": soft_temp_now,
            "had_undervolt": undervolt_past,
            "had_throttle": throttle_past
        }
    except:
        return None

def get_current_clock_speed() -> int:
    try:
        res = subprocess.check_output(["vcgencmd", "measure_clock", "arm"], text=True)
        hz = int(res.split('=')[1].strip())
        return hz // 1_000_000  # Convert to MHz
    except:
        return 0

def monitor_sys(log_heartbeat: bool = False):
    ram_usage = get_ram_usage()
    cpu_usage = get_cpu_usage()
    cpu_temp = get_cpu_temp()

    cpu_freq = get_current_clock_speed()

    status = get_hardware_status()

    msg = f"CPU: {cpu_usage:.1f}% @ {cpu_freq}MHz | RAM: {ram_usage:.1f}% | Temp: {cpu_temp:.1f}°C"

    if not status:
        LOGGER_SYS.error(f"Failed to get hardware status. {msg}")
        return

        # 1. Immediate hardware risk
    if status["undervolt"]:
        LOGGER_SYS.critical(f"POWER CRITICAL: Under-voltage detected! {msg}")
        return

        # 2. Throttling and Limits
    if status["throttled"]:
        LOGGER_SYS.warning(f"THERMAL THROTTLE: CPU speed is being forced down! {msg}")
    elif status["capped"]:
        LOGGER_SYS.warning(f"PERFORMANCE CAPPED: ARM frequency limited by firmware. {msg}")
    elif status["soft_limit"]:
        LOGGER_SYS.warning(f"SOFT LIMIT REACHED: Temperature > 60°C, slight throttling active. {msg}")

        # 3. Standard Thresholds
    if ram_usage > configuration.RAM_USAGE_THRESHOLD or cpu_usage > configuration.CPU_USAGE_THRESHOLD or cpu_temp > configuration.CPU_TEMP_THRESHOLD:
        LOGGER_SYS.warning(f"RESOURCE ALERT: Threshold exceeded. {msg}")

        # 4. Heartbeat
    if log_heartbeat:
        LOGGER_SYS.info(f"Heartbeat: {msg}")


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
            LOGGER_DISKS.warning(f"DISK FULL: {drive['name']} is {usage['percent']}% full ({usage['free_gb']}GB left)")
        else:
            LOGGER_DISKS.info(f"{drive['name']} Usage: {usage['percent']}% ({usage['free_gb']}GB free)")
        if drive["type"] == "smart":
            health = get_smart_health(drive["device"])
            if health == "PASSED":
                LOGGER_DISKS.info(f"DRIVE {drive["name"]} passed the SMART test")
            elif health == "FAILED":
                LOGGER_DISKS.critical(f"DRIVE FAILURE IMMINENT: {drive['name']} ({drive['device']}) FAILED SMART CHECK!")
            elif health == "ERROR":
                LOGGER_DISKS.error(f"SMART ERROR: Could not communicate with {drive['device']}. Check USB cable.")
            elif health == "TIMEOUT":
                LOGGER_DISKS.error(f"SMART check timed out for {drive['device']}")
            elif health == "UNKNOWN":
                LOGGER_DISKS.error(f"UNKNOWN SMART STATUS: smartctl returned unknown status for {drive["device"]}")
        elif drive["type"] == "sd":
            health = get_sd_health(drive["write_test_file"])
            if health == "PASSED":
                LOGGER_DISKS.info(f"SD card {drive["name"]} passed the write test")
            elif health == "FAILED":
                log_critical_with_email(LOGGER_DISKS,f"SD card {drive["name"]} did not pass the write test. It is now in READ-ONLY mode!",
                                        alternate_email_message=f"SD card {drive["name"]} failed the write test, because it is in READ-ONLY mode!.\n"
                                                                f"Immediate backup and replacement required.")
            elif health == "ERROR":
                log_critical_with_email(LOGGER_DISKS,f"UNKNOWN ERROR while performing write test on {drive["name"]}",
                                        alternate_email_message=f"SD card {drive["name"]} failed the write test with an unknown error.\n"
                                                                f"It may be in READ-ONLY mode! Immediate replacement required.")




def monitor_loop():
    LOGGER_MAIN.info("Main monitor loop started")

    last_dns_check = 0
    last_sys_check = 0
    last_sys_heartbeat = 0
    last_disks_check = 0

    last_report = ""

    while True:
        now = time.time()
        local_time = austrian_time()
        local_day = local_time.strftime("%Y-%m-%d")

        if now - last_dns_check > configuration.DNS_CHECK_INTERVAL:
            threading.Thread(target=monitor_dns_record, name="dns").start()
            last_dns_check = now

        if now - last_sys_check > configuration.SYS_CHECK_INTERVAL:
            should_heartbeat = (now - last_sys_heartbeat) > configuration.SYS_HEARTBEAT_INTERVAL
            threading.Thread(target=monitor_sys, name="sys", args=(should_heartbeat,)).start()
            last_sys_check = now
            if should_heartbeat:
                last_sys_heartbeat = now

        if now - last_disks_check > configuration.DISK_CHECK_INTERVAL:
            threading.Thread(target=monitor_disks, name="disks").start()
            last_disks_check = now

        if local_time.hour == 1 and local_day != last_report:
            threading.Thread(target=send_daily_report, name="email-reporter", args=(local_time - timedelta(days=1),)).start()
            last_report = local_day


        time.sleep(configuration.MAIN_LOOP_INTERVAL)


if __name__=="__main__":
    monitor_loop()