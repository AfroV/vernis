#!/usr/bin/env python3
"""
Vernis Performance Benchmark Tool
Tests CPU performance, temperature, and helps optimize for enclosure cooling.

Usage:
  python3 performance_benchmark.py --duration 60 --output benchmark_results.json
  python3 performance_benchmark.py --stress --duration 120
  python3 performance_benchmark.py --quick
"""

import argparse
import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from datetime import datetime

class PerformanceBenchmark:
    """Comprehensive Pi performance benchmark"""

    def __init__(self, output_dir="/opt/vernis"):
        self.output_dir = Path(output_dir)
        self.results_file = self.output_dir / "benchmark-results.json"
        self.running = False
        self.samples = []

    def get_cpu_freq(self):
        """Get current CPU frequency in MHz"""
        try:
            result = subprocess.run(
                ["vcgencmd", "measure_clock", "arm"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # Output: frequency(48)=1800000000
                freq_str = result.stdout.strip().split("=")[1]
                return int(freq_str) // 1000000  # Convert to MHz
        except:
            pass

        # Fallback: read from sysfs
        try:
            with open("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq") as f:
                return int(f.read().strip()) // 1000
        except:
            return 0

    def get_temperature(self):
        """Get CPU temperature in Celsius"""
        try:
            result = subprocess.run(
                ["vcgencmd", "measure_temp"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                # Output: temp=52.0'C
                temp_str = result.stdout.strip()
                temp = float(temp_str.replace("temp=", "").replace("'C", ""))
                return temp
        except:
            pass

        # Fallback
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                return int(f.read().strip()) / 1000
        except:
            return 0

    def get_memory_usage(self):
        """Get memory usage in MB"""
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()

            mem_info = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    value = int(parts[1])
                    mem_info[key] = value

            total = mem_info.get("MemTotal", 0) / 1024
            free = mem_info.get("MemAvailable", mem_info.get("MemFree", 0)) / 1024
            used = total - free

            return {
                "total_mb": round(total, 1),
                "used_mb": round(used, 1),
                "free_mb": round(free, 1),
                "percent": round((used / total) * 100, 1) if total > 0 else 0
            }
        except:
            return {"total_mb": 0, "used_mb": 0, "free_mb": 0, "percent": 0}

    def get_throttle_status(self):
        """Get throttling status"""
        try:
            result = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                throttle_str = result.stdout.strip()
                throttle_hex = throttle_str.replace("throttled=", "")
                throttle_val = int(throttle_hex, 16)

                return {
                    "raw": throttle_hex,
                    "under_voltage": bool(throttle_val & 0x1),
                    "freq_capped": bool(throttle_val & 0x2),
                    "throttled": bool(throttle_val & 0x4),
                    "soft_temp_limit": bool(throttle_val & 0x8),
                    "under_voltage_occurred": bool(throttle_val & 0x10000),
                    "freq_cap_occurred": bool(throttle_val & 0x20000),
                    "throttle_occurred": bool(throttle_val & 0x40000)
                }
        except:
            pass
        return {"raw": "0x0", "throttled": False}

    def get_pi_model(self):
        """Detect Raspberry Pi model"""
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("Model"):
                        model = line.split(":")[1].strip()
                        if "Pi 5" in model:
                            return "Pi 5"
                        elif "Pi 4" in model:
                            return "Pi 4"
                        elif "Pi Zero 2" in model:
                            return "Pi Zero 2W"
                        return model
        except:
            pass
        return "Unknown"

    def get_cpu_profile(self):
        """Get current CPU profile from config.txt"""
        try:
            config_paths = [
                Path("/boot/firmware/config.txt"),
                Path("/boot/config.txt")
            ]
            for config_path in config_paths:
                if config_path.exists():
                    content = config_path.read_text()
                    arm_freq = None
                    for line in content.split("\n"):
                        line = line.strip()
                        if line.startswith("arm_freq="):
                            arm_freq = int(line.split("=")[1])
                    return arm_freq
        except:
            pass
        return None

    def sample_metrics(self):
        """Take a single sample of all metrics"""
        return {
            "timestamp": time.time(),
            "cpu_freq_mhz": self.get_cpu_freq(),
            "temp_c": self.get_temperature(),
            "memory": self.get_memory_usage(),
            "throttle": self.get_throttle_status()
        }

    def cpu_stress_test(self, duration=10, threads=4):
        """Run CPU stress test and monitor"""
        print(f"Running CPU stress test for {duration}s with {threads} threads...")

        # Start stress process
        stress_procs = []
        for _ in range(threads):
            proc = subprocess.Popen(
                ["python3", "-c", "while True: pass"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            stress_procs.append(proc)

        # Sample during stress
        samples = []
        start_time = time.time()
        while time.time() - start_time < duration:
            samples.append(self.sample_metrics())
            time.sleep(1)

        # Stop stress
        for proc in stress_procs:
            proc.terminate()
            proc.wait()

        return samples

    def idle_test(self, duration=10):
        """Monitor metrics at idle"""
        print(f"Running idle monitoring for {duration}s...")

        samples = []
        start_time = time.time()
        while time.time() - start_time < duration:
            samples.append(self.sample_metrics())
            time.sleep(1)

        return samples

    def analyze_samples(self, samples, test_name="test"):
        """Analyze a set of samples"""
        if not samples:
            return {}

        temps = [s["temp_c"] for s in samples if s["temp_c"] > 0]
        freqs = [s["cpu_freq_mhz"] for s in samples if s["cpu_freq_mhz"] > 0]
        throttle_events = sum(1 for s in samples if s["throttle"].get("throttled", False))

        return {
            "test_name": test_name,
            "duration_s": len(samples),
            "samples": len(samples),
            "temperature": {
                "min": round(min(temps), 1) if temps else 0,
                "max": round(max(temps), 1) if temps else 0,
                "avg": round(sum(temps) / len(temps), 1) if temps else 0,
                "delta": round(max(temps) - min(temps), 1) if temps else 0
            },
            "cpu_freq": {
                "min": min(freqs) if freqs else 0,
                "max": max(freqs) if freqs else 0,
                "avg": round(sum(freqs) / len(freqs)) if freqs else 0
            },
            "throttle_events": throttle_events,
            "throttle_percent": round((throttle_events / len(samples)) * 100, 1) if samples else 0
        }

    def run_full_benchmark(self, idle_duration=30, stress_duration=60):
        """Run complete benchmark suite"""
        print("=" * 50)
        print("Vernis Performance Benchmark")
        print("=" * 50)

        results = {
            "timestamp": datetime.now().isoformat(),
            "pi_model": self.get_pi_model(),
            "configured_freq": self.get_cpu_profile(),
            "tests": {}
        }

        # Initial readings
        print("\nInitial state:")
        initial = self.sample_metrics()
        print(f"  Temperature: {initial['temp_c']}°C")
        print(f"  CPU Freq: {initial['cpu_freq_mhz']} MHz")
        print(f"  Memory: {initial['memory']['used_mb']:.0f} MB used")
        results["initial"] = initial

        # Idle test
        print("\n[1/3] Idle Test")
        idle_samples = self.idle_test(idle_duration)
        results["tests"]["idle"] = self.analyze_samples(idle_samples, "Idle")
        print(f"  Avg temp: {results['tests']['idle']['temperature']['avg']}°C")

        # Stress test
        print("\n[2/3] CPU Stress Test")
        stress_samples = self.cpu_stress_test(stress_duration, threads=4)
        results["tests"]["stress"] = self.analyze_samples(stress_samples, "Stress")
        print(f"  Max temp: {results['tests']['stress']['temperature']['max']}°C")
        print(f"  Throttle events: {results['tests']['stress']['throttle_events']}")

        # Cooldown
        print("\n[3/3] Cooldown Test")
        cooldown_samples = self.idle_test(idle_duration)
        results["tests"]["cooldown"] = self.analyze_samples(cooldown_samples, "Cooldown")
        print(f"  Final temp: {cooldown_samples[-1]['temp_c'] if cooldown_samples else 'N/A'}°C")

        # Calculate cooling efficiency
        if results["tests"]["stress"]["temperature"]["max"] > 0 and cooldown_samples:
            temp_drop = results["tests"]["stress"]["temperature"]["max"] - cooldown_samples[-1]["temp_c"]
            results["cooling_efficiency"] = {
                "temp_drop_c": round(temp_drop, 1),
                "drop_rate_c_per_min": round((temp_drop / idle_duration) * 60, 2)
            }

        # Summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)
        print(f"Pi Model: {results['pi_model']}")
        print(f"Configured Freq: {results['configured_freq']} MHz")
        print(f"Idle Temp: {results['tests']['idle']['temperature']['avg']}°C")
        print(f"Stress Max Temp: {results['tests']['stress']['temperature']['max']}°C")
        print(f"Temp Rise: {results['tests']['stress']['temperature']['max'] - results['tests']['idle']['temperature']['avg']:.1f}°C")
        print(f"Throttle Events: {results['tests']['stress']['throttle_events']} ({results['tests']['stress']['throttle_percent']}%)")
        if "cooling_efficiency" in results:
            print(f"Cooling Rate: {results['cooling_efficiency']['drop_rate_c_per_min']}°C/min")

        # Recommendations
        print("\nRECOMMENDATIONS:")
        max_temp = results["tests"]["stress"]["temperature"]["max"]
        throttle_pct = results["tests"]["stress"]["throttle_percent"]

        if max_temp >= 85:
            print("  - CRITICAL: Device is thermal throttling severely")
            print("  - Add active cooling (fan) or reduce CPU profile")
        elif max_temp >= 75:
            print("  - WARNING: Running hot, consider better cooling")
            print("  - Passive heatsink with airflow recommended")
        elif max_temp >= 65:
            print("  - GOOD: Acceptable for enclosed operation")
            print("  - Add ventilation holes to enclosure if not present")
        else:
            print("  - EXCELLENT: Cool running, current setup is adequate")

        if throttle_pct > 10:
            print(f"  - Throttling at {throttle_pct}% - lower CPU profile recommended")

        return results

    def run_quick_benchmark(self):
        """Run quick 30-second benchmark"""
        return self.run_full_benchmark(idle_duration=10, stress_duration=20)

    def save_results(self, results):
        """Save results to JSON file"""
        # Load existing results
        all_results = []
        if self.results_file.exists():
            try:
                with open(self.results_file) as f:
                    all_results = json.load(f)
            except:
                pass

        # Add new results
        all_results.append(results)

        # Keep last 50 results
        all_results = all_results[-50:]

        # Save
        with open(self.results_file, "w") as f:
            json.dump(all_results, f, indent=2)

        print(f"\nResults saved to {self.results_file}")
        return self.results_file


def main():
    parser = argparse.ArgumentParser(description="Vernis Performance Benchmark")
    parser.add_argument("--quick", action="store_true", help="Run quick 30s benchmark")
    parser.add_argument("--stress", action="store_true", help="Run stress test only")
    parser.add_argument("--idle", type=int, default=30, help="Idle test duration (seconds)")
    parser.add_argument("--duration", type=int, default=60, help="Stress test duration (seconds)")
    parser.add_argument("--output", type=str, help="Output JSON file path")
    parser.add_argument("--sample", action="store_true", help="Take single sample and exit")

    args = parser.parse_args()

    benchmark = PerformanceBenchmark()

    if args.sample:
        # Single sample mode
        sample = benchmark.sample_metrics()
        print(json.dumps(sample, indent=2))
        return

    if args.quick:
        results = benchmark.run_quick_benchmark()
    elif args.stress:
        samples = benchmark.cpu_stress_test(args.duration)
        results = {
            "timestamp": datetime.now().isoformat(),
            "pi_model": benchmark.get_pi_model(),
            "tests": {"stress": benchmark.analyze_samples(samples, "Stress")}
        }
    else:
        results = benchmark.run_full_benchmark(args.idle, args.duration)

    benchmark.save_results(results)

    # Output path override
    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Also saved to {args.output}")

    # Notify API that benchmark is complete
    try:
        requests.post("http://127.0.0.1:5000/api/benchmark/complete", timeout=5)
    except:
        pass  # API might not be running


if __name__ == "__main__":
    main()
