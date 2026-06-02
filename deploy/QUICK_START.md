# Vernis v3 - Quick Start Guide

## 🚀 Fastest Way to Deploy (5 Minutes)

### Prerequisites
- Raspberry Pi 4 (2GB+ RAM)
- 32GB+ SD card
- Raspberry Pi OS Lite (64-bit) flashed to SD card

### Installation Steps

**1. Boot your Raspberry Pi with fresh OS**

**2. SSH into the device:**
```bash
ssh pi@raspberrypi.local
# Default password: raspberry
```

**3. Download and run installer:**
```bash
# Download Vernis package
wget https://github.com/YOUR_REPO/releases/latest/download/vernis-v3-latest.tar.gz

# Download installer
wget https://github.com/YOUR_REPO/releases/latest/download/install-vernis.sh

# Install
sudo bash install-vernis.sh
```

**4. Wait 5-10 minutes for auto-setup**

**5. Connect to http://vernis.local`
- Or use IP: `http://[PI_IP_ADDRESS]:5000`

**Done! 🎉**

---

## 📝 Manual Installation (If wget fails)

```bash
# 1. Clone repository
cd /tmp
git clone https://github.com/YOUR_REPO/vernis.git

# 2. Move to /opt
sudo mv vernis /opt/vernis

# 3. Run setup
cd /opt/vernis/deploy
sudo bash first-boot-setup.sh

# 4. Access at http://vernis.local
```

---

## 🎯 First Time Setup (In Web Interface)

1. **Choose Theme**: Settings → Select your preferred theme
2. **Configure Display**: Settings → Display Configuration
   - Image duration: 15s
   - Video duration: 30s
   - Enable shuffle
3. **Add NFTs**: Add Art → Upload CSV or add single NFT
4. **Set Workers**: Select 3-4 workers for optimal speed
5. **Start Display**: Click "Display" to view your gallery

---

## 💡 Common Commands

### Service Management
```bash
# Check status
sudo systemctl status vernis-backend
sudo systemctl status vernis-ipfs

# Restart services
sudo systemctl restart vernis-backend
sudo systemctl restart vernis-ipfs

# View logs
journalctl -u vernis-backend -f
journalctl -u vernis-ipfs -f
```

### IPFS Management
```bash
# Check IPFS status
IPFS_PATH=/opt/vernis/.ipfs sudo -u vernis ipfs stats bw

# Garbage collection (free space)
IPFS_PATH=/opt/vernis/.ipfs sudo -u vernis ipfs repo gc

# Check storage usage
du -sh /opt/vernis/.ipfs/datastore
```

### Updates
```bash
# Pull latest code
cd /opt/vernis
sudo git pull

# Restart services
sudo systemctl restart vernis-backend
```

---

## 🔥 Troubleshooting

**Can't access web interface?**
```bash
# Check if backend is running
sudo systemctl status vernis-backend

# Check firewall
sudo ufw status

# Find IP address
hostname -I
```

**Downloads not working?**
```bash
# Check IPFS
sudo systemctl status vernis-ipfs

# Restart IPFS
sudo systemctl restart vernis-ipfs
```

**Out of space?**
```bash
# Clean IPFS cache
IPFS_PATH=/opt/vernis/.ipfs sudo -u vernis ipfs repo gc

# Check space
df -h /opt/vernis
```

---

## 📞 Support

- Documentation: `/opt/vernis/deploy/`
- Logs: `/var/log/vernis-setup.log`
- Issues: Check service logs with `journalctl`

---

## ⚡ Pro Tips

1. **Use SSD for large collections**: Faster than SD card
2. **Set static IP**: Easier to access
3. **Pre-download collections**: Add CSVs before demo
4. **Monitor temperature**: Keep RPi cool for best performance
5. **Regular backups**: Copy `/opt/vernis/nfts/` to backup

---

**Enjoy your Vernis! 🎨**
