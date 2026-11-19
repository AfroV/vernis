#!/bin/bash
# BT PAN helper — manages the network bridge for Bluetooth PAN connections
# Run as root by bt-pan.service, from the root-owned copy
# /usr/local/lib/vernis/bt-pan-helper.sh (install-root-scripts.sh).
# Installed by setup-bluetooth-pan.sh.

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
