from pathlib import Path


# TIME FORMATS
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_SUFFIX_FORMAT = "%Y-%m-%d"
HUMAN_READABLE_DATETIME_FORMAT = "%d.%m.%Y %H:%M:%S"

# CLOUDFLARE CONFIGS
CLOUDFLARE_ZONE_ID = "8b35a4d96efcd077732d5f265f08921a"
CLOUDFLARE_RECORD_ID = "b595d55f830f08bc5c332355b56f76c4"
CLOUDFLARE_RECORD_NAME = "cloud.hofmannmichael.at"

# EMAIL CONFIGS
SENDER_EMAIL = "pi-logger@hofmannmichael.at"
RECEIVER_EMAIL = "mail@hofmannmichael.at"
SMTP_SERVER = "smtp.mailbox.org"
SMTP_PORT = 465

# REPORT CONFIGS
DAILY_REPORTS = True
DAILY_REPORT_LEVELS = ["WARNING", "ERROR", "CRITICAL"]
URGENT_EMAILS = True

# PATH CONFIGS
HOME_DIR = Path("~").expanduser()
BASE_LOG_DIR = HOME_DIR / "pi-logger.logs"
DNS_LOG_DIR = BASE_LOG_DIR / "ddns.logs"
IP_STATE_FILE = HOME_DIR / ".ip-state.json"

# INTERVALS
MAIN_LOOP_INTERVAL = 10                     # 10 second
DNS_CHECK_INTERVAL = 60*5                   # 5 minutes
DNS_FORCE_REFRESH_INTERVAL = 60 * 60 * 24   # 24 hours
SYS_CHECK_INTERVAL = 10                     # 10 seconds
SYS_HEARTBEAT_INTERVAL = 60*60              # 1 hour
DISK_CHECK_INTERVAL = 60*60*24              # 24 hours

# THRESHOLDS
RAM_USAGE_THRESHOLD = 80    # %
CPU_USAGE_THRESHOLD = 80    # %
CPU_TEMP_THRESHOLD = 75     # °C
DISK_THRESHOLD = 80         # %

# DRIVE CONFIG
EXTERNAL_DRIVES = [
    {"name": "Nextcloud data",
     "device": "/dev/disk/by-label/nextcloud-data",
     "mount": "/mnt/nextcloud-data",
     "type": "smart"},

    {"name": "Nextcloud backup",
     "device": "/dev/disk/by-label/nextcloud-backup",
     "mount": "/mnt/nextcloud-backup",
     "type": "smart"},

    {"name": "System SD card",
     "device": "unused here",
     "mount": "/",
     "type": "sd"}
]
