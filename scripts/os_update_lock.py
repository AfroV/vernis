#!/usr/bin/env python3
"""
Vernis OS Update Lock Manager

Prevents accidental kernel/firmware updates that could break the built-in display.
Updates should only be applied after testing on a development device.

Usage:
  python3 os_update_lock.py --status          # Show current lock status
  python3 os_update_lock.py --lock            # Lock critical packages
  python3 os_update_lock.py --unlock          # Temporarily unlock for updates
  python3 os_update_lock.py --safe-update     # Run safe updates (excludes kernel/firmware)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Packages that should be held (not updated) to protect display compatibility
CRITICAL_PACKAGES = [
    "raspberrypi-kernel",
    "raspberrypi-kernel-headers",
    "raspberrypi-bootloader",
    "libraspberrypi0",
    "libraspberrypi-bin",
    "libraspberrypi-dev",
    "libraspberrypi-doc",
    "raspi-firmware",
    "linux-image-*",
    "rpi-eeprom",
    "rpi-eeprom-images",
]

# Additional packages to hold for DSI display stability
DSI_PACKAGES = [
    "mesa-*",
    "libdrm*",
    "xserver-xorg-video-fbdev",
    "xserver-xorg-video-fbturbo",
]

STATUS_FILE = Path("/opt/vernis/os-lock-status.json")
LOG_FILE = Path("/opt/vernis/os-update.log")


def log_action(action, details=""):
    """Log an action to the update log"""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"{timestamp} | {action} | {details}\n")
    except:
        pass


def run_cmd(cmd, check=True):
    """Run a shell command and return output"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def get_held_packages():
    """Get list of currently held packages"""
    success, stdout, _ = run_cmd("dpkg --get-selections | grep hold")
    if success and stdout:
        return [line.split()[0] for line in stdout.split("\n") if line]
    return []


def get_package_version(package):
    """Get installed version of a package"""
    success, stdout, _ = run_cmd(f"dpkg -s {package} 2>/dev/null | grep ^Version")
    if success and stdout:
        return stdout.replace("Version:", "").strip()
    return None


def hold_package(package):
    """Mark a package as held"""
    success, _, stderr = run_cmd(f"echo '{package} hold' | dpkg --set-selections")
    return success


def unhold_package(package):
    """Remove hold from a package"""
    success, _, stderr = run_cmd(f"echo '{package} install' | dpkg --set-selections")
    return success


def get_installed_critical_packages():
    """Get list of critical packages that are actually installed"""
    installed = []
    for pkg in CRITICAL_PACKAGES + DSI_PACKAGES:
        if "*" in pkg:
            # Handle wildcards
            base = pkg.replace("*", "")
            success, stdout, _ = run_cmd(f"dpkg -l | grep '^ii' | awk '{{print $2}}' | grep '^{base}'")
            if success and stdout:
                installed.extend(stdout.split("\n"))
        else:
            version = get_package_version(pkg)
            if version:
                installed.append(pkg)
    return list(set(installed))


def check_status():
    """Check and return current lock status"""
    held = get_held_packages()
    installed_critical = get_installed_critical_packages()

    # Check which critical packages are held
    protected = [p for p in installed_critical if p in held]
    unprotected = [p for p in installed_critical if p not in held]

    # Check if apt unattended-upgrades is disabled
    unattended_disabled = False
    if Path("/etc/apt/apt.conf.d/20auto-upgrades").exists():
        success, stdout, _ = run_cmd("cat /etc/apt/apt.conf.d/20auto-upgrades")
        if "0" in stdout:
            unattended_disabled = True

    # Check if apt-daily timers are disabled
    apt_daily_disabled = False
    success, stdout, _ = run_cmd("systemctl is-enabled apt-daily.timer 2>/dev/null")
    if "disabled" in stdout or not success:
        apt_daily_disabled = True

    status = {
        "locked": len(unprotected) == 0 and len(protected) > 0,
        "protected_packages": protected,
        "unprotected_packages": unprotected,
        "total_critical": len(installed_critical),
        "unattended_upgrades_disabled": unattended_disabled,
        "apt_daily_disabled": apt_daily_disabled,
        "last_checked": datetime.now().isoformat()
    }

    # Save status
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2)
    except:
        pass

    return status


def lock_packages():
    """Lock all critical packages"""
    print("Locking critical packages to prevent display breakage...")

    installed = get_installed_critical_packages()
    locked = 0
    failed = []

    for pkg in installed:
        if hold_package(pkg):
            print(f"  ✓ Held: {pkg}")
            locked += 1
        else:
            print(f"  ✗ Failed: {pkg}")
            failed.append(pkg)

    # Disable unattended-upgrades if present
    print("\nDisabling automatic updates...")

    # Disable apt-daily timer
    run_cmd("systemctl disable apt-daily.timer 2>/dev/null")
    run_cmd("systemctl disable apt-daily-upgrade.timer 2>/dev/null")
    run_cmd("systemctl stop apt-daily.timer 2>/dev/null")
    run_cmd("systemctl stop apt-daily-upgrade.timer 2>/dev/null")

    # Disable unattended-upgrades
    auto_upgrades_file = Path("/etc/apt/apt.conf.d/20auto-upgrades")
    if auto_upgrades_file.exists():
        try:
            auto_upgrades_file.write_text(
                'APT::Periodic::Update-Package-Lists "0";\n'
                'APT::Periodic::Unattended-Upgrade "0";\n'
            )
            print("  ✓ Disabled unattended-upgrades")
        except PermissionError:
            run_cmd(f'echo \'APT::Periodic::Update-Package-Lists "0";\nAPT::Periodic::Unattended-Upgrade "0";\' | sudo tee {auto_upgrades_file}')

    log_action("LOCK", f"Locked {locked} packages")

    print(f"\nLocked {locked} packages")
    if failed:
        print(f"Failed to lock: {', '.join(failed)}")

    return len(failed) == 0


