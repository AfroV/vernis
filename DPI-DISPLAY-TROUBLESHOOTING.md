# Waveshare 4inch DPI LCD (C) — Display Issues & Fixes

This document covers all known display issues with the Waveshare 4inch DPI LCD (C) on Raspberry Pi, their root causes, and how to fix them.

## How the DPI Display Works

The DPI (Display Parallel Interface) uses **GPIO pins directly** to send pixel data to the LCD. Unlike HDMI which uses a dedicated controller, DPI turns GPIO pins into a parallel data bus.

**GPIO pins used by DPI (RGB666, 18-bit color):**
- Data: GPIO 0-9, 12-17, 20-25 (18 data lines)
- Clock: GPIO 19 (pixel clock)
- Sync: GPIO 10 (HSYNC), GPIO 11 (VSYNC)
- Enable: GPIO 18 is listed as DPI_D14 alternate function

**GPIO pins NOT used by DPI (safe for fan/LED/sensors):**
GPIO 26, 27 — and ONLY these are guaranteed safe. GPIO 18/19 have DPI alternate functions and may be claimed.

**Display specs:** RGB666 (262K colors), 720x720, 60Hz

## Issue 1: Dim Screen / No Backlight / Faint Image Visible

### Symptoms
- Screen appears very dim, almost off
- You can faintly see the UI (like a dim QR code) if you look closely
- Stripes or color artifacts visible

### Root Cause
The `dpi-backlight.service` systemd unit sets GPIO 18 as a plain output LOW (`pinctrl set 18 op dl`). GPIO 18 is **also used by the DPI driver as data pin DPI_D14**. When the service forces it LOW:
- One bit of every pixel's color data is stuck at 0
- The display shows corrupted, dim output
- The kernel logs `gpio-backlight rpi_backlight: error -EBUSY` because the DPI driver already claimed the pin

### Diagnosis
```bash
# Check if the service exists and what it does
systemctl status dpi-backlight
# Look for: ExecStart=/usr/bin/pinctrl set 18 op dl  ← THIS IS THE BUG

# Check kernel log for the conflict
dmesg | grep -i "backlight\|EBUSY"
# Look for: gpio-backlight rpi_backlight: error -EBUSY

# Check GPIO 18 state
pinctrl get 18
# If it shows "op dl" = problem. Should show DPI alternate function.
```

### Fix
```bash
# 1. Disable the broken service permanently
sudo systemctl stop dpi-backlight
sudo systemctl disable dpi-backlight

# 2. Reboot to let DPI driver reclaim GPIO 18
sudo reboot
```

### Why This Keeps Happening
The `dpi-backlight.service` was created during initial Waveshare display setup. The Waveshare overlay (`waveshare-4dpic-4b`) includes a `gpio-backlight` device tree node for GPIO 18, but this conflicts with the `vc4-kms-DPI-4inch` overlay which uses GPIO 18 for DPI_D14. The kernel driver fails (EBUSY), so someone created a systemd service as a workaround — but used `dl` (drive LOW = OFF) instead of `dh` (drive HIGH = ON). Even `dh` would be wrong because GPIO 18 must remain under DPI driver control for pixel data.

**The correct fix is: do NOT touch GPIO 18 at all. The backlight on the Waveshare 4" DPI LCD (C) is always-on when powered via the ribbon cable. No GPIO backlight control is needed.**

### Prevention
- **NEVER** create a service that sets GPIO 18 on DPI-equipped Pis
- **NEVER** use `pinctrl` to manually set GPIO 18 when DPI is active
- If the display setup script creates `dpi-backlight.service`, immediately disable it
- Add to install script: `systemctl disable dpi-backlight 2>/dev/null`

---

## Issue 2: Green Tint / Dark Stripes / Color Corruption

### Symptoms
- Greenish tint across the entire display
- Dark horizontal or vertical stripes
- Colors look wrong

### Root Cause
A GPIO pin used by DPI for color data has been hijacked by another driver. Previously, `gpio-fan` was configured on **GPIO 14**, which is DPI data pin DPI_D10.

### Diagnosis
```bash
# Check config.txt for gpio-fan pin
grep gpio-fan /boot/firmware/config.txt
# If gpiopin=14 (or any pin in 0-9, 12-17, 20-25) = problem

# Check all overlays using DPI-range GPIOs
grep -i "gpio\|pin" /boot/firmware/config.txt
```

