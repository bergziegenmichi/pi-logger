import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from requests import RequestException

import loggers
from config import configuration, credentials
from utils.generic_utils import get_local_time
from utils.email_utils import log_critical_with_email


def get_ip() -> str:
    """Gets public IP. Throws exception on failure."""
    urls = ["https://ifconfig.me", "https://api.ipify.org"]
    for url in urls:
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.text.strip()
        except RequestException as e:
            loggers.DNS.warning(f"Failed to get IP from {url}: {e}")
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
        loggers.DNS.warning("State file corrupted. Resetting.")
        return "", datetime.min.replace(tzinfo=ZoneInfo("Europe/Vienna"))


def write_ip_state(ip: str) -> None:
    """Saves the current IP and timestamp."""
    state = {
        "ip": ip,
        "ts": get_local_time().isoformat()
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
            loggers.DNS.error(f"Cloudflare API returned failure: {data}")
            return False

    except RequestException as e:
        loggers.DNS.error(f"Network error updating DNS: {e}")
        return False


def monitor_dns_record():
    loggers.DNS.info("Starting DNS record check.")

    try:
        current_ip = get_ip()
        loggers.DNS.info(f"Current WAN IP: {current_ip}")
    except Exception as e:
        loggers.DNS.error(f"Failed to determine IP. Aborting. Error: {e}")
        return

    old_ip, last_ts = read_ip_state()


    time_diff = get_local_time() - last_ts

    should_refresh = False
    critical_refresh = False

    if current_ip == old_ip:
        loggers.DNS.info("IP has not changed.")

        if time_diff > timedelta(seconds=configuration.DNS_FORCE_REFRESH_INTERVAL):
            loggers.DNS.info(f"Force refresh triggered (Last update: {time_diff}).")
            should_refresh = True
        else:
            loggers.DNS.info(f"Nothing to do, exiting now (Last update: {time_diff}).")

    else:
        loggers.DNS.info(f"IP changed from {old_ip} to {current_ip}.")
        should_refresh = True
        critical_refresh = True

    if should_refresh:
        success = update_dns_record(current_ip)

        if success:
            loggers.DNS.info("DNS record successfully updated. Exiting now.")
            write_ip_state(current_ip)

        elif critical_refresh:
            loggers.DNS.error("Failed to update DNS record to new IP! Retrying...")
            for i in range(1,4):
                time.sleep(30)
                if update_dns_record(current_ip):
                    loggers.DNS.info(f"Retry #{i} successful. Exiting now.")
                    write_ip_state(current_ip)
                    return
                loggers.DNS.error(f"Retry #{i} failed.")
            log_critical_with_email(loggers.DNS, "All retries failed. Service is now unreachable. Immediate action must be taken. Exiting now.",
                                    alternate_email_message= "Failed to update Cloudflare DNS record to new IP Address multiple times.\n"
                                                             "If everything still works, a later attempt was successful.\n"
                                                             f"If not, manually edit the Cloudflare DNS record. Current IP is {current_ip}")
        else:
            loggers.DNS.warning("Failed to refresh DNS record, but IP did not change. Should not be a problem for now. Exiting now.")
