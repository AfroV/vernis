# Vernis v3 - Deployment Scripts

This directory contains all scripts and documentation needed to deploy Vernis v3 to production devices.

## 📁 Files Overview

### 🚀 Deployment Scripts
- **`create-sd-image.sh`** - Creates deployment package (TAR or IMG)
- **`first-boot-setup.sh`** - Auto-setup script that runs on first boot
- **`install-services.sh`** - Installs systemd services

### ⚙️ Service Files
- **`vernis-backend.service`** - Systemd service for Flask API
- **`vernis-ipfs.service`** - Systemd service for IPFS daemon

### 📖 Documentation
- **`QUICK_START.md`** - 5-minute quick start guide
- **`SD_CARD_DEPLOYMENT.md`** - Comprehensive SD card deployment guide
- **`PRODUCTION_READY_GUIDE.md`** - Complete production deployment workflow

## 🎯 Quick Start

### For Single Unit Deployment
```bash
# 1. Create deployment package
sudo bash create-sd-image.sh
# Select option 1 (TAR package)

# 2. Copy to Raspberry Pi
scp ../release/vernis-v3-*.tar.gz pi@raspberrypi.local:/tmp/
scp ../release/install-vernis.sh pi@raspberrypi.local:/tmp/

# 3. SSH and install
ssh pi@raspberrypi.local
cd /tmp
sudo bash install-vernis.sh

# 4. Access at http://vernis.local
```

### For Mass Production
```bash
# 1. Set up one perfect master unit (follow above)
# 2. See PRODUCTION_READY_GUIDE.md for master image creation
# 3. Clone master image to all SD cards
```

## 📋 What Each Script Does

### `create-sd-image.sh`
Creates deployable packages:
- Option 1: TAR archive (~50-100MB) - Recommended
- Option 2: Full IMG file (2-8GB) - Advanced users

### `first-boot-setup.sh`
Automated first-boot configuration:
1. Updates system packages (optional)
2. Installs Python, Flask, dependencies
3. Installs and configures IPFS (Kubo)
4. Creates vernis user
5. Installs systemd services
6. Configures network (vernis.local)
7. Optimizes system
8. Starts services

Runtime: ~5-10 minutes

### `install-services.sh`
- Copies service files to `/etc/systemd/system/`
- Enables services to start on boot
- Reloads systemd daemon

## 🔧 Customization

### Before Deployment

**1. Edit default configuration**
```bash
# Edit device defaults
nano ../config/device-config.json
```

**2. Customize branding**
```bash
# Edit theme colors
nano ../vernis-themes.css
```

**3. Pre-load collections**
```bash
# Add CSV files
cp your-collection.csv ../csv-library/
```

### Environment Variables

Set these before running `first-boot-setup.sh`:

- `SKIP_UPDATE=1` - Skip apt-get update (faster setup)
- `DISABLE_BLUETOOTH=1` - Disable Bluetooth (default: enabled)
- `AUTO_REBOOT=1` - Auto-reboot after setup

Example:
```bash
SKIP_UPDATE=1 AUTO_REBOOT=1 sudo bash first-boot-setup.sh
```

## 📊 Service Architecture

```
┌─────────────────────────────────────┐
│     User Browser                    │
│     http://vernis.local             │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  vernis-backend.service             │
│  Flask API (Port 5000)              │
│  - Serves web interface             │
│  - Handles API requests             │
│  - Manages NFT downloads            │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  vernis-ipfs.service                │
│  IPFS Daemon (Kubo)                 │
│  - Gateway: localhost:8080          │
│  - API: localhost:5001              │
│  - Pins NFT files                   │
└─────────────────────────────────────┘
```

## 🔐 Security Notes

### Default Setup (Development)
- SSH enabled with default password
- No firewall
- HTTP only (no HTTPS)

### Production Hardening (See PRODUCTION_READY_GUIDE.md)
- Change all default passwords
- Enable firewall (ufw)
- Disable or secure SSH
- Optional: HTTPS with Let's Encrypt
- Optional: Auto-updates

## 📦 Package Contents

When you create a deployment package, it includes:

```
vernis-v3-YYYYMMDD.tar.gz
├── backend/                 # Flask API
├── scripts/                 # Download scripts
├── deploy/                  # Deployment files (this dir)
├── csv-library/             # Pre-loaded collections
├── config/                  # Configuration
├── *.html                   # Web interface
├── *.css                    # Stylesheets
└── *.js                     # JavaScript files
```

## 🚨 Troubleshooting

### Setup fails during IPFS installation
```bash
# Manually install IPFS
wget https://dist.ipfs.tech/kubo/v0.24.0/kubo_v0.24.0_linux-arm64.tar.gz
tar -xzf kubo_v0.24.0_linux-arm64.tar.gz
cd kubo
sudo bash install.sh
```

### Services won't start
```bash
# Check logs
journalctl -u vernis-backend -n 50
journalctl -u vernis-ipfs -n 50

# Check permissions
sudo chown -R vernis:vernis /opt/vernis
```

### Network issues (can't access vernis.local)
```bash
# Check avahi
sudo systemctl status avahi-daemon

# Or use IP address
hostname -I
```

## 📞 Support

- Quick Start: `QUICK_START.md`
- Full Deployment: `SD_CARD_DEPLOYMENT.md`
- Production: `PRODUCTION_READY_GUIDE.md`
- Setup Logs: `/var/log/vernis-setup.log`

## 🎉 Ready to Deploy!

Start with `QUICK_START.md` for immediate deployment, or review `PRODUCTION_READY_GUIDE.md` for manufacturing workflow.

**Happy deploying! 🚀**
