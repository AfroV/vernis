# Vernis Update Router (offline hotspot)

Turns a **spare Pi** into a self-contained, **offline** update station so the
other Vernis units can be updated without hotel/public WiFi or internet.

It does two things on first boot:

1. **WiFi hotspot** `VernisAP` (NetworkManager AP mode) at `10.42.0.1`,
   handing out DHCP to clients.
2. **HTTP server** on `:8080` serving the Vernis update package at
   `http://10.42.0.1:8080/vernis-update.tar.gz`.

## Build the card (from your Mac)

1. Flash Raspberry Pi OS with Raspberry Pi Imager **with customization**
   (set username/password, enable SSH). This produces a cloud-init card
   (`user-data`, `network-config`, `meta-data` on the boot partition).
2. Build the update package:
   ```bash
   bash scripts/create-update-package.sh
   cp vernis-update-*.tar.gz /Volumes/bootfs/vernis-update.tar.gz
   ```
3. Apply the provisioning:
   - **Replace** `/Volumes/bootfs/network-config` with
     [`cloud-init-network-config.yaml`](cloud-init-network-config.yaml)
     (frees `wlan0` for AP mode).
   - **Append** [`cloud-init-user-data-snippet.yaml`](cloud-init-user-data-snippet.yaml)
     to the end of `/Volumes/bootfs/user-data` (keep the existing keys).
   - In the appended block, set a **strong** AP password (replace `<AP_PASSWORD>`,
     >=12 chars). The production units share this LAN, so the runcmd guard
     refuses to start the hotspot with a default/weak PSK. The package server
     binds to `10.42.0.1` only, and no wired uplink is configured.
4. Eject, boot the Pi. After ~1–2 min `VernisAP` appears.

> macOS can only write the FAT32 boot partition, not the ext4 rootfs — that is
> why setup is done via cloud-init `write_files` + `runcmd` rather than copying
> files into `/opt` directly.

## Update the other units

On each Vernis: **Settings → WiFi → join `VernisAP`**. Then from a machine on
`VernisAP` (your Mac, or the router itself), per unit:

```bash
PW='<unit-password>'
for N in 1 2 3 4 5 6 7; do
  U="vernis$N"; IP="vernis$N.local"
  sshpass -p "$PW" ssh -o StrictHostKeyChecking=no "$U@$IP" \
    "echo '$PW' | sudo -S bash -c 'curl -fsSL http://10.42.0.1:8080/vernis-update.tar.gz -o /tmp/v.tar.gz && bash /opt/vernis/scripts/updater.sh /tmp/v.tar.gz'"
done
```

`updater.sh` backs up, applies web/backend/scripts, restarts services, reboots.

## Refresh the served package later

Rebuild and drop a new tarball on the router:
```bash
bash scripts/create-update-package.sh
scp vernis-update-*.tar.gz w2vernis2@10.42.0.1:/tmp/v.tar.gz
ssh w2vernis2@10.42.0.1 'sudo cp /tmp/v.tar.gz /opt/update-router/www/vernis-update.tar.gz'
```
