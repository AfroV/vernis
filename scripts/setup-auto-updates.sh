#!/bin/bash
# Vernis - Setup automatic security updates (unattended-upgrades)
# Usage: sudo bash setup-auto-updates.sh [enable|disable|status]
# Default action: enable

set -e

ACTION="${1:-enable}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[auto-updates]${NC} $1"; }
warn() { echo -e "${YELLOW}[auto-updates]${NC} $1"; }
err() { echo -e "${RED}[auto-updates]${NC} $1"; }

# Check root
if [ "$(id -u)" -ne 0 ]; then
    err "Must be run as root (sudo)"
    exit 1
fi

STATUS_FILE="/opt/vernis/auto-update-config.json"

show_status() {
    if dpkg -l unattended-upgrades 2>/dev/null | grep -q '^ii'; then
        # Check if enabled in apt config
        if [ -f /etc/apt/apt.conf.d/20auto-upgrades ]; then
            if grep -q 'APT::Periodic::Unattended-Upgrade "1"' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null; then
                echo "enabled"
                return 0
            fi
        fi
        echo "disabled"
        return 0
    else
        echo "not_installed"
        return 0
    fi
}

enable_auto_updates() {
    log "Installing unattended-upgrades..."
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq unattended-upgrades apt-listchanges >/dev/null 2>&1

    log "Configuring security-only updates..."

    # Configure unattended-upgrades for security patches only
    cat > /etc/apt/apt.conf.d/50unattended-upgrades << 'UUCFG'
// Vernis: Security-only automatic updates
Unattended-Upgrade::Origins-Pattern {
    "origin=Debian,codename=${distro_codename},label=Debian-Security";
    "origin=Raspbian,codename=${distro_codename},label=Raspbian";
};

// Do NOT auto-remove unused dependencies (safety)
Unattended-Upgrade::Remove-Unused-Dependencies "false";

// Do NOT auto-remove new unused dependencies
Unattended-Upgrade::Remove-New-Unused-Dependencies "false";

// Auto-reboot at 4:00 AM if needed (kernel patches)
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";

// Log to syslog
Unattended-Upgrade::SyslogEnable "true";

// Mail not configured (headless device)
UUCFG

    # Enable periodic updates
    cat > /etc/apt/apt.conf.d/20auto-upgrades << 'AUTOCFG'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
AUTOCFG

    # Pin critical packages to prevent breakage
    log "Pinning critical packages (kernel, display drivers, chromium)..."
    cat > /etc/apt/preferences.d/vernis-pin-critical << 'PINCFG'
# Vernis: Pin critical packages to prevent auto-upgrade
# These should only be updated manually after testing

Package: linux-image-* linux-headers-* raspberrypi-kernel raspberrypi-bootloader
Pin: release *
Pin-Priority: -1

Package: chromium chromium-browser chromium-common
Pin: release *
Pin-Priority: -1

Package: labwc wlroots* libwlroots*
Pin: release *
Pin-Priority: -1
PINCFG

    # Save config
    mkdir -p /opt/vernis
    echo '{"enabled": true}' > "$STATUS_FILE"

    log "Auto security updates enabled (security-only, reboot at 4 AM if needed)"
    log "Pinned: kernel, chromium, labwc/wlroots (won't auto-update)"
}

disable_auto_updates() {
    log "Disabling automatic updates..."

    if [ -f /etc/apt/apt.conf.d/20auto-upgrades ]; then
        cat > /etc/apt/apt.conf.d/20auto-upgrades << 'AUTOCFG'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
AUTOCFG
    fi

    mkdir -p /opt/vernis
    echo '{"enabled": false}' > "$STATUS_FILE"

    log "Auto security updates disabled"
}

case "$ACTION" in
    enable)
        enable_auto_updates
        ;;
    disable)
        disable_auto_updates
        ;;
    status)
        show_status
        ;;
    *)
        err "Usage: $0 [enable|disable|status]"
        exit 1
        ;;
esac
