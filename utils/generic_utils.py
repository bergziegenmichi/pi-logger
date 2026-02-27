from datetime import datetime
from zoneinfo import ZoneInfo

from config import configuration


def get_local_time() -> datetime:
    return datetime.now(ZoneInfo(configuration.LOCAL_TIMEZONE))
