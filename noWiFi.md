Current Hotspot Trigger:
  vernis-ap-check.timer
    └── runs at: boot + 90s, then every 5 min
         └── enable-setup-ap.sh
              └── pings 8.8.8.8
                   └── if no internet → start hostapd

  Hotspot details:
  - SSID: Vernis-XXXXXXXX (last 8 digits of CPU serial)
  - Password: <ap-password>
  - IP: 192.168.50.1

  So now you have both running:
  ┌─────────┬───────────────────────┬────────────────────────────────┐
  │ Method  │        Trigger        │             Delay              │
  ├─────────┼───────────────────────┼────────────────────────────────┤
  │ BLE     │ wifi_monitor.py       │ ~90 sec (no WiFi)              │
  ├─────────┼───────────────────────┼────────────────────────────────┤
  │ Hotspot │ vernis-ap-check.timer │ 90 sec boot, then 5 min checks │
  └─────────┴───────────────────────┴────────────────────────────────┘
  They can coexist - BLE activates first for Chrome users, hotspot kicks in as fallback for Safari/Firefox users.