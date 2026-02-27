#!/usr/bin/env python3
import threading
import time
from datetime import datetime, timedelta

import loggers
from config import configuration
from utils.generic_utils import get_local_time
from services.disks import monitor_disks
from services.dns import monitor_dns_record
from utils.email_utils import send_email
from services.sys import monitor_sys


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


def send_daily_report(day: datetime):
    report = get_report(day)
    date = day.strftime("%d.%m.%Y")

    subject = f"Raspberry pi report for {date}"

    send_email(subject, report)


def monitor_loop():
    loggers.MAIN.info("Main monitor loop started")

    last_dns_check = 0
    last_sys_check = 0
    last_sys_heartbeat = 0
    last_disks_check = 0

    last_report = ""

    while True:
        now = time.time()
        local_time = get_local_time()
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