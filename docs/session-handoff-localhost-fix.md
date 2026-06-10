# Session Handoff — localhost→127.0.0.1 fleet fix

**Last touched:** 2026-05-30
**Reason for write:** session context limit; resume from here

## TL;DR for next session

Chromium 146 auto-upgrades `http://localhost` → `https://localhost`, breaking
the kiosk on devices where HTTPS is disabled. Fix is to navigate to
`http://127.0.0.1` instead. Source repo is fully patched. Two devices
deployed. The rest need deployment when reachable.

## Source repo state (all committed-ready, not pushed by me)

| File | Change |
|---|---|
| `audit-package/scripts/kiosk-launcher.sh` + `scripts/kiosk-launcher.sh` | `exec chromium` URL: `http://127.0.0.1/$START_PAGE` |
| `audit-package/scripts/watchdog.sh` + `scripts/watchdog.sh` | recovery navigate URL + tab-finding logic accepts both `localhost` and `127.0.0.1` |
| `audit-package/backend/app.py` + `backend/app.py` | 8 changes: `/api/https` GET check uses `("tls " + CERT_PATH) in content` (fixes false-positive on `:443` in comments); 7 kiosk-navigation URLs switched from `localhost` → `127.0.0.1` (generator/lab, easter egg, remote start/stop gallery, remote nav, Bluetooth pairing redirect, timed return) |
| `tools/deploy-kiosk-and-https-fix.sh` | New fleet deploy script; idempotent; backs up originals once; `pkill` detached so SSH doesn't drop; verify timeout 60s |

## Per-device state

| Device | IP | Reachable from my mac | Deployed | Tab URL | Notes |
|---|---|---|---|---|---|
| **vernis2** | 10.0.0.41 | ✅ yes | ✅ all fixes | `http://127.0.0.1/gallery.html` | also has profile backup at `/home/vernis2/.config/chromium.bak.1779663274` — safe to `rm -rf` next visit |
| **afrol** | 10.0.0.28 | ✅ yes | ✅ all fixes | `http://127.0.0.1/index.html` | chromium 142 (older), bug still applied via HSTS |
| **afrom** | 10.0.0.39 | ❌ 100% packet loss | not yet | unknown | user said it's online but ping fails; investigate IP/network/mDNS — maybe IP changed |
| afroz | 10.0.0.34 | ❌ offline | not yet | — | |
| afromini | 10.2.0.8 | ❌ offline | not yet | — | |
| vernis1 | 10.0.0.40 | ❌ offline | not yet | — | |
| vernis3 | 10.0.0.43 | ❌ offline | not yet | — | |
| vernis4 | 10.0.0.44 | ❌ offline | not yet | — | |
| vernis5 | 10.0.0.45 | ❌ offline | not yet | — | |
| vernis6 | 10.0.0.42 | ❌ offline | not yet | — | |
| vernis7 | 10.0.0.46 | ❌ offline | not yet | — | |

## To resume — single command

```bash
bash tools/deploy-kiosk-and-https-fix.sh
```

That hits all 11 devices; skips offline; verifies each. Add device names as
args (e.g. `… afrom afroz`) to scope.

Per-device verification command (no deploy):
```bash
ssh vernisN@<ip> "
  pgrep -af /usr/lib/chromium/chromium | head -1 | tr ' ' '\n' | grep -E '^http' | head -1
  curl -s http://localhost:5000/api/https
  grep -c '127.0.0.1/' /opt/vernis/app.py        # expect ≥5 if patched
  grep -c '127.0.0.1/\$START_PAGE' /opt/vernis/scripts/kiosk-launcher.sh  # expect 1
"
```

## Side findings (not blocking, but worth noting)

1. **afrom IP mystery** — user said afrom + afrol both online (2026-05-25). afrol pings fine, afrom doesn't. Maybe afrom rebooted onto a new lease. Need fresh `arp -a` or device console check.

2. **Bluetooth + PIN modes confirmed working as expected.** Pi kiosk never gated (127.0.0.1 bypass at `audit-package/backend/app.py:582`). Remote PC/phone: Mode A/B always allow; Mode C gates `POST /api/bluetooth/{pairing,discoverable,unpair}` because they classify as `control`.

3. **`/api/https` false-positive** was fixed but afrol still reports `has_cert:true` — leftover `/etc/caddy/vernis.crt` from a past HTTPS-enable. Cosmetic; no behavior impact.

4. **Backups on deployed devices** (cleanup someday, not urgent):
   - `/opt/vernis/scripts/kiosk-launcher.sh.pre-localhost-fix`
   - `/opt/vernis/scripts/watchdog.sh.pre-localhost-fix`
   - `/opt/vernis/app.py.pre-https-fix`
   - vernis2: `/home/vernis2/.config/chromium.bak.1779663274`

## Open question for user

afrom (10.0.0.39) — what's its actual current IP? Or is it on a different subnet now (10.2.x.x like afromini)?
