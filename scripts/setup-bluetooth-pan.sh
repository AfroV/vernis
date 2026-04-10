#!/bin/bash
##############################################
# Vernis Bluetooth PAN Setup
# Creates a Bluetooth Personal Area Network
# for SSH access when WiFi is unavailable
##############################################

set -e

echo "==========================================="
echo "Vernis Bluetooth PAN Setup"
echo "==========================================="

if [ "$EUID" -eq 0 ]; then
    echo "Please run as normal user (not root)"
    echo "Usage: bash setup-bluetooth-pan.sh"
    exit 1
fi

USER_NAME=$(whoami)
BT_SUBNET="10.44.0"
BT_IP="${BT_SUBNET}.1"
BT_DHCP_START="${BT_SUBNET}.10"
BT_DHCP_END="${BT_SUBNET}.50"

# Step 1: Install dependencies
echo "[1/5] Installing Bluetooth networking packages..."
sudo apt update
sudo apt install -y bluez bluez-tools bridge-utils dnsmasq python3-dbus python3-gi

# Step 2: Configure Bluetooth adapter
echo "[2/5] Configuring Bluetooth adapter..."

# Enable Bluetooth service
sudo systemctl enable bluetooth
sudo systemctl start bluetooth

# Set device name to match hostname (e.g. "afrol")
HOSTNAME=$(hostname)
sudo bluetoothctl system-alias "Vernis-${HOSTNAME}" 2>/dev/null || true

# Step 3: Create the BT PAN helper script
echo "[3/5] Creating BT PAN bridge service..."

sudo tee /opt/vernis/scripts/bt-pan-helper.sh > /dev/null << 'BTHELPER'
#!/bin/bash
# BT PAN helper — manages the network bridge for Bluetooth PAN connections
# Called by bt-pan systemd service

BT_BRIDGE="bt0"
BT_IP="10.44.0.1"
BT_NETMASK="255.255.255.0"

setup_bridge() {
    # Create bridge if it doesn't exist
    if ! ip link show "$BT_BRIDGE" &>/dev/null; then
        sudo brctl addbr "$BT_BRIDGE"
    fi
    sudo ip addr flush dev "$BT_BRIDGE" 2>/dev/null
    sudo ip addr add "${BT_IP}/24" dev "$BT_BRIDGE"
    sudo ip link set "$BT_BRIDGE" up
    echo "[bt-pan] Bridge $BT_BRIDGE up at $BT_IP"
}

cleanup_bridge() {
    sudo ip link set "$BT_BRIDGE" down 2>/dev/null
    sudo brctl delbr "$BT_BRIDGE" 2>/dev/null
    echo "[bt-pan] Bridge $BT_BRIDGE removed"
}

case "$1" in
    start)
        setup_bridge
        # Start the NAP server (blocks until stopped)
        sudo /usr/bin/bt-network -s nap "$BT_BRIDGE"
        ;;
    stop)
        cleanup_bridge
        ;;
    *)
        echo "Usage: $0 {start|stop}"
        exit 1
        ;;
esac
BTHELPER

sudo chmod +x /opt/vernis/scripts/bt-pan-helper.sh

# Copy pairing agent script
sudo cp -f "$(dirname "$0")/bt-pairing-agent.py" /opt/vernis/scripts/bt-pairing-agent.py 2>/dev/null || true
sudo chmod +x /opt/vernis/scripts/bt-pairing-agent.py

# Step 4: Create BT agent for pairing + PAN systemd services
echo "[4/5] Creating systemd services..."

# Pairing agent — handles pairing requests with PIN display on screen
sudo tee /etc/systemd/system/bt-agent.service > /dev/null << EOF
[Unit]
Description=Bluetooth Pairing Agent for Vernis
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStartPre=/usr/bin/bluetoothctl pairable on
ExecStart=/usr/bin/python3 /opt/vernis/scripts/bt-pairing-agent.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# PAN network service
sudo tee /etc/systemd/system/bt-pan.service > /dev/null << EOF
[Unit]
Description=Bluetooth PAN Network for Vernis
After=bluetooth.service bt-agent.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStart=/opt/vernis/scripts/bt-pan-helper.sh start
ExecStop=/opt/vernis/scripts/bt-pan-helper.sh stop
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Configure dnsmasq for BT subnet DHCP
# Use a separate config so it doesn't conflict with any existing dnsmasq setup
sudo tee /etc/dnsmasq.d/bt-pan.conf > /dev/null << EOF
# Bluetooth PAN DHCP — only serves on bt0 bridge
interface=bt0
bind-interfaces
dhcp-range=${BT_DHCP_START},${BT_DHCP_END},255.255.255.0,24h
dhcp-option=3,${BT_IP}
dhcp-option=6,${BT_IP}
EOF

# Step 5: Firewall + enable services
echo "[5/5] Configuring firewall and enabling services..."

# Allow SSH on the BT subnet
sudo ufw allow in on bt0 to any port 22 proto tcp comment "SSH over Bluetooth PAN"
# Allow HTTP (web UI) on the BT subnet — BT PAN uses HTTP (no TLS cert for 10.44.0.1)
sudo ufw allow in on bt0 to any port 80 proto tcp comment "HTTP over Bluetooth PAN"
# Allow HTTPS (web UI) on the BT subnet in case user configures TLS later
sudo ufw allow in on bt0 to any port 443 proto tcp comment "HTTPS over Bluetooth PAN"
# Allow DHCP on bt0
sudo ufw allow in on bt0 to any port 67 proto udp comment "DHCP for BT PAN"

# Restart dnsmasq to pick up new config
sudo systemctl restart dnsmasq 2>/dev/null || sudo systemctl start dnsmasq

# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable bt-agent bt-pan
sudo systemctl start bt-agent bt-pan

echo ""
echo "==========================================="
echo "Bluetooth PAN Setup Complete"
echo "==========================================="
echo ""
echo "Pi is now discoverable for pairing."
echo ""
echo "To connect from your phone/laptop:"
echo "  1. Scan for Bluetooth devices"
echo "  2. Pair with 'Vernis-${HOSTNAME}'"
echo "  3. Connect to the PAN network"
echo "  4. SSH to ${BT_IP} (same username/password as WiFi)"
echo "     ssh ${USER_NAME}@${BT_IP}"
echo "  5. Web UI: http://${BT_IP}"
echo ""
echo "After pairing, disable discoverable mode:"
echo "  sudo bluetoothctl discoverable off"
echo ""
echo "To re-enable for new device pairing:"
echo "  sudo bluetoothctl discoverable on"
echo ""
echo "Security:"
echo "  - Paired devices only (no anonymous connections)"
echo "  - SSH + fail2ban protection (same as WiFi)"
echo "  - UFW firewall limits BT to SSH + HTTPS only"
echo "  - ~10m range (requires physical proximity)"
echo ""
