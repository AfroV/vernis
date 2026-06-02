#!/bin/bash
##############################################
# Vernis Screen Watchdog
# Monitors Chromium and restarts if frozen
# Only useful on v2 with built-in screen
##############################################

while true; do
    sleep 300  # Check every 5 minutes

    # Check if chromium is running
    if ! pgrep -x "chromium-browse" > /dev/null; then
        echo "Chromium not running, restarting X session..."
        sudo systemctl restart lightdm
    fi

    # Check if X server is responsive
    if ! DISPLAY=:0 xdpyinfo &> /dev/null; then
        echo "[Watchdog] Vernis Gallery frozen! Restarting Chromium..."
        sudo systemctl restart lightdm
    fi
done
