# Vernis v3 - Deployment Guide

This guide explains how to deploy Vernis v3 to one or more Raspberry Pi devices over your local network.

## Quick Start

1. **Edit the config file** with your Pi credentials:
   ```bash
   nano pi-devices.json
   ```

2. **Run the deployment script**:
   ```bash
   python3 deploy-to-pi.py
   ```

3. **SSH into your Pi and run the installer**:
   ```bash
   ssh pi@192.168.1.100
   cd ~/vernisv3
   sudo bash install.sh
   ```

---

## Prerequisites

### On Your Computer (macOS)

Install required tools:
```bash
brew install rsync
brew install hudochenkov/sshpass/sshpass
```

### On Your Raspberry Pi

1. **Fresh Raspberry Pi OS Lite** installed on SD card
2. **SSH enabled** (create empty `ssh` file in boot partition)
3. **Connected to your local network** (WiFi or Ethernet)
4. **Know the Pi's IP address** (check your router or use `arp -a` to scan)

---

## Configuration

### 1. Edit `pi-devices.json`

```json
{
  "devices": [
    {
      "name": "Pi-Living-Room",
      "host": "192.168.1.100",
      "username": "pi",
      "password": "raspberry",
      "enabled": true
    },
    {
      "name": "Pi-Gallery",
      "host": "192.168.1.101",
      "username": "pi",
      "password": "newpassword",
      "enabled": true
    }
  ],
  "deployment": {
    "target_directory": "/home/pi/vernisv3",
    "auto_install": false,
    "files_to_exclude": [
      ".git",
      ".claude",
      "__pycache__",
      "*.pyc",
      "node_modules",
      ".DS_Store",
      "pi-devices.json",
      "deploy-to-pi.py"
    ]
  }
}
```

### Configuration Options

- **name**: Friendly name for the device
- **host**: IP address of the Pi on your local network
- **username**: SSH username (usually `pi`)
- **password**: SSH password (default is `raspberry`, change it!)
- **enabled**: Set to `false` to skip this device during deployment
- **target_directory**: Where files will be copied on the Pi
- **auto_install**: Set to `true` to automatically run `install.sh` (takes 10+ minutes)
- **files_to_exclude**: Files/folders that won't be transferred

---

## Usage

### Deploy to All Enabled Devices

```bash
python3 deploy-to-pi.py
```

The script will:
1. Check SSH connectivity to each Pi
2. Create the target directory
3. Transfer all files (excluding specified patterns)
4. Optionally run the installation script

### Deploy Only (No Auto-Install)

Set `"auto_install": false` in the config, then:

```bash
python3 deploy-to-pi.py
```

After files are transferred, manually SSH into each Pi:

```bash
ssh pi@192.168.1.100
cd ~/vernisv3
sudo bash install.sh
```

### Auto-Install Mode

Set `"auto_install": true` in the config to automatically run the installation after file transfer. **Warning**: This can take 10-15 minutes per device.

---

## Finding Your Pi's IP Address

### Method 1: Router Admin Panel
Check your router's DHCP client list

### Method 2: Network Scan (macOS)
```bash
# Find all devices on your network
arp -a | grep -E "192.168"
```

### Method 3: Use Pi's Hostname (if mDNS is enabled)
```bash
ssh pi@raspberrypi.local
```

### Method 4: Connect to Pi via Monitor
1. Connect keyboard/monitor to Pi
2. Login and run: `hostname -I`

---

## Security Recommendations

1. **Change default password**: The default `raspberry` password is insecure
   ```bash
   ssh pi@192.168.1.100
   passwd
   ```

2. **Use SSH keys instead of passwords** (more secure):
   ```bash
   # Generate SSH key on your computer
   ssh-keygen -t ed25519

   # Copy to Pi
   ssh-copy-id pi@192.168.1.100

   # Disable password authentication on Pi
   sudo nano /etc/ssh/sshd_config
   # Set: PasswordAuthentication no
   sudo systemctl restart ssh
   ```

3. **Keep `pi-devices.json` private**: This file is excluded from git by default

---

## Troubleshooting

### "sshpass: command not found"
Install sshpass:
```bash
brew install hudochenkov/sshpass/sshpass  # macOS
sudo apt-get install sshpass              # Linux
```

### "Connection refused" or "Connection timeout"
- Check Pi is powered on and connected to network
- Verify IP address is correct
- Ensure SSH is enabled on Pi
- Check firewall settings

### "Permission denied"
- Verify username/password in config
- Default credentials: username=`pi`, password=`raspberry`

### Files not transferring
- Check `files_to_exclude` patterns in config
- Verify sufficient disk space on Pi: `df -h`

### Installation fails
- Check Pi has internet connection: `ping google.com`
- Verify sufficient disk space (needs ~2GB free)
- Check installation log for errors

---

## Workflow for Multiple Devices

### Initial Setup (One-Time)
1. Flash Raspberry Pi OS to SD card
2. Enable SSH (create `ssh` file in boot partition)
3. Configure WiFi (create `wpa_supplicant.conf` in boot partition)
4. Boot Pi and find its IP address
5. Add Pi to `pi-devices.json`

### Regular Updates
1. Make changes to your code
2. Run `python3 deploy-to-pi.py`
3. Changes are deployed to all enabled devices

### Repeat for Each New Device
Just add new entries to the `devices` array in `pi-devices.json`.

---

## Advanced: Update Only (Skip Full Install)

If you've already run the full installation and just want to update files:

1. Keep `auto_install: false` in config
2. Run deployment: `python3 deploy-to-pi.py`
3. SSH into Pi and restart services:
   ```bash
   ssh pi@192.168.1.100
   sudo systemctl restart vernis-api
   sudo systemctl restart caddy
   ```

---

## What Gets Installed

The `install.sh` script will:
- Update system packages
- Install Caddy web server
- Install Python dependencies
- Configure systemd services
- Setup mDNS (access via `vernis.local`)
- Configure fallback WiFi AP mode
- Optimize SD card endurance
- Optional: Setup kiosk mode with display

After installation, access the web interface at:
- `http://vernis.local` (if mDNS works)
- `http://192.168.1.100` (direct IP)
- `http://Vernis-XXXXXXXX` (fallback AP mode)

---

## Tips

- **Test with one Pi first**: Enable only one device until you verify it works
- **Use descriptive names**: Helps identify devices in large deployments
- **Keep backups**: The script doesn't delete files, but accidents happen
- **Monitor the installation**: First run takes longest (10-15 minutes)
- **Check the logs**: SSH into Pi and check `/var/log/vernis-api.log`
