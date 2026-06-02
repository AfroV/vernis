# Vernis Update System

The Vernis update system supports two modes: **Development** and **Production**. You can easily switch between them using the settings page.

## 🎯 Overview

- **Development Mode**: Pull updates from your local development machine for testing
- **Production Mode**: Pull updates from GitHub repository and system packages

Both modes use the same UI: **Settings → System → Software Updates**

## 🛠️ Development Mode

### Setup

1. On your **development machine**, start the dev server:
   ```bash
   cd vernisv3
   ./start-dev.sh
   ```

2. On the **Pi**, open `http://vernis.local/settings-local.html`

3. Go to **System** section

4. Select **🛠️ Development** mode

5. Enter your dev machine IP:PORT (shown by `start-dev.sh`)
   - Example: `192.168.1.100:8080`

6. Click **Save Update Configuration**

### Testing Updates

1. Make code changes on your development machine

2. Go to **Software Updates** section

3. Click **Check for Updates**
   - It will check if your dev server is reachable

4. Click **Install Updates & Reboot**
   - Pulls latest files from dev server
   - Restarts services
   - Page auto-reloads in 5 seconds

### What Gets Updated (Dev Mode)

- All HTML/CSS files → `/var/www/vernis/`
- Backend `app.py` → `/opt/vernis/`
- Scripts → `/opt/vernis/scripts/`

Services automatically restart:
- `vernis-api.service` (Flask backend)
- `caddy` (web server)

## 🚀 Production Mode

### Setup

1. On the Pi, open `http://vernis.local/settings.html`

2. Go to **System** section

3. Select **🚀 Production** mode

4. Enter your GitHub repository:
   - Format: `username/repository`
   - Example: `yourusername/vernis`

5. Enter branch (default: `main`)

6. Click **Save Update Configuration**

### Installing Updates

1. Go to **Software Updates** section

2. Click **Check for Updates**
   - Checks for system package updates
   - Shows count of available updates

3. Click **Install Updates & Reboot**
   - Clones latest code from GitHub
   - Updates system packages (`apt upgrade`)
   - Reboots the Pi

### What Gets Updated (Production Mode)

- Latest code from GitHub repository
- System packages (security updates, etc.)
- Services restart
- **System reboots after completion**

## 🔄 Switching Modes

You can switch between modes anytime:

1. Open settings page
2. Go to **System → Update Mode**
3. Click **Development** or **Production**
4. Configure the settings for that mode
5. Click **Save Update Configuration**

The system remembers your settings for each mode, so switching back and forth is easy.

## 📝 Configuration File

The update configuration is stored in `/opt/vernis/update-config.json`:

```json
{
  "mode": "production",
  "dev_server": "192.168.1.100:8080",
  "github_repo": "yourusername/vernis",
  "github_branch": "main"
}
```

## 🎬 Typical Workflow

### During Development

1. Set mode to **Development**
2. Start dev server: `./start-dev.sh`
3. Make changes → Check for Updates → Install
4. Test on Pi
5. Repeat!

### For Production Deployment

1. Commit and push changes to GitHub
2. Switch to **Production** mode
3. Configure GitHub repo and branch
4. Check for Updates
5. Install Updates & Reboot
6. Pi pulls latest code and reboots with new version

## ⚠️ Important Notes

### Development Mode
- Only updates code files (not system packages)
- Services restart (2-3 second downtime)
- Page auto-reloads after update
- Both machines must be on same network

### Production Mode
- Updates both code AND system packages
- **System reboots** (1-2 minute downtime)
- Requires GitHub repository to be configured
- Good for deploying stable releases

## 🐛 Troubleshooting

### "Cannot connect to dev server"
- Verify dev server is running: `./start-dev.sh`
- Check firewall isn't blocking port 8080
- Confirm Pi and dev machine on same network
- Try pinging dev machine from Pi

### "Failed to clone repository"
- Check GitHub repo exists and is public (or use token for private)
- Verify branch name is correct
- Ensure Pi has internet connection

### "Update check timed out"
- Network may be slow
- Try again in a few moments
- Check Pi's internet connection

### Updates not appearing
- Hard refresh browser: Ctrl+Shift+R
- Check if services restarted: `sudo systemctl status vernis-api caddy`
- Verify files were updated: `ls -lt /var/www/vernis/`

## 💡 Tips

1. **Use descriptive commit messages** when pushing to GitHub - they help track what changed

2. **Test in dev mode first** before deploying to production

3. **Development mode is faster** - use it for rapid iteration during testing

4. **Production mode is safer** - only use for stable, tested code

5. **Keep your GitHub repo private** if your Vernis contains sensitive configurations

## 📚 Related Files

- `dev-server.py` - Development file server
- `start-dev.sh` - Convenient dev server starter
- `scripts/dev-update.sh` - Dev mode update script
- `scripts/github-update.sh` - Production mode update script
- `update-config.json` - Configuration file
