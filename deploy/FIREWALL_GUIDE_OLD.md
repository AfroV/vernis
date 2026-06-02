# Vernis v3 - Firewall Configuration Guide

## 🔒 Default Firewall Setup

Vernis automatically configures UFW (Uncomplicated Firewall) during first boot.

### Default Open Ports

| Port | Service | Purpose |
|------|---------|---------|
| 22 | SSH | Remote administration (disable after setup) |
| 5000 | HTTP | Vernis web interface |
| 5353 | mDNS | vernis.local discovery |

### Default Closed Ports

| Port | Service | Why Closed |
|------|---------|------------|
| 8080 | IPFS Gateway | Bound to localhost only, not exposed |
| 5001 | IPFS API | Bound to localhost only, not exposed |

---

## 🛡️ Firewall Management Commands

### Check Firewall Status
```bash
sudo ufw status verbose
```

### View All Rules
```bash
sudo ufw status numbered
```

### Enable/Disable Firewall
```bash
# Enable
sudo ufw enable

# Disable (not recommended)
sudo ufw disable
```

---

## 🔧 Common Firewall Tasks

### 1. Disable SSH After Setup (Recommended for Production)
```bash
# Remove SSH rule
sudo ufw delete allow 22/tcp

# Or disable SSH service entirely
sudo systemctl disable ssh
sudo systemctl stop ssh
```

### 2. Add Custom Port
```bash
# Example: Allow port 8080 for external IPFS gateway
sudo ufw allow 8080/tcp comment 'IPFS Gateway'
```

### 3. Allow From Specific IP
```bash
# Only allow SSH from specific IP
sudo ufw delete allow 22/tcp
sudo ufw allow from 192.168.1.100 to any port 22 proto tcp
```

### 4. Block Specific IP
```bash
sudo ufw deny from 192.168.1.50
```

### 5. Rate Limiting (DDoS Protection)
```bash
# Limit SSH connections
sudo ufw limit 22/tcp
```

---

## 🌐 Network Access Scenarios

### Scenario 1: Local Network Only (Default)
**Use case:** Home gallery, private collection

**Configuration:**
- Firewall: Enabled
- Ports: 5000, 22 (SSH optional)
- Access: Local network only (192.168.x.x)

```bash
# Already configured by default
sudo ufw status
```

### Scenario 2: Public Internet Access
**Use case:** Share with friends, remote access

**Configuration:**
- Firewall: Enabled
- HTTPS: Required (use reverse proxy)
- Port forwarding: 443 → 5000

```bash
# Install nginx for HTTPS
sudo apt-get install nginx certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot --nginx -d vernis.yourdomain.com

# Allow HTTPS
sudo ufw allow 443/tcp comment 'HTTPS'

# Close direct HTTP access
sudo ufw delete allow 5000/tcp
```

### Scenario 3: Demo/Kiosk Mode (Locked Down)
**Use case:** Trade show, gallery installation

**Configuration:**
- Firewall: Enabled
- SSH: Disabled
- Read-only: Optional

```bash
# Remove SSH
sudo ufw delete allow 22/tcp
sudo systemctl disable ssh

# Only allow web interface
sudo ufw status  # Should only show port 5000
```

### Scenario 4: Development/Testing
**Use case:** Active development

**Configuration:**
- Firewall: Disabled temporarily
- SSH: Enabled
- All ports: Open

```bash
# Disable firewall (development only!)
sudo ufw disable

# Re-enable when done
sudo ufw enable
```

---

## 🔐 Security Best Practices

### 1. Change Default Passwords
```bash
# Change pi user password
sudo passwd pi

# Change root password
sudo passwd root
```

### 2. SSH Key-Based Authentication
```bash
# On your local machine
ssh-keygen -t ed25519 -C "vernis-admin"

# Copy to Vernis
ssh-copy-id pi@vernis.local

# Disable password auth
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no

# Restart SSH
sudo systemctl restart ssh
```

### 3. Enable Automatic Security Updates
```bash
sudo apt-get install unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

### 4. Monitor Failed Login Attempts
```bash
# Install fail2ban
sudo apt-get install fail2ban

# Configure for SSH
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 5. Regular Firewall Audits
```bash
# Check current rules
sudo ufw status numbered

# Review logs
sudo tail -f /var/log/ufw.log
```

---

## 🚨 Troubleshooting

### Can't Access Web Interface After Firewall Setup
```bash
# Check if port 5000 is allowed
sudo ufw status | grep 5000

# If not, add it
sudo ufw allow 5000/tcp comment 'Vernis Web Interface'
```

### Locked Out of SSH
```bash
# If you have physical access:
# 1. Connect keyboard and monitor
# 2. Login directly
# 3. Add SSH rule:
sudo ufw allow 22/tcp

# If no physical access and port 5000 is open:
# SSH is required for remote access
```

### vernis.local Not Working
```bash
# Check if mDNS port is allowed
sudo ufw status | grep 5353

# Add if missing
sudo ufw allow 5353/udp comment 'mDNS'

# Restart avahi
sudo systemctl restart avahi-daemon
```

### Firewall Blocking IPFS
```bash
# IPFS gateway and API are localhost-only by default
# No firewall rules needed
# To expose IPFS externally (not recommended):
sudo ufw allow 8080/tcp comment 'IPFS Gateway'
sudo ufw allow 5001/tcp comment 'IPFS API'

# Update IPFS config to listen on all interfaces
IPFS_PATH=/opt/vernis/.ipfs ipfs config Addresses.Gateway /ip4/0.0.0.0/tcp/8080
```

---

## 📊 Firewall Logs

### View Recent Blocks
```bash
sudo tail -f /var/log/ufw.log
```

### Search for Specific IP
```bash
sudo grep "192.168.1.100" /var/log/ufw.log
```

### Count Blocked Attempts
```bash
sudo grep "BLOCK" /var/log/ufw.log | wc -l
```

---

## 🔄 Reset Firewall to Defaults

### Complete Reset
```bash
# Reset UFW
sudo ufw --force reset

# Reconfigure
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 5000/tcp comment 'Vernis Web Interface'
sudo ufw allow 5353/udp comment 'mDNS'
sudo ufw --force enable
```

### Restore Vernis Defaults
```bash
# Re-run setup script firewall section
cd /opt/vernis/deploy
# Extract and run just the firewall configuration section
```

---

## 📞 Support

For firewall issues:
1. Check status: `sudo ufw status verbose`
2. View logs: `sudo tail -f /var/log/ufw.log`
3. Test connectivity: `curl http://localhost:5000`
4. Reset if needed (see above)

**Remember:** Always keep at least one access method (web or SSH) before closing ports!
