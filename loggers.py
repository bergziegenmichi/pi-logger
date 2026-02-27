from utils.logger_utils import get_service_logger

DNS = get_service_logger("dns")
SYS = get_service_logger("sys")
EMAIL = get_service_logger("email")
DISKS = get_service_logger("disks")
MAIN = get_service_logger("main")

ALL_LOGGERS = [DNS, SYS, EMAIL, DISKS, MAIN]
