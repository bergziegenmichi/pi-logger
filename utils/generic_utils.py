from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import loggers
from config import configuration, credentials


def get_local_time() -> datetime:
    return datetime.now(ZoneInfo(configuration.LOCAL_TIMEZONE))

def ping_healthchecks_io():
    try:
        requests.get(credentials.HEALTHCHECK_URL, timeout=10)
    except requests.RequestException as e:
        # If this fails repeatedly, Healthchecks.io will notify you via email anyway.
        loggers.MAIN.warning(f"Failed to ping healthchecks.io: {e}")
        return
    loggers.MAIN.info("Successfully pinged healthchecks.io")