### Fix
Move gpio-fan to a DPI-safe pin:
```bash
# In /boot/firmware/config.txt, change:
dtoverlay=gpio-fan,gpiopin=14,temp=80000
# To:
dtoverlay=gpio-fan,gpiopin=26,temp=80000
```
Then physically rewire the fan to GPIO 26 and reboot.

---

## Issue 3: Scan Lines / Signal Artifacts

### Symptoms
- Visible horizontal scan lines across the display
- Flickering or unstable image
- Worse at certain brightness levels

### Root Cause
`over_voltage` in config.txt is too low. The DPI interface is sensitive to voltage because GPIO signal levels must be clean for the parallel data bus. Below `over_voltage=4`, the signal edges are too soft, causing timing errors visible as scan lines.

### Fix
```bash
# In /boot/firmware/config.txt, ensure:
over_voltage=4    # minimum for DPI — 0.91V above nominal

# ALL CPU profiles must use over_voltage >= 4
# eco=4, balanced=4, performance=4, maximum=4
```

**Do NOT set over_voltage higher than 4 for overclocking** — values of 6+ also cause display artifacts (dim patches, color shifts). The DPI signal is sensitive in both directions.

---

## Issue 4: Overclocking Causes Display Problems

### Symptoms
- Lines on screen after changing CPU/GPU frequency
- One side of screen dim
- Colors not as sharp

### Root Cause
Changing `gpu_freq` directly affects the pixel clock divider chain. The DPI display runs at exactly 60MHz pixel clock (derived from VCO 1200MHz → /10 → /2). Changing GPU frequency shifts the VCO, and the dividers may not produce a clean 60MHz.

Changing `arm_freq` and `over_voltage` together can also shift GPIO signal characteristics.

### Fix
**Do not overclock Pis with DPI displays.** The display is hardwired to GPIO pins and extremely sensitive to clock/voltage changes. The stock balanced profile is the safe configuration:
```
arm_freq=1500
gpu_freq=600
over_voltage=4
arm_boost=0
```

---

## Issue 5: Backlight On But No Image

### Symptoms
- Screen backlight is on (white/bright) but no image displayed
- Or screen is completely black with backlight

### Root Cause
DPI overlay configuration issue. Common causes:
- `dtoverlay=vc4-fkms-v3d` present (conflicts with KMS DPI)
- Wrong overlay combination
- Missing overlay files in `/boot/overlays/`

### Fix
Ensure config.txt has:
```
dtoverlay=vc4-kms-v3d          # NOT fkms
dtoverlay=vc4-kms-DPI-4inch
dtoverlay=waveshare-4dpic-4b
dtoverlay=waveshare-touch-4dpi
# waveshare-4dpi must be COMMENTED OUT (conflicts with vc4-kms-DPI-4inch)
```

---

## Issue 6: Touch Not Aligned After Rotation

### Symptoms
- Touch input doesn't match display position after rotating the display

### Root Cause
labwc (the Wayland compositor) does NOT auto-rotate touch input to match display transforms. The touch calibration matrix must be updated manually.

### Fix
The `display-output.sh` script must pass the actual rotation value to `update_touch_config`, which writes a `calibrationMatrix` to labwc's `rc.xml`.

---

## Quick Reference: Config.txt for DPI Display

```ini
# Required overlays
dtoverlay=vc4-kms-v3d
dtoverlay=vc4-kms-DPI-4inch
dtoverlay=waveshare-4dpic-4b
#dtoverlay=waveshare-4dpi      # DISABLED — conflicts
dtoverlay=waveshare-touch-4dpi

# Required voltage
over_voltage=4                  # minimum for clean DPI signal

# Fan on safe GPIO
dtoverlay=gpio-fan,gpiopin=26,temp=80000

# Do NOT have:
# - dpi-backlight.service enabled
# - gpio-fan on pins 0-9, 12-17, 20-25
# - pwm-2chan overlay (conflicts with GPIO 18)
# - over_voltage < 4 or > 4 with overclocking
# - dtoverlay=vc4-fkms-v3d (use vc4-kms-v3d)
```

## Affected Devices
- **afrol** (Pi 28, 10.0.0.28) — Pi 5, DPI display, fixed 2026-03-15
- **afrom** (Pi 39, 10.0.0.39) — Pi 4, DPI display, fixed 2026-03-15
- **afromini** (10.2.0.8) — unknown if DPI, check before applying
