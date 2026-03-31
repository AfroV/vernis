#!/usr/bin/env python3
"""
WiFi Monitor for Vernis
Monitors WiFi connection and starts BLE provisioning when disconnected.
"""

import subprocess
import time
import os
import sys
import signal
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('wifi_monitor')

BLE_SERVICE = 'vernis-ble.service'
CHECK_INTERVAL = 30  # seconds between checks
STARTUP_DELAY = 60   # seconds to wait after boot before first check
NO_WIFI_THRESHOLD = 3  # number of consecutive failures before starting BLE

class WiFiMonitor:
    def __init__(self):
        self.running = True
        self.consecutive_failures = 0
        self.ble_active = False

    def is_wifi_connected(self):
        """Check if WiFi is connected to an access point."""
        try:
            # Check if wlan0 has an IP address
            result = subprocess.run(
                ['ip', 'addr', 'show', 'wlan0'],
                capture_output=True, text=True, timeout=10
            )

            if 'inet ' in result.stdout:
                # Has IP address, check if we can reach the gateway
                gw_result = subprocess.run(
                    ['ip', 'route', 'show', 'default'],
                    capture_output=True, text=True, timeout=10
                )

                if gw_result.stdout.strip():
                    # Has default route, try to ping gateway
                    gateway = gw_result.stdout.split()[2]
                    ping_result = subprocess.run(
                        ['ping', '-c', '1', '-W', '3', gateway],
                        capture_output=True, timeout=10
                    )
                    return ping_result.returncode == 0

            return False

        except Exception as e:
            logger.error(f'Error checking WiFi: {e}')
            return False

    def get_current_ssid(self):
        """Get the currently connected SSID."""
        try:
            result = subprocess.run(
                ['iwgetid', '-r'],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except:
            return None

    def start_ble_provisioning(self):
        """Start the BLE provisioning service."""
        if self.ble_active:
            logger.info('BLE already active')
            return

        logger.info('Starting BLE provisioning...')
        try:
            subprocess.run(
                ['sudo', 'systemctl', 'start', BLE_SERVICE],
                check=True, timeout=30
            )
            self.ble_active = True
            logger.info('BLE provisioning started')
        except Exception as e:
            logger.error(f'Failed to start BLE: {e}')

    def stop_ble_provisioning(self):
        """Stop the BLE provisioning service."""
        if not self.ble_active:
            return

        logger.info('Stopping BLE provisioning...')
        try:
            subprocess.run(
                ['sudo', 'systemctl', 'stop', BLE_SERVICE],
                capture_output=True, timeout=30
            )
            self.ble_active = False
            logger.info('BLE provisioning stopped')
        except Exception as e:
            logger.error(f'Failed to stop BLE: {e}')

    def check_ble_status(self):
        """Check if BLE service is actually running."""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', BLE_SERVICE],
                capture_output=True, text=True, timeout=10
            )
            self.ble_active = result.stdout.strip() == 'active'
        except:
            pass

    def run(self):
        """Main monitoring loop."""
        logger.info('WiFi Monitor starting...')
        logger.info(f'Waiting {STARTUP_DELAY}s for system startup...')

        # Wait for system to fully boot
        time.sleep(STARTUP_DELAY)

        logger.info('Beginning WiFi monitoring')

        while self.running:
            try:
                self.check_ble_status()

                if self.is_wifi_connected():
                    ssid = self.get_current_ssid()
                    logger.debug(f'WiFi connected: {ssid}')
                    self.consecutive_failures = 0

                    # If BLE is running and WiFi is connected, stop BLE
                    if self.ble_active:
                        logger.info('WiFi restored, stopping BLE provisioning')
                        self.stop_ble_provisioning()
                else:
                    self.consecutive_failures += 1
                    logger.warning(f'No WiFi connection ({self.consecutive_failures}/{NO_WIFI_THRESHOLD})')

                    # Start BLE after threshold failures
                    if self.consecutive_failures >= NO_WIFI_THRESHOLD and not self.ble_active:
                        logger.info('WiFi unavailable, starting BLE provisioning')
                        self.start_ble_provisioning()

                time.sleep(CHECK_INTERVAL)

            except Exception as e:
                logger.error(f'Monitor error: {e}')
                time.sleep(CHECK_INTERVAL)

    def shutdown(self, signum, frame):
        """Handle shutdown signal."""
        logger.info('Shutting down WiFi monitor...')
        self.running = False
        self.stop_ble_provisioning()
        sys.exit(0)


def main():
    monitor = WiFiMonitor()

    # Handle shutdown signals
    signal.signal(signal.SIGINT, monitor.shutdown)
    signal.signal(signal.SIGTERM, monitor.shutdown)

    monitor.run()


if __name__ == '__main__':
    main()
