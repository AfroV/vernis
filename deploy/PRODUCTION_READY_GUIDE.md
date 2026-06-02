# Vernis Production-Ready Guideployment Guide

## 🎯 Quick Start: From Development to Production

This guide walks you through deploying Vernis v3 to production-ready hardware units.

---

## 📦 Method 1: TAR Package Deployment (RECOMMENDED)

### Best for:
- Small batches (1-50 units)
- Quick prototyping
- Custom configurations per unit

### Steps:

#### 1. Create Deployment Package
```bash
cd /path/to/vernis/deploy
sudo bash create-sd-image.sh
# Select option 1 (TAR package)
```

This creates: `vernis-YYYYMMDD.tar.gz` (~50-100MB)

#### 2. Prepare SD Cards
- Flash **Raspberry Pi OS Lite (64-bit)** to SD cards
- Use Raspberry Pi Imager or balenaEtcher
- Enable SSH in imager settings (optional)

#### 3. First Boot Setup
**Option A: Automated (Copy to SD card)**
1. Mount SD card on your computer
2. Copy these files to `/boot/`:
   ```
   vernis-YYYYMMDD.tar.gz
   install-vernis.sh
   ```
3. Create `/boot/firstrun.sh`:
   ```bash
   #!/bin/bash
   cd /boot
   bash install-vernis.sh
   ```
4. Unmount and boot the Pi

**Option B: Manual SSH Installation**
1. Boot Pi with Raspberry Pi OS
2. SSH into device: `ssh pi@raspberrypi.local`
3. Copy package:
   ```bash
   # On your computer
   scp vernis-*.tar.gz pi@raspberrypi.local:/tmp/
   ```
4. Install:
   ```bash
   # On the Pi
   cd /tmp
   sudo bash install-vernis.sh
   ```

#### 4. Access Vernis
- Wait 5-10 minutes for setup to complete
- Access at: `http://vernis.local`
- Or find IP: `http://[IP_ADDRESS]:5000`

---

## 🏭 Method 2: Master Image Cloning (For Mass Production)

### Best for:
- Large batches (50+ units)
- Identical configurations
- Manufacturing partners

### Steps:

#### 1. Create Perfect Master Unit
1. Follow Method 1 to set up one device
2. Configure everything perfectly:
   - Network settings
   - Pre-loaded collections
   - Theme customization
   - Display settings

#### 2. Clean for Cloning
```bash
# Remove unique identifiers
sudo rm -f /etc/ssh/ssh_host_*
sudo rm -f /opt/vernis/.setup-complete
sudo rm -f /var/log/vernis-setup.log

# Clear IPFS identity (will regenerate on boot)
sudo rm -rf /opt/vernis/.ipfs/config
sudo rm -rf /opt/vernis/.ipfs/datastore

# Clear network configs
sudo rm -f /etc/NetworkManager/system-connections/*

# Clear bash history
history -c && history -w
```

#### 3. Create Master Image
```bash
# Shutdown the master unit
sudo shutdown -h now

# On your imaging computer (Linux/Mac)
# Insert SD card
sudo dd if=/dev/sdX of=vernis-master.img bs=4M status=progress

# Compress for distribution
gzip vernis-master.img
# Result: vernis-master.img.gz (2-4GB)
```

#### 4. Clone to Production Units
```bash
# Flash master image to each SD card
gunzip -c vernis-master.img.gz | sudo dd of=/dev/sdX bs=4M status=progress
```

#### 5. First Boot (Each Unit)
- Each unit will regenerate unique IDs automatically
- IPFS will create new peer ID
- SSH keys regenerated
- Ready to use in 1-2 minutes

---

## 🔧 Pre-Production Customization

### 1. Branding & Theming

Edit `vernis-themes.css` before deployment:
```css
:root {
  --accent-primary: #YOUR_COLOR;
  --accent-secondary: #YOUR_COLOR;
  --font-display: 'Your Font', serif;
}
```

### 2. Pre-load NFT Collections

Add CSV files to `/opt/vernis/csv-library/`:
```bash
cd /opt/vernis/csv-library

# Add your collection
cp /path/to/collection.csv ./my-collection.csv

# Add metadata
cat > my-collection.json << EOF
{
  "name": "Premium Collection",
  "description": "500 curated NFTs",
  "count": 500,
  "preview": "preview.jpg"
}
EOF
```

### 3. Default Configuration

Edit `/opt/vernis/config/device-config.json`:
```json
{
  "device_name": "Vernis Gallery Pro",
  "display": {
    "image_duration": 20,
    "video_duration": 45,
    "shuffle": true,
    "frosted_background": false
  },
  "network": {
    "hostname": "vernis",
    "ap_mode": false,
    "wifi_country": "US"
  },
  "ipfs": {
    "storage_max": "10GB",
    "gateway_port": 8080
  }
}
```

### 4. Set Default Theme

Edit `index.html` or add to setup script:
```javascript
localStorage.setItem('vernis-theme-style', 'gallery');
localStorage.setItem('vernis-theme-mode', 'light');
```

---

## 📋 Quality Control Checklist

### Hardware QC
- [ ] SD card integrity test (`sudo badblocks -sv /dev/sdX`)
- [ ] Power supply voltage check (5V ±0.25V)
- [ ] Temperature test (should stay under 70°C under load)
- [ ] Boot time test (< 2 minutes to ready state)

