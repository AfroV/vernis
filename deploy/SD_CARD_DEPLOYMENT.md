# Vernis v3 - SD Card Deployment Guide

## 🎯 Overview

This guide helps you create production-ready SD card images for Vernis devices. The setup includes:

- **Auto-installation** on first boot
- **IPFS daemon** with pinning service
- **Web interface** auto-start
- **Network configuration**
- **Production optimization**

---

## 📦 Package Structure

```
/opt/vernis/
├── backend/           # Flask API server
├── scripts/           # Download & utility scripts
├── nfts/             # NFT storage directory
├── uploads/          # CSV upload temporary storage
├── csv-library/      # Pre-packaged NFT collections
├── config/           # Configuration files
├── *.html            # Frontend files
├── *.css/.js         # Assets
└── deploy/           # Deployment scripts
    ├── first-boot-setup.sh
    ├── install-services.sh
    └── vernis.service
```

---

## 🚀 Quick Deployment Steps

### 1. Base OS Image
Start with **Raspberry Pi OS Lite (64-bit)** or **DietPi**

### 2. Run Deployment Script
```bash
# On your development machine
cd /opt/vernis/deploy
sudo bash create-sd-image.sh
```

### 3. Flash to SD Card
```bash
# Using dd (Linux/Mac)
sudo dd if=vernis-v3.img of=/dev/sdX bs=4M status=progress

# Or use Raspberry Pi Imager with the generated image
```

### 4. First Boot
- Insert SD card into Raspberry Pi
- Power on
- Auto-setup runs (5-10 minutes)
- Access via: `http://vernis.local`

---

## 🔧 What Happens on First Boot

1. **System Update** (optional, can be disabled for faster setup)
2. **Install Dependencies**:
   - Python 3.10+
   - Flask, requests
   - IPFS (kubo)
   - Network Manager
   - UFW (firewall)
3. **Configure IPFS**:
   - Initialize IPFS repository
   - Enable pinning service with **2TB storage limit**
   - Configure gateway (localhost:8080)
   - Optimize for large collections
4. **Install Systemd Services**:
   - `vernis-backend.service` - Flask API
   - `vernis-ipfs.service` - IPFS daemon
5. **Configure Firewall (UFW)**:
   - Enable firewall
   - Allow port 5000 (Web interface)
   - Allow port 22 (SSH - disable after setup)
   - Allow port 5353 (mDNS)
6. **Network Setup**:
   - Configure WiFi AP mode (optional)
   - Set hostname to `vernis`
   - Enable mDNS (vernis.local)
7. **Optimize**:
   - Disable unnecessary services
   - Configure auto-login to web interface

---

## 📋 Production Checklist

### Hardware Requirements
- [ ] Raspberry Pi 4 (2GB+ RAM recommended)
- [ ] 32GB+ SD card (Class 10 or better)
- [ ] Power supply (5V 3A for RPi 4)
- [ ] Case with cooling (optional but recommended)

### Software Configuration
- [ ] Set static IP or configure mDNS
- [ ] Configure WiFi credentials
- [ ] Pre-load CSV collections in `/opt/vernis/csv-library/`
- [ ] Set custom branding (logo, colors in theme CSS)
- [ ] Configure IPFS gateway preferences

### Security Hardening
- [x] Firewall enabled (UFW) - **Configured automatically**
- [ ] Change default passwords
- [ ] Disable SSH after setup (port 22 open by default)
- [ ] Use SSH key-based auth only (disable password auth)
- [ ] Set up HTTPS (optional, for remote access)

---

## 🎨 Customization Before Deployment

### 1. Branding
Edit `vernis-themes.css` to customize colors and fonts.

### 2. Pre-load Collections
Place CSV files in `/opt/vernis/csv-library/` with metadata:

```json
{
  "name": "Bored Ape Yacht Club",
  "description": "10,000 unique NFTs",
  "count": 10000,
  "preview": "preview.jpg"
}
```

### 3. Default Settings
Edit `/opt/vernis/config/device-config.json`:

```json
{
  "device_name": "Vernis Gallery",
  "display": {
    "image_duration": 15,
    "video_duration": 30,
    "shuffle": true
  },
  "network": {
    "hostname": "vernis",
    "ap_mode": false
  }
}
```

---

## 🔄 Update Strategy

### OTA Updates (Over-The-Air)
```bash
# On device
sudo systemctl stop vernis-backend
cd /opt/vernis
git pull origin main
sudo systemctl start vernis-backend
```

### SD Card Updates
1. Create new image with updates
2. Flash to new SD card
3. Swap SD cards (hot-swap safe after shutdown)

---

## 🐛 Troubleshooting

### Service Status
```bash
sudo systemctl status vernis-backend
sudo systemctl status vernis-ipfs
```

### View Logs
```bash
journalctl -u vernis-backend -f
journalctl -u vernis-ipfs -f
```

### Reset to Defaults
```bash
cd /opt/vernis/deploy
sudo bash factory-reset.sh
```

---

## 📊 Performance Optimization

### For Large Collections (1000+ NFTs)
- **IPFS configured for 2TB storage** (default)
- Use SSD instead of SD card (via USB 3.0) for better performance
- Use 4GB+ RAM Raspberry Pi model
- Garbage collection runs every 6 hours automatically

### For Demo/Retail Units
- Pre-download popular collections
- Disable auto-updates
- Set IPFS to offline mode (local only)

---

## 🏭 Manufacturing/Mass Production

### Creating Master Image
1. Set up one perfect unit
2. Remove unique identifiers (SSH keys, etc.)
3. Create image: `sudo dd if=/dev/mmcblk0 of=vernis-master.img bs=4M`
4. Compress: `gzip vernis-master.img`

### Cloning Process
1. Flash master image to all SD cards
2. Each unit gets unique ID on first boot
3. QR code or NFC tag for device pairing

### Quality Control Checklist
- [ ] Boot test (successful boot in <2 min)
- [ ] Network connectivity
- [ ] IPFS daemon running
- [ ] Web interface accessible
- [ ] Sample NFT download test
- [ ] Display slideshow test

---

## 📝 Next Steps for Production

1. **Packaging**: Create retail packaging with quick start guide
2. **Support Portal**: Set up customer support system
3. **Documentation**: User manual with setup wizard
4. **Warranty**: Define warranty and return policy
5. **Compliance**: CE/FCC certification if selling in EU/US
