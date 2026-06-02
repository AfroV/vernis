#!/usr/bin/env python3
"""
Vernis v3 - Raspberry Pi Deployment Script
Deploys files to one or more Raspberry Pis over SSH
"""

import json
import subprocess
import sys
import os
import re
import time
from pathlib import Path

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_step(message):
    """Print a step message"""
    print(f"{Colors.BLUE}==>{Colors.RESET} {message}")

def print_success(message):
    """Print a success message"""
    print(f"{Colors.GREEN}✓{Colors.RESET} {message}")

def print_error(message):
    """Print an error message"""
    print(f"{Colors.RED}✗{Colors.RESET} {message}")

def print_warning(message):
    """Print a warning message"""
    print(f"{Colors.YELLOW}!{Colors.RESET} {message}")

def print_progress_bar(percentage, width=40, label="Progress"):
    """Print a progress bar"""
    filled = int(width * percentage / 100)
    bar = '█' * filled + '░' * (width - filled)
    print(f"\r{Colors.CYAN}{label}:{Colors.RESET} [{bar}] {percentage:3.0f}%", end='', flush=True)

def load_config(config_path="pi-devices.json"):
    """Load the configuration file"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print_error(f"Config file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON in config file: {e}")
        sys.exit(1)

def test_connection(device):
    """Test SSH connection to a device"""
    host = f"{device['username']}@{device['host']}"
    use_ssh_key = device.get('use_ssh_key', False)

    if use_ssh_key:
        # Use SSH keys
        cmd = [
            'ssh', '-o', 'StrictHostKeyChecking=no',
            '-o', 'ConnectTimeout=10',
            '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=2',
            host, 'echo "connected"'
        ]
    else:
        # Use password authentication
        cmd = [
            'sshpass', '-p', device['password'],
            'ssh', '-o', 'StrictHostKeyChecking=no',
            '-o', 'ConnectTimeout=10',
            '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=2',
            '-o', 'PubkeyAuthentication=no',
            host, 'echo "connected"'
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            # Print error details for debugging
            if result.stderr:
                print_warning(f"Connection error: {result.stderr.strip()}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print_warning("Connection timeout - host may be unreachable")
        return False
    except Exception as e:
        print_warning(f"Connection error: {str(e)}")
        return False

def deploy_to_device(device, config, source_dir):
    """Deploy files to a single device"""
    device_name = device['name']
    host = f"{device['username']}@{device['host']}"
    target_dir = config['deployment']['target_directory']
    use_ssh_key = device.get('use_ssh_key', False)

    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}Deploying to: {device_name} ({device['host']}){Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")

    # Test connection
    print_step(f"Testing connection to {device_name}...")
    if not test_connection(device):
        print_error(f"Cannot connect to {device_name}")
        return False
    print_success("Connection successful")

    # Create target directory
    print_step(f"Creating target directory on {device_name}...")
    if use_ssh_key:
        mkdir_cmd = [
            'ssh', '-o', 'StrictHostKeyChecking=no',
            host, f'mkdir -p {target_dir}'
        ]
    else:
        mkdir_cmd = [
            'sshpass', '-p', device['password'],
            'ssh', '-o', 'StrictHostKeyChecking=no',
            host, f'mkdir -p {target_dir}'
        ]

    result = subprocess.run(mkdir_cmd, capture_output=True)
    if result.returncode != 0:
        print_error(f"Failed to create directory: {result.stderr.decode()}")
        return False
    print_success("Directory created")

    # Build rsync exclude patterns
    excludes = []
    for pattern in config['deployment']['files_to_exclude']:
        excludes.extend(['--exclude', pattern])

    # Sync files
    print_step(f"Transferring files to {device_name}...")
    if use_ssh_key:
        rsync_cmd = [
            'rsync', '-az', '--info=progress2',
            '-e', 'ssh -o StrictHostKeyChecking=no',
            *excludes,
            f"{source_dir}/",
            f"{host}:{target_dir}/"
        ]
    else:
        rsync_cmd = [
            'rsync', '-az', '--info=progress2',
            '-e', f"sshpass -p {device['password']} ssh -o StrictHostKeyChecking=no",
            *excludes,
            f"{source_dir}/",
            f"{host}:{target_dir}/"
        ]

    # Run rsync with progress tracking
    process = subprocess.Popen(rsync_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    for line in process.stdout:
        # Parse rsync progress2 output: "1,234,567  45%  123.45kB/s    0:00:12"
        match = re.search(r'(\d+)%', line)
        if match:
            percentage = int(match.group(1))
            print_progress_bar(percentage, label="Transferring")

    process.wait()
    print()  # New line after progress bar

    if process.returncode != 0:
        print_error("File transfer failed")
        return False
    print_success("Files transferred successfully")

    # Run installation if enabled
    if config['deployment'].get('auto_install', False):
        print_step(f"Running installation on {device_name}...")

        # Make install.sh executable
        if use_ssh_key:
            chmod_cmd = [
                'ssh', '-o', 'StrictHostKeyChecking=no',
                host,
                f'chmod +x {target_dir}/install.sh'
            ]
        else:
            chmod_cmd = [
                'sshpass', '-p', device['password'],
                'ssh', '-o', 'StrictHostKeyChecking=no',
                host,
                f'chmod +x {target_dir}/install.sh'
            ]

        subprocess.run(chmod_cmd, capture_output=True)

        print_warning("This may take 10-15 minutes...")

        # Skip reboot if kiosk mode will be enabled
        skip_reboot = "SKIP_REBOOT=1 " if device.get('kiosk_mode', False) else ""

        if use_ssh_key:
            install_cmd = [
                'ssh', '-o', 'StrictHostKeyChecking=no',
                host,
                f'cd {target_dir} && echo "n" | sudo {skip_reboot}bash install.sh'
            ]
        else:
            install_cmd = [
                'sshpass', '-p', device['password'],
                'ssh', '-o', 'StrictHostKeyChecking=no',
                host,
                f'cd {target_dir} && echo "n" | sudo {skip_reboot}bash install.sh'
            ]

        # Run installation with progress tracking
        process = subprocess.Popen(install_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        current_step = 0
        total_steps = 10
        current_task = "Starting..."

        for line in process.stdout:
            # Parse install.sh progress markers: "[1/10] Description..."
            match = re.search(r'\[(\d+)/(\d+)\]\s+(.+?)\.\.\.', line)
            if match:
                current_step = int(match.group(1))
                total_steps = int(match.group(2))
                current_task = match.group(3)
                percentage = int((current_step / total_steps) * 100)
                print_progress_bar(percentage, label=f"Installing ({current_step}/{total_steps})")
            elif line.strip():
                # Show important messages
                if any(keyword in line.lower() for keyword in ['error', 'failed', 'warning']):
                    print(f"\n{Colors.YELLOW}{line.strip()}{Colors.RESET}")

        process.wait()
        print()  # New line after progress bar

        if process.returncode != 0:
            print_error("Installation failed")
            return False
        print_success("Installation completed")
    else:
        print_warning("Auto-install disabled. Run install.sh manually on the Pi:")
        print(f"         ssh {host}")
        print(f"         cd {target_dir}")
        print(f"         sudo bash install.sh")

    # Setup kiosk mode if enabled
    if device.get('kiosk_mode', False):
        print_step(f"Enabling kiosk mode on {device_name}...")

        if use_ssh_key:
            kiosk_cmd = [
                'ssh', '-o', 'StrictHostKeyChecking=no',
                host,
                f'cd {target_dir} && sudo systemctl disable lightdm 2>&1 || true && sudo bash enable-kiosk-simple.sh'
            ]
        else:
            kiosk_cmd = [
                'sshpass', '-p', device['password'],
                'ssh', '-o', 'StrictHostKeyChecking=no',
                host,
                f'cd {target_dir} && sudo systemctl disable lightdm 2>&1 || true && sudo bash enable-kiosk-simple.sh'
            ]

        result = subprocess.run(kiosk_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print_warning("Kiosk mode setup failed (non-critical)")
            if result.stderr:
                print_warning(f"Error: {result.stderr.strip()}")
        else:
            print_success("Kiosk mode enabled")
            print_warning("Rebooting Pi to activate kiosk mode...")

            # Trigger reboot
            if use_ssh_key:
                reboot_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', host, 'sudo reboot']
            else:
                reboot_cmd = ['sshpass', '-p', device['password'], 'ssh', '-o', 'StrictHostKeyChecking=no', host, 'sudo reboot']

            subprocess.run(reboot_cmd, capture_output=True)
            print_warning("Pi will display web interface on connected screen after reboot completes")

    return True

def check_dependencies(devices):
    """Check if required tools are installed"""
    required = ['rsync', 'ssh']

    # Only require sshpass if any device uses password authentication
    needs_sshpass = any(not d.get('use_ssh_key', False) for d in devices)
    if needs_sshpass:
        required.append('sshpass')

    missing = []
    for tool in required:
        result = subprocess.run(['which', tool], capture_output=True)
        if result.returncode != 0:
            missing.append(tool)

    if missing:
        print_error("Missing required tools:")
        for tool in missing:
            print(f"  - {tool}")
        print("\nInstall missing tools:")
        if sys.platform == 'darwin':  # macOS
            print("  brew install rsync")
            if 'sshpass' in missing:
                print("  brew install hudochenkov/sshpass/sshpass")
        else:  # Linux
            print("  sudo apt-get install rsync sshpass")
        sys.exit(1)

def main():
    """Main deployment function"""
    print(f"\n{Colors.BOLD}Vernis v3 - Pi Deployment Tool{Colors.RESET}\n")

    # Get source directory
    source_dir = os.path.dirname(os.path.abspath(__file__))

    # Load config
    print_step("Loading configuration...")
    config = load_config()

    # Filter enabled devices
    devices = [d for d in config['devices'] if d.get('enabled', True)]

    if not devices:
        print_error("No enabled devices found in config")
        sys.exit(1)

    print_success(f"Found {len(devices)} enabled device(s)")

    # Check dependencies
    check_dependencies(devices)

    # Show deployment plan
    print(f"\n{Colors.BOLD}Deployment Plan:{Colors.RESET}")
    for device in devices:
        status = "ENABLED" if device.get('enabled', True) else "DISABLED"
        kiosk = " [Kiosk Mode]" if device.get('kiosk_mode', False) else ""
        print(f"  • {device['name']} ({device['host']}) - {status}{kiosk}")
    print(f"\nTarget directory: {config['deployment']['target_directory']}")
    print(f"Auto-install: {'Yes' if config['deployment'].get('auto_install') else 'No'}")

    # Confirm
    response = input(f"\n{Colors.YELLOW}Proceed with deployment? (y/n): {Colors.RESET}")
    if response.lower() != 'y':
        print("Deployment cancelled")
        sys.exit(0)

    # Deploy to each device
    results = {}
    for device in devices:
        success = deploy_to_device(device, config, source_dir)
        results[device['name']] = success

    # Summary
    print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}Deployment Summary{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*60}{Colors.RESET}\n")

    successful = sum(1 for v in results.values() if v)
    total = len(results)

    for device_name, success in results.items():
        if success:
            print_success(f"{device_name}: Success")
        else:
            print_error(f"{device_name}: Failed")

    print(f"\n{Colors.BOLD}Result: {successful}/{total} deployments successful{Colors.RESET}\n")

    if successful < total:
        sys.exit(1)

if __name__ == "__main__":
    main()