### Software QC
- [ ] Network connectivity (Ethernet and WiFi)
- [ ] Web interface accessible (`http://vernis.local`)
- [ ] IPFS daemon running (`sudo systemctl status vernis-ipfs`)
- [ ] Backend API running (`sudo systemctl status vernis-backend`)
- [ ] Test NFT download (upload test CSV)
- [ ] Display slideshow works
- [ ] Theme switching works
- [ ] Settings persistence

### Integration QC
- [ ] CSV upload and download works
- [ ] Progress bar displays correctly
- [ ] Worker selection functions
- [ ] IPFS gateway accessible
- [ ] Log files clean (no critical errors)

---

## 🚀 Production Deployment Workflows

### Workflow A: Retail Units (Consumer Market)
1. Master image on 32GB SD card
2. Custom retail packaging with:
   - Vernis Quick Start Guide (1 page)
   - WiFi setup card
   - Power adapter
3. QR code on device for support portal
4. 30-day return policy

### Workflow B: Enterprise/Gallery (B2B Market)
1. Master image on 64GB SD card or SSD
2. Pre-configured with client's collections
3. Custom branding applied
4. Remote management access enabled
5. On-site installation support

### Workflow C: Demo/Trade Show Units
1. Master image with demo collections
2. Auto-refresh every 24 hours
3. Locked settings (kiosk mode)
4. Prominent branding
5. Collect leads via QR code

---

## 🔐 Security Hardening for Production

### Essential Security Steps:

1. **Change Default Passwords**
```bash
# Change pi user password
sudo passwd pi

# Or disable pi user entirely
sudo usermod -L pi
```

2. **Enable Firewall**
```bash
sudo apt-get install ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp    # SSH (disable after setup)
sudo ufw allow 5000/tcp  # Vernis web interface
sudo ufw enable
```

3. **SSH Security**
```bash
# Disable password auth (use keys only)
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no

# Or disable SSH entirely for production
sudo systemctl disable ssh
```

4. **HTTPS (Optional)**
```bash
# Install Let's Encrypt certificate
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d vernis.yourdomain.com
```

5. **Auto-Updates** (Optional)
```bash
# Enable unattended security updates
sudo apt-get install unattended-upgrades
sudo dpkg-reconfigure unattended-upgrades
```

---

## 📊 Monitoring & Maintenance

### System Health Monitoring

Create `/opt/vernis/scripts/health-check.sh`:
```bash
#!/bin/bash
# Health check script

# Check services
systemctl is-active --quiet vernis-backend || echo "ALERT: Backend down"
systemctl is-active --quiet vernis-ipfs || echo "ALERT: IPFS down"

# Check disk space
USED=$(df -h /opt/vernis | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$USED" -gt 90 ]; then
    echo "ALERT: Disk usage at ${USED}%"
fi

# Check temperature (RPi specific)
if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
    TEMP=$(($(cat /sys/class/thermal/thermal_zone0/temp) / 1000))
    if [ "$TEMP" -gt 75 ]; then
        echo "ALERT: CPU temp ${TEMP}°C"
    fi
fi
```

Add to crontab:
```bash
# Run every hour
0 * * * * /opt/vernis/scripts/health-check.sh >> /var/log/vernis-health.log
```

---

## 🆘 Support & Troubleshooting

### Common Issues:

**Q: Web interface not accessible**
```bash
# Check backend service
sudo systemctl status vernis-backend

# Check firewall
sudo ufw status

# Restart service
sudo systemctl restart vernis-backend
```

**Q: Downloads not starting**
```bash
# Check IPFS daemon
sudo systemctl status vernis-ipfs

# Check IPFS gateway
curl http://localhost:8080/ipfs/QmHash

# Restart IPFS
sudo systemctl restart vernis-ipfs
```

**Q: Slow performance**
```bash
# Check CPU usage
top

# Check memory
free -h

# Check IPFS datastore size
du -sh /opt/vernis/.ipfs/datastore

# Run garbage collection
IPFS_PATH=/opt/vernis/.ipfs sudo -u vernis ipfs repo gc
```

### Factory Reset

Create `/opt/vernis/deploy/factory-reset.sh`:
```bash
#!/bin/bash
sudo systemctl stop vernis-backend vernis-ipfs
sudo rm -rf /opt/vernis/nfts/*
sudo rm -rf /opt/vernis/.ipfs/datastore/*
sudo rm -rf /opt/vernis/uploads/*
sudo systemctl start vernis-ipfs vernis-backend
```

---

## 📞 Next Steps

1. **Compliance & Certification**
   - CE marking (Europe)
   - FCC certification (USA)
   - RoHS compliance
   - Energy efficiency ratings

2. **Support Infrastructure**
   - Create support portal
   - Set up ticketing system
   - Prepare FAQ/Knowledge base
   - Train support team

3. **Distribution**
   - Partner with retailers
   - Set up e-commerce
   - Prepare marketing materials
   - Create demo videos

4. **Continuous Improvement**
   - Collect user feedback
   - Monitor analytics
   - Plan updates/features
   - Build community

---

## ✅ Production Readiness Checklist

- [ ] Master image created and tested
- [ ] QC process documented
- [ ] Support documentation complete
- [ ] Security hardening applied
- [ ] Packaging designed
- [ ] Pricing established
- [ ] Warranty terms defined
- [ ] Returns process documented
- [ ] Support team trained
- [ ] Marketing materials ready
- [ ] Legal reviewed (terms, privacy)
- [ ] Payment processing set up
- [ ] Inventory management system
- [ ] Shipping partners confirmed
- [ ] Launch date set

**Congratulations! You're ready to ship Vernis v3! 🎉**
