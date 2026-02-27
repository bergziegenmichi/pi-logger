#!/usr/bin/env python3
import threading
import time
from datetime import datetime, timedelta

import loggers
from config import configuration
from utils import generic_utils
from utils.generic_utils import get_local_time, ping_healthchecks_io
from services.disks import monitor_disks
from services.dns import monitor_dns_record
from utils.email_utils import send_email, log_critical_with_email
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
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        for level in configuration.DAILY_REPORT_LEVELS:
                            if f"[{level}]" in line:
                                report_lines.append(f"[{service_name.upper()}] {line.strip()}")
                                break
            except PermissionError:
                report_lines.append("")
                report_lines.append(f"Permission Error while trying to read {log_file}")
                report_lines.append("")

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
    def run_thread(name, target, args=()):
        if name in running_threads and running_threads[name].is_alive():
            loggers.MAIN.warning(f"Skipping {name} check: Previous thread still running.")
            return
        t = threading.Thread(target=target, name=name, args=args)
        running_threads[name] = t
        t.start()


    if not configuration.BASE_LOG_DIR.exists():
        loggers.MAIN.warning(f"Log directory {configuration.BASE_LOG_DIR} does not exist, trying to create it.")
        try:
            configuration.BASE_LOG_DIR.mkdir(parents=True)
            loggers.MAIN.info(f"Log directory {configuration.BASE_LOG_DIR} created successfully")
        except Exception as e:
            log_critical_with_email(loggers.MAIN, f"Unable to create log directory {configuration.BASE_LOG_DIR}: {e}")
            time.sleep(60*60) # sleep 1 hour
            return

    loggers.MAIN.info("Main monitor loop started")

    try:
        send_email("pi-logger started", f"System booted. Time: {get_local_time()}")
    except Exception as e:
        loggers.MAIN.error(f"Failed to send startup email: {e}")

    last_dns_check = 0
    last_sys_check = 0
    last_sys_heartbeat = 0
    last_disks_check = 0
    last_healtcheck_ping = 0

    last_report = ""

    running_threads : dict[str, threading.Thread] = {}

    while True:
        now = time.time()
        local_time = get_local_time()
        local_day = local_time.strftime("%Y-%m-%d")

        if now - last_dns_check > configuration.DNS_CHECK_INTERVAL >= 0:
            loggers.MAIN.info("Running task dns")
            run_thread(target=monitor_dns_record, name="dns")
            last_dns_check = now

        if now - last_sys_check > configuration.SYS_CHECK_INTERVAL >= 0:
            should_heartbeat = (now - last_sys_heartbeat) > configuration.SYS_HEARTBEAT_INTERVAL
            loggers.MAIN.info(f"Running task sys. heartbeat = {should_heartbeat}")
            run_thread(target=monitor_sys, name="sys", args=(should_heartbeat,))
            last_sys_check = now
            if should_heartbeat:
                last_sys_heartbeat = now

        if now - last_disks_check > configuration.DISK_CHECK_INTERVAL >= 0:
            loggers.MAIN.info("running task disks")
            run_thread(target=monitor_disks, name="disks")
            last_disks_check = now

        if local_time.hour == 1 and local_day != last_report:
            loggers.MAIN.info("running task email-reporter")
            run_thread(target=send_daily_report, name="email-reporter", args=(local_time - timedelta(days=1),))
            last_report = local_day

        if now - last_healtcheck_ping > configuration.HEALTHCHECK_PING_INTERVAL >= 0:
            loggers.MAIN.info("running task ping-healthcheck")
            run_thread(target=ping_healthchecks_io, name="ping-healthcheck")
            last_healtcheck_ping = now

        time.sleep(configuration.MAIN_LOOP_INTERVAL)


if __name__=="__main__":
    monitor_loop()