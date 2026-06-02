# Vernis Development Workflow

Quick guide for testing code changes on your Raspberry Pi during development.

## 🚀 Quick Start

### 1. Start the Dev Server (on your development machine)

```bash
cd /path/to/vernisv3
python3 dev-server.py
```

This starts a file server on port 8080 (customize with `python3 dev-server.py 9000`)

### 2. Get Your Dev Machine's IP Address

```bash
# macOS/Linux
ifconfig | grep "inet "

# Windows
ipconfig
```

Look for your local network IP (usually 192.168.x.x or 10.x.x.x)

### 3. Update the Pi

**Option A: Using the Web UI** (Recommended)
1. Open `http://vernis.local/settings-local.html` on the Pi
2. Scroll to "🛠️ Developer Tools"
3. Enter your dev machine IP and port (e.g., `192.168.1.100:8080`)
4. Click "Pull Development Update"
5. Wait 5 seconds for services to restart

**Option B: Using SSH**
```bash
ssh pi@vernis.local
sudo bash /opt/vernis/scripts/dev-update.sh 192.168.1.100:8080
```

## 📁 What Gets Updated

The dev update script syncs these files from your dev machine to the Pi:

- **Web UI**: All HTML, CSS, JS files → `/var/www/vernis/`
- **Backend**: `backend/app.py` → `/opt/vernis/app.py`
- **Scripts**: Files in `scripts/` → `/opt/vernis/scripts/`

Services automatically restart after update:
- `vernis-api.service` (Flask backend)
- `caddy` (web server)

## 🔄 Development Cycle

1. **Edit code** on your dev machine
2. **Start dev server** (if not already running)
3. **Trigger update** from Pi's settings page or SSH
4. **Test changes** at `http://vernis.local`
5. Repeat!

## 🎯 Pro Tips

### Persistent Dev Server Address
The settings page remembers your dev server address in localStorage, so you only need to enter it once.

### Watch for Errors
Check the dev server terminal output to see which files the Pi is downloading.

### Check Logs on Pi
```bash
# View API logs
sudo journalctl -u vernis-api.service -f

# View Caddy logs
sudo journalctl -u caddy -f
```

### Quick File Check
After updating, verify files were copied:
```bash
ls -lh /var/www/vernis/  # Web files
ls -lh /opt/vernis/      # Backend & scripts
```

## ⚠️ Important Notes

- **Only for local development**: This workflow is for testing on your local network
- **Services restart**: Expect a 2-3 second service restart during updates
- **Network required**: Both machines must be on the same network
- **Sudo access**: The update script runs with sudo to modify system files

## 🐛 Troubleshooting

### "Failed to connect to dev server"
- Verify dev server is running: `python3 dev-server.py`
- Check firewall isn't blocking port 8080
- Confirm Pi and dev machine are on same network
- Try pinging: `ping YOUR_DEV_IP` from Pi

### "Permission denied" errors
- Run update script with sudo: `sudo bash dev-update.sh ...`
- Or use the web UI which handles sudo automatically

### Changes not appearing
- Hard refresh browser: Ctrl+Shift+R (Cmd+Shift+R on Mac)
- Check if services restarted: `sudo systemctl status vernis-api caddy`
- Verify files were updated: `ls -lt /var/www/vernis/`

### Dev server not accessible
- Make sure you're using the correct IP address
- Try accessing from browser: `http://YOUR_DEV_IP:8080`
- Check if another service is using port 8080

## 📝 Example Session

```bash
# On your dev machine (macOS/Linux)
$ cd ~/Projects/vernisv3
$ python3 dev-server.py

🚀 Vernis Development File Server
========================================
Serving files from: /Users/you/Projects/vernisv3
Server running at: http://0.0.0.0:8080

# On the Pi (via SSH or web UI)
$ sudo bash /opt/vernis/scripts/dev-update.sh 192.168.1.100:8080

==========================================
Vernis v3 - Development Update
==========================================
Fetching from: http://192.168.1.100:8080

[1/6] Downloading web files...
✅ Web files downloaded
[2/6] Downloading backend...
✅ Backend downloaded
[3/6] Downloading scripts...
✅ Scripts downloaded
[4/6] Installing updates...
✅ Web files installed
✅ Backend installed
✅ Scripts installed
[5/6] Restarting services...
✅ Services restarted
[6/6] Cleaning up...
✅ Cleanup complete

==========================================
✅ Development Update Complete!
==========================================
```

## 🔒 Security Note

This development workflow is intended for **local network testing only**. Never expose the dev server to the public internet without authentication.

For production deployments, use the standard `install.sh` or manual deployment methods.
