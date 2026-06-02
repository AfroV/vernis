#!/usr/bin/env python3
"""
Vernis Thermal Monitor Daemon
Logs CPU temperature and throttling status every 5 minutes.
Keeps 24 hours of history.
"""

import subprocess
import json
import time
from pathlib import Path

THERMAL_LOG_FILE = Path("/opt/vernis/thermal-log.json")
LOG_INTERVAL = 300  # 5 minutes


def get_thermal_status():
    """Get current CPU temperature and throttling status"""
    result = {
        "temperature": None,
        "throttled": False,
        "throttle_flags": [],
        "under_voltage": False,
        "frequency_capped": False,
        "timestamp": time.time()
    }

    # Get CPU temperature
    try:
        temp_result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=5
        )
        if temp_result.returncode == 0:
            temp_str = temp_result.stdout.strip()
            temp = float(temp_str.replace("temp=", "").replace("'C", ""))
            result["temperature"] = temp
    except:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp = int(f.read().strip()) / 1000.0
                result["temperature"] = temp
        except:
            pass

    # Get throttling status
    try:
        throttle_result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True, text=True, timeout=5
        )
        if throttle_result.returncode == 0:
            throttle_str = throttle_result.stdout.strip()
            throttle_hex = throttle_str.replace("throttled=", "")
            throttle_val = int(throttle_hex, 16)

            flags = []
            if throttle_val & 0x1:
                flags.append("Under-voltage detected")
                result["under_voltage"] = True
            if throttle_val & 0x2:
                flags.append("Frequency capped")
                result["frequency_capped"] = True
            if throttle_val & 0x4:
                flags.append("Currently throttled")
                result["throttled"] = True
            if throttle_val & 0x8:
                flags.append("Soft temp limit")
            if throttle_val & 0x10000:
                flags.append("Under-voltage occurred")
            if throttle_val & 0x20000:
                flags.append("Freq cap occurred")
            if throttle_val & 0x40000:
                flags.append("Throttling occurred")
            if throttle_val & 0x80000:
                flags.append("Soft temp limit occurred")

            result["throttle_flags"] = flags
            result["throttle_raw"] = throttle_hex
    except:
        pass

    return result


def log_reading():
    """Log current thermal reading to file"""
    try:
        # Load existing log
        if THERMAL_LOG_FILE.exists():
            with open(THERMAL_LOG_FILE, 'r') as f:
                log_data = json.load(f)
        else:
            log_data = {"readings": []}

        # Add new reading
        reading = get_thermal_status()
        log_data["readings"].append(reading)

        # Keep only last 24 hours
        cutoff = time.time() - (24 * 60 * 60)
        log_data["readings"] = [r for r in log_data["readings"] if r.get("timestamp", 0) > cutoff]

        # Save
        with open(THERMAL_LOG_FILE, 'w') as f:
            json.dump(log_data, f)

        # Log to console
        temp = reading.get("temperature", "N/A")
        throttled = "YES" if reading.get("throttled") else "no"
        print(f"[{time.strftime('%H:%M:%S')}] Temp: {temp}°C | Throttled: {throttled}")

    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Error: {e}")


def main():
    print("Vernis Thermal Monitor started")
    print(f"Logging every {LOG_INTERVAL // 60} minutes to {THERMAL_LOG_FILE}")

    while True:
        log_reading()
        time.sleep(LOG_INTERVAL)


if __name__ == "__main__":
    main()
