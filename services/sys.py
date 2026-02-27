import subprocess

import psutil

import loggers
from config import configuration


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
        loggers.SYS.error(f"Failed to get hardware status. {msg}")
        return

        # 1. Immediate hardware risk
    if status["undervolt"]:
        loggers.SYS.critical(f"POWER CRITICAL: Under-voltage detected! {msg}")
        return

        # 2. Throttling and Limits
    if status["throttled"]:
        loggers.SYS.warning(f"THERMAL THROTTLE: CPU speed is being forced down! {msg}")
    elif status["capped"]:
        loggers.SYS.warning(f"PERFORMANCE CAPPED: ARM frequency limited by firmware. {msg}")
    elif status["soft_limit"]:
        loggers.SYS.warning(f"SOFT LIMIT REACHED: Temperature > 60°C, slight throttling active. {msg}")

        # 3. Standard Thresholds
    if ram_usage > configuration.RAM_USAGE_THRESHOLD or cpu_usage > configuration.CPU_USAGE_THRESHOLD or cpu_temp > configuration.CPU_TEMP_THRESHOLD:
        loggers.SYS.warning(f"RESOURCE ALERT: Threshold exceeded. {msg}")

        # 4. Heartbeat
    if log_heartbeat:
        loggers.SYS.info(f"Heartbeat: {msg}")
