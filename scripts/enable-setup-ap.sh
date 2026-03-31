#!/bin/bash
##############################################
# Vernis v3 - Wi-Fi SoftAP Fallback
# Creates a recovery AP if internet is unavailable
# Run on boot via systemd timer
##############################################

set -e

# Wait for network to initialize
sleep 15

# Check if we have internet connectivity
if ping -c 1 -W 5 8.8.8.8 &> /dev/null; then
    echo "Internet connection OK, no fallback AP needed"
    # Stop AP if it's running
    systemctl is-active --quiet hostapd && systemctl stop hostapd
    systemctl is-active --quiet dnsmasq && systemctl stop dnsmasq
    systemctl is-active --quiet vernis-bluetooth && systemctl stop vernis-bluetooth
    exit 0
fi

echo "No internet connection detected. Starting fallback AP..."

# Get unique identifier from CPU serial
SERIAL=$(cat /proc/cpuinfo | grep Serial | cut -d' ' -f2 | cut -c9-16)
SSID="Vernis-${SERIAL}"
PASS="vernis2025"
INTERFACE="wlan0"

# Create hostapd configuration
cat > /etc/hostapd/hostapd.conf <<EOF
interface=${INTERFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${PASS}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Create dnsmasq configuration
cat > /etc/dnsmasq.conf <<EOF
interface=${INTERFACE}
dhcp-range=192.168.50.10,192.168.50.50,255.255.255.0,24h
domain=local
address=/vernis.local/192.168.50.1
EOF

# Configure static IP for AP
ip addr flush dev ${INTERFACE}
ip addr add 192.168.50.1/24 dev ${INTERFACE}
ip link set ${INTERFACE} up

# Enable IP forwarding (optional, for internet sharing if available)
echo 1 > /proc/sys/net/ipv4/ip_forward

# Start services
systemctl unmask hostapd
systemctl start hostapd
systemctl start dnsmasq
systemctl start vernis-bluetooth

echo "=========================================="
echo "Fallback AP Started!"
echo "SSID: ${SSID}"
echo "Password: ${PASS}"
echo "Access Vernis at: http://vernis.local or http://192.168.50.1"
echo "=========================================="
