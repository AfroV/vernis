# Work Mode — Claude usage on the frame (design)

## Intent
The owner wants the Vernis frame to double as a desk companion while working:
an opt-in "Work Mode" screen that shows how much of their Claude plan quota is
left and when it resets, at a glance, in a cozy but simple look. Style
reference (approved by owner): a small dark square device showing a "Usage"
title, two rounded cards (Current / Weekly) each with a big percentage, a pill
label, a thick progress bar and "Resets in 1h 22m", plus a small animated
status line at the bottom.

## Goals
- Off by default. A toggle in Settings turns it on.
- When on: a "Work" entry in the dashboard menu (every page) and a
  "Work Mode" button on the kiosk start screen.
- `work.html`: shows the 5-hour window and the weekly window as "% left" with a
  bar, and a live "Resets in …" countdown. Works on the 720×720 kiosk display,
  a phone and a desktop browser.

## Non-goals / anti-goals
- Never store the owner's Claude login on the Pi. Only percentages and reset
  times leave the Mac.
- No Settings buttons for one-off operations beyond the toggle and the
  copyable install command (see project rule on settings bloat).
- Not a copy of the reference device's branding: no Anthropic mascot or
  spinner glyph. An original small pixel coffee cup is the icon.

## Constraints found
- Anthropic has no public quota API. The numbers come from the endpoint
  Claude Code itself uses (`GET https://api.anthropic.com/api/oauth/usage`,
  header `anthropic-beta: oauth-2025-04-20`), authenticated with the Claude Code
  CLI's OAuth login stored in the macOS Keychain (`Claude Code-credentials`).
  It is undocumented and may change.
- The desktop app does not share its login with scripts. The owner must log in
  the CLI once (`claude auth login`). Access tokens expire after hours; the
  script must not rotate the refresh token itself (that can log the CLI out).
- Security modes: a POST from the Mac would be PIN-gated in Mode C, so the push
  endpoint authenticates itself with its own push token and is exempted in
  `_enforce_security`, like `/api/mcp`.
- Python.org Python on the Mac fails TLS verification (no CA bundle). Use
  `curl` for HTTPS, passing headers on stdin so the token never appears in
  `ps`.

## Approaches considered
1. **Mac pushes numbers to the frame (chosen by owner).** Login stays on the
   Mac; numbers only update while the Mac is awake, so the page shows how old
   they are.
2. Frame fetches itself — rejected: puts an account credential on a device in
   the living room, and token refresh fights the Mac's CLI.
3. Owner types numbers in manually — rejected: defeats the point.

## Design
**Backend (`backend/app.py`)**
- `/opt/vernis/workmode.json`: `{enabled, push_token}`; latest numbers in
  `/opt/vernis/workmode-usage.json`.
- `GET /api/workmode/config` → `{enabled, has_data}` (no token).
- `POST /api/workmode/config` `{enabled}` (control-class, PIN-gated as usual).
  First enable generates a random push token.
- `POST /api/workmode/push-token` → returns token and the Mac install command
  (control-class, so Mode C requires the PIN to see it). `{"rotate":true}`
  makes a new one.
- `POST /api/workmode/usage` — called by the Mac. Requires
  `Authorization: Bearer <push_token>` (constant-time compare), 403 when the
  feature is off. Validates and stores only: per window `utilization`
  (0–100) and `resets_at` (ISO), plus `received_at`.
- `GET /api/workmode/usage` → stored numbers + `age_seconds`; 404-ish empty
  state when nothing received.
- `GET /api/workmode/installer.sh` → a bash installer with the push script
  embedded and this device's URL filled in.

**Mac (`tools/claude-quota-push/claude_quota_push.py`, also copied to
`/opt/vernis/scripts/` so the device can serve it)**
- Stdlib Python. Reads Keychain JSON, if the access token has expired runs the
  `claude` CLI so it refreshes its own login, re-reads, fetches usage via curl,
  posts `{five_hour, seven_day}` to the frame. Never prints or sends the token.
- Installer writes `~/Library/Application Support/vernis-quota/`, config with
  URL + push token (chmod 600), and a LaunchAgent (`no.vernis.quota-push`,
  every 300 s, RunAtLoad). `--uninstall` removes it.

**Frontend**
- `work.html` (new): dark rounded "screen" like the reference. Header: pixel
  cup icon, "Usage" title, small "updated 2 min ago". Two cards: big "% left",
  pill ("5-hour" / "Weekly"), thick bar showing what is left, colour by level
  (calm green → amber under 40 % → coral under 15 %), "Resets in 1h 22m".
  Footer: small cozy status that rotates words ("Brewing…", "Pondering…").
  Polls every 60 s, countdown ticks every 30 s. Past the reset time it shows
  100 % left marked "refilled". Stale > 15 min → muted "last update 2 h ago".
  No data yet → friendly setup hint pointing to Settings. Kiosk: Back button.
- Settings: "Work Mode" section with toggle; when on, shows the one-line Mac
  install command (copy button) and last-received time.
- Menu: `.workmode-nav` link hidden by default on every page with a menu,
  shown when `/api/workmode/config` says enabled (same pattern as Atelier).
- Kiosk start screen (`index.html`): "Work Mode" button, hidden unless enabled.
- Deploy/update/install scripts include `work.html` and the push script.

## Decisions made by the builder (owner may correct)
- Big number is **% left** (the owner asked "how much I have left"); the bar
  shrinks as quota is used.
- UI text in English, like the rest of Vernis.
- Per-model weekly windows (e.g. Opus-only) are shown only if present, as a
  thin third row.

## Changes after building it (2026-11-18)
The owner tried it on afrom and several decisions changed:

- **Data source:** no longer the Claude Code login. News reports say
  Anthropic's terms (Feb 2026) bar third-party tools from using a Claude
  subscription login, so reading it is not acceptable for a product.
  The Mac helper now runs `claude -p "/usage"` — Claude Code's own command,
  which sends nothing to the model (`num_turns: 0`, $0) — and parses
  "Current session: N% used · resets …" / "Current week (…): N% used · resets …".
- **Timing:** not a 5-minute LaunchAgent. The installer adds a Claude Code
  **Stop hook** (async, 45 s debounce, recursion guard via `VERNIS_QUOTA_CHILD`),
  so the frame updates after every Claude Code reply. The Claude desktop app's
  Code tab runs Claude Code as `--output-format stream-json` (no screen, so no
  status line) but does run hooks. Chats in claude.ai don't trigger an update.
  Tested and rejected: a status line (desktop app never runs it) and a hidden
  `claude` in a pseudo-terminal (numbers did not refresh while idle).
- **Display:** "% used" like Claude's own usage page (the owner compared and
  found "% left" confusing), labels Session / This week, reset clock time,
  weekly pace line, title "Claude", no mascot, Vernis theme + edge frame.
  Cards use `.quota`, not `.card`, to avoid the theme's hover lift.
- **On the frame:** the menu's **Work** on a phone/PC switches the frame's own
  screen (`/api/workmode/show`, `/hide`, CDP navigation, previous local URL
  remembered); "Back to art" also returns the phone to the dashboard, and the
  page carries the normal site menu instead of a Back link. On the frame,
  Back sits just right of the corner ornament (46 px, 20 px on the 720 px
  screen), like Wi-Fi and Connect. On a phone/PC the edge frame is drawn over
  the site header (which would otherwise hide its top), and the phone menu
  button is moved inside the frame, clear of the corner.
