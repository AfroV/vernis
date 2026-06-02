#!/bin/bash
##############################################
# Vernis v3 - Disable SoftAP Fallback
# Stops the recovery AP and restores normal Wi-Fi
##############################################

echo "Stopping fallback AP..."

systemctl stop hostapd
systemctl stop dnsmasq
systemctl mask hostapd

# Restore normal DHCP on wlan0
ip addr flush dev wlan0
dhclient wlan0

echo "Fallback AP disabled. Reconnecting to Wi-Fi..."