def unlock_packages():
    """Temporarily unlock packages for manual update"""
    print("Unlocking packages for manual update...")
    print("WARNING: Only proceed if you have tested updates on another device!")

    held = get_held_packages()
    unlocked = 0

    for pkg in held:
        if unhold_package(pkg):
            print(f"  ✓ Unheld: {pkg}")
            unlocked += 1

    log_action("UNLOCK", f"Unlocked {unlocked} packages")

    print(f"\nUnlocked {unlocked} packages")
    print("\nRemember to run --lock after updating to re-protect packages!")

    return True


def safe_update():
    """Run safe updates that exclude kernel/firmware"""
    print("Running safe package updates (excluding kernel/firmware)...")

    # First ensure critical packages are held
    lock_packages()

    print("\nUpdating package lists...")
    success, stdout, stderr = run_cmd("apt-get update")
    if not success:
        print(f"Failed to update package lists: {stderr}")
        return False

    print("\nUpgrading safe packages...")
    # Use apt-get upgrade (not dist-upgrade) with held packages
    success, stdout, stderr = run_cmd("apt-get upgrade -y --allow-change-held-packages=false")

    if success:
        print("\n✓ Safe update completed successfully")
        log_action("SAFE_UPDATE", "Completed successfully")
    else:
        print(f"\nUpdate had issues: {stderr}")
        log_action("SAFE_UPDATE", f"Issues: {stderr[:100]}")

    return success


def print_status(status):
    """Pretty print the status"""
    print("\n" + "=" * 50)
    print("OS Update Lock Status")
    print("=" * 50)

    if status["locked"]:
        print(f"\n🔒 Status: LOCKED (Protected)")
    else:
        print(f"\n🔓 Status: UNLOCKED (Vulnerable to updates)")

    print(f"\nProtected packages: {len(status['protected_packages'])}")
    print(f"Unprotected packages: {len(status['unprotected_packages'])}")

    if status['unprotected_packages']:
        print("\n⚠️  Unprotected critical packages:")
        for pkg in status['unprotected_packages'][:10]:
            print(f"   - {pkg}")
        if len(status['unprotected_packages']) > 10:
            print(f"   ... and {len(status['unprotected_packages']) - 10} more")

    print(f"\nAutomatic updates disabled: {'Yes' if status['unattended_upgrades_disabled'] else 'No'}")
    print(f"APT daily timer disabled: {'Yes' if status['apt_daily_disabled'] else 'No'}")

    print("\n" + "=" * 50)

    if not status["locked"]:
        print("\nRun with --lock to protect your system")


def get_kernel_info():
    """Get current kernel information"""
    info = {}

    success, stdout, _ = run_cmd("uname -r")
    if success:
        info["running_kernel"] = stdout

    success, stdout, _ = run_cmd("dpkg -l | grep raspberrypi-kernel | head -1 | awk '{print $3}'")
    if success:
        info["installed_kernel_version"] = stdout

    success, stdout, _ = run_cmd("cat /proc/device-tree/model 2>/dev/null")
    if success:
        info["device_model"] = stdout.replace("\x00", "")

    return info


def main():
    parser = argparse.ArgumentParser(
        description="Vernis OS Update Lock Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Check current status:     python3 os_update_lock.py --status
  Lock critical packages:   sudo python3 os_update_lock.py --lock
  Safe update:              sudo python3 os_update_lock.py --safe-update
  Temporary unlock:         sudo python3 os_update_lock.py --unlock
        """
    )

    parser.add_argument("--status", "-s", action="store_true", help="Show lock status")
    parser.add_argument("--lock", "-l", action="store_true", help="Lock critical packages")
    parser.add_argument("--unlock", "-u", action="store_true", help="Unlock packages (use with caution)")
    parser.add_argument("--safe-update", action="store_true", help="Run safe updates")
    parser.add_argument("--json", action="store_true", help="Output status as JSON")
    parser.add_argument("--kernel-info", action="store_true", help="Show kernel information")

    args = parser.parse_args()

    # Check for root if needed
    if (args.lock or args.unlock or args.safe_update) and os.geteuid() != 0:
        print("Error: This operation requires root privileges. Run with sudo.")
        sys.exit(1)

    if args.kernel_info:
        info = get_kernel_info()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print("\nKernel Information:")
            for key, value in info.items():
                print(f"  {key}: {value}")
        return

    if args.lock:
        success = lock_packages()
        status = check_status()
        print_status(status)
        sys.exit(0 if success else 1)

    if args.unlock:
        success = unlock_packages()
        sys.exit(0 if success else 1)

    if args.safe_update:
        success = safe_update()
        sys.exit(0 if success else 1)

    # Default: show status
    status = check_status()
    if args.json:
        print(json.dumps(status, indent=2))
    else:
        print_status(status)


if __name__ == "__main__":
    main()
