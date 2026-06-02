# Vernis v3 - User Journeys & UX Review

## Table of Contents
1. [Non-Technical User Journey](#1-non-technical-user-journey)
2. [Medium-Technical User Journey](#2-medium-technical-user-journey)
3. [Technical User Journey](#3-technical-user-journey)
4. [UX Review - Ranked Issues](#4-ux-review---ranked-issues)

---

## 1. Non-Technical User Journey

**Persona**: Someone who received Vernis as a gift or bought it pre-configured. They just want to plug it in, connect to WiFi, and enjoy art on their screen. May download a CSV from a friend.

### Journey A: First-Time Setup (Power On + WiFi)

1. **Plug in power** → Device boots, Chromium kiosk loads → **Home page (index.html)** appears
2. **Status bar** (bottom center) shows: `"0 Downloaded * Not Connected"` with gray dot
3. User sees 5 cards: Fullscreen Gallery, Connect (QR code), Remote Control, CSV Library, Manage Collection
4. **No WiFi prompt or wizard is shown** — user must know to go to Settings
5. User taps **hamburger menu** (top-left ≡) → taps **Settings**
6. On Settings page, sidebar shows many sections → user must find **Wi-Fi** in the sidebar (under "System" category)
7. Taps **Wi-Fi** → sees "Current WiFi: Not Connected"
8. Taps **Scan** button → networks appear in dropdown
9. Selects network → enters password → taps **Connect to Network**
10. Gets success/error toast notification
11. Goes back to Home → status bar now shows `"0 Downloaded * MyWiFi"` with yellow dot

**Key observations:**
- There is no onboarding wizard or first-run setup flow
- WiFi is buried in Settings > Wi-Fi (4th category, 12th item in sidebar)
- User must already know the UI to find WiFi settings
- No "Get Started" prompt when device has 0 artworks

### Journey B: Browsing & Installing a Collection from Library

1. From Home, user taps **Browse Library** card (or hamburger menu → Library)
2. **Library page** loads with collection cards in a grid
3. Each card shows: cover image, name, author, NFT count, description
4. User finds a collection they like → taps **Install & Pin** button
5. Button changes to **"Starting"** → shimmer progress bar appears
6. Status text cycles: "Preparing art preservation..." → "Starting preservation engine..." → "Detecting IPFS gateway..." → "Scanning collection..."
7. Progress bar fills as downloads progress: `"12/45 downloading & pinning (2.3 MB/s)"`
8. Button shows percentage: **"27%"**
9. On completion: bar turns green → text: `"All 45 artworks downloaded & pinned"` → button: **"Installed"**
10. A **Gallery** button appears on the card
11. User taps Gallery → enters fullscreen gallery mode

**Key observations:**
- Progress feedback is good — real-time updates, speed display, percentage
- The "preparing" phase messages are reassuring but take time before real progress shows
- "Install & Pin" wording may confuse non-technical users (what does "Pin" mean?)

### Journey C: Viewing the Gallery

1. From Home, user taps **Start Gallery** card
2. **Splash screen** appears: "Vernis - Your Forever Gallery" with loading bar
3. Gallery enters fullscreen → first artwork fades in
4. Art auto-cycles every 15 seconds (default) with crossfade
5. **Controls overlay** at bottom: ◀ Prev | ▶❚❚ Play/Pause | ▶ Next
6. Controls auto-hide after 1 minute of no interaction
7. Tap anywhere to show controls again
8. Top-right: **Exit (X)** button → returns to Home
9. Top-left: **Hue sun button** (if Hue connected) + **Info (i) button**
10. Pressing **i** shows slide-up panel with artwork metadata (name, artist, description, tags)

**Key observations:**
- Gallery UX is smooth and intuitive
- Controls auto-hide is good for display mode
- Exit button is always accessible (top-right)

### Journey D: Using the Remote Control

1. From Home, user sees **Connect card** with QR code and URL (e.g., `http://10.0.0.28`)
2. Scans QR with phone → opens Vernis home page on phone
3. Taps **Open Remote** on phone → remote control page loads
4. Can navigate gallery from phone (prev/next/pause)

### Journey E: Uploading a CSV from a Friend

1. Friend sends a `.csv` file (via email, message, etc.)
2. User opens Vernis on phone/computer browser (via QR/URL)
3. Hamburger menu → **Add Collection**
4. Scrolls to **CSV Upload** section
5. Taps **Choose CSV File** or drags file onto drop zone
6. Optionally enters collection name/description
7. Taps implied upload (file selection triggers upload)
8. Loading spinner: `"Uploading filename.csv..."`
9. Success screen: checkmark, `"Collection Added! Go to Library to install."`
10. User taps **Go to Library** → finds new collection → taps **Install & Pin**

**Key observations:**
- The CSV upload flow is clear with good feedback
- The "Go to Library" redirect after upload is helpful
- Template download button helps if creating own CSV

### Journey F: Shutting Down the Device

1. From Home, user taps **status bar** (bottom center)
2. Status bar expands → shows storage info + two buttons
3. **Screen Off** → instant (no confirmation) — screen goes dark
4. **Shutdown** → confirmation modal: "The device will shut down completely. You will need physical access to turn it back on."
5. User confirms → shutdown animation plays → device powers off

---

## 2. Medium-Technical User Journey

**Persona**: Comfortable with technology. Will add their own CIDs, change themes, upload CSV files, and try to unlock easter eggs. Might have heard the unlock codes or find them online.

### Journey G: Adding a Single IPFS CID

1. Hamburger menu → **Add Collection**
2. First section: **Quick Add by CID**
3. Pastes an IPFS CID (e.g., `QmXyz...`) or full URL (`https://ipfs.io/ipfs/QmXyz...`)
4. URL prefixes are auto-stripped — input normalizes to just the CID
5. Optionally enters a name
6. Taps **Add to Gallery**
7. Info toast appears → success: `"NFT added successfully!"`
8. Input fields clear, ready for another
9. Art is now available in Gallery and Manage pages

**Key observations:**
- Accepts multiple input formats (CID, full URL) — user-friendly
- No progress bar for single CID (instant add to index, but download happens later in background)
- User might expect to see the art immediately but it needs to download first

### Journey H: Changing Theme

1. Settings → **Theme** (first/default section, easy to find)
2. Sees 6 theme cards with color swatches: Museum Gallery, Nordic Elegance, Black Walnut, X (XCOPY), Royal, Pop Art
3. Taps a theme → checkmark appears, theme applies instantly
4. Below themes: **Light Mode / Dark Mode** toggle buttons
5. Changes are immediate — no save button needed

**Key observations:**
- Theme section is the default landing in Settings — well placed
- Instant preview is great UX
- Light/Dark mode is clearly separated from color themes

### Journey I: Uploading a CSV File

(Same as Journey E above, but this user might also:)
1. Download the **CSV Template** first to understand the format
2. Create their own CSV with CIDs they've collected
3. Upload → Install from Library
4. Use **Manage NFTs** to curate which pieces show in gallery

### Journey J: Managing Collection Visibility

1. Hamburger menu → **Manage NFTs**
2. Sees grid of all downloaded artwork thumbnails
3. Tabs at top: **Artworks** | **Files** | **All IPFS Files**
4. In Artworks tab, toolbar has: Refresh, Select All, Filter/Sort, Collections, Carousels
5. User clicks individual cards to select → checkmark appears
6. Taps **Hide Selected** → selected art no longer appears in Gallery
7. Stats bar updates: "In Carousel: 30" → "Hidden: 15"
8. **Burn-in warning** appears if fewer than 10 pieces in carousel

**Key observations:**
- Selection is intuitive (tap to toggle)
- Stats bar gives good overview
- Burn-in warning is helpful but only for OLED/certain displays

### Journey K: Unlocking Easter Eggs (Keyboard Codes)

**Method 1: Typing codes on a keyboard (on Library or any page)**

1. User types `whereisthemoon` on keyboard (no input field needed — it's a global keypress listener)
2. Toast appears: `"Gazer unlocked! Visit the Lab."`
3. Goes to Home → new card appears: **AfroViking Lab** with flask icon
4. Types `pixelsonchain` → `"PixelChain unlocked! Visit the Lab."`
5. Types `doomparty` → `"DOOM Party unlocked! Visit the Lab."`

**Method 2: Being given a hint**
- Easter egg codes work on: index.html, library.html (both have keypress listeners)
- The Lab card appears on Home once any experiment is unlocked
- Each unlock persists in both localStorage and server-side (`/api/easter-egg`)

**In the Lab:**
1. User taps **Enter Lab** on Home
2. Sees unlocked experiments (Gazer, PixelChain, DOOM Party)
3. **DOOM Party** is a 3x3 puzzle — solving it unlocks CryptoPunks and/or Autoglyphs
4. After solving: sections appear, green dots confirm unlock

**Hiding easter eggs:**
- Type `hidethemoon`, `hidepixelsonchain`, `hidedoomparty` to re-lock

**Key observations:**
- Easter eggs require a physical keyboard — touch-only users can't trigger them
- No way to unlock via touch/UI (intentional — they're secrets)
- Codes work on multiple pages but not all pages
- DOOM puzzle is a second-level unlock (Lab must be visible first)

### Journey L: Using Hue Lights with Gallery

1. Settings → **Ambient Light (Hue)** in sidebar
2. Status shows "Not connected" → taps **Find Hue Bridge**
3. Must press physical button on Hue Bridge within 30 seconds
4. Bridge appears in list → user registers
5. Connected state shows: bridge IP, protocol status
6. **Lights list** appears with checkboxes — user selects which lights to sync
7. **Enable Color Sync** toggle → turns on
8. Goes to Gallery → Hue sun button (top-left) is now visible
9. Taps sun button → lights start matching artwork colors in real-time
10. On gallery exit, lights return to normal Hue app control

---

## 3. Technical User Journey

**Persona**: Power user who wants to configure everything. Tests offline mode, custom RPC, fan speeds, backups, and IPFS preservation. Might be a developer or crypto enthusiast.

### Journey M: Testing Offline Mode

1. Settings → Wi-Fi → disconnect or physically unplug ethernet
2. Home status bar shows: `"Offline"` with gray dot
3. **Gallery still works** — all previously downloaded art is stored locally on SD card
4. **Library page** still loads — but "Install & Pin" may fail (no IPFS gateway)
5. **Lab experiments** that need Ethereum RPC (PixelChain, CryptoPunks, Autoglyphs) will fail with network errors
6. **Gazer** needs Art Blocks servers — fails offline unless cached
7. **BURNER** has explicit offline cache: Settings? No — it's in Lab. "Download" button pre-caches assets from Arweave
8. **IPFS pinning** doesn't work offline (no peers to connect to)
9. **Remote control** doesn't work (no network to serve pages)

**Key observations:**
- Core gallery works offline — good
- No explicit "offline mode" indicator on pages other than Home
- Lab experiments fail silently or with generic errors — could be clearer
- No offline preparation wizard ("Download everything for offline use")

### Journey N: Configuring Custom Ethereum RPC

1. Settings → **Ethereum RPC** (under "Content" category)
2. Default: uses public RPCs (Cloudflare, Ankr, etc.)
3. Enters custom RPC URL: `https://eth-mainnet.g.alchemy.com/v2/MY_KEY`
4. Taps **Save RPC Settings**
5. Status message confirms saved
6. Goes to Lab → PixelChain → enters token number → data fetches via custom RPC
7. If RPC fails, code has fallback chain to try other providers

**Key observations:**
- Simple form, clear purpose
- Fallback chain means custom RPC failure is non-fatal
- No "test connection" button to verify RPC works before saving

### Journey O: Configuring Fan and CPU Performance

1. Settings → **Performance** (under "System" category)
2. **Device Information** shows: Model, Current MHz, Temperature, Running Profile
3. **Thermal Monitoring** shows: Current Temp, 24h Min/Max/Avg
4. **Throttle Status** shows if device is thermal throttling

5. **Performance Profile** grid shows preset cards (with emoji icons):
   - Each profile balances speed vs. heat
   - Select a profile → tap **Apply Changes**
   - Some changes require reboot (pending changes box appears)

6. **Advanced Settings** accordion:
   - CPU Cores selector (1-4 buttons)
   - Turbo Boost toggle
   - Max CPU Frequency slider (600-2400 MHz)
   - Warning: "Custom settings override the selected profile"

7. After applying: tap **Reboot** or wait for prompted reboot
8. On return, new profile is active

**Fan Control (via Performance section):**
- Fan modes are part of the performance profiles
- Silent mode (renamed from auto-quiet) = low fan speed
- Backend calculates correct fan level from current temperature

**Key observations:**
- Performance section is comprehensive but very long
- Advanced settings hidden in accordion (good for most users)
- Benchmark tool available (Quick Test 30s / Full Test longer)
- No real-time fan RPM display in UI (thermal data only)

### Journey P: Creating and Restoring a Backup

1. Settings → **Backup** (under "Storage" category)
2. Taps **Create Backup**
3. Progress bar animates: "Collecting files..." → "Compressing..." → percentage
4. Backup completes → `.tar.gz` file appears in "Previous Backups" list
5. Can download backup to computer or external storage

**Restore flow:**
6. Taps **Import Backup** → file picker opens
7. Selects `.tar.gz` or `.tgz` file
8. Progress bar shows restore progress
9. Toast notification on completion
10. Backend skips hidden files (`.env`, etc.) during import for security

**Key observations:**
- Backup includes: CSV files, settings, metadata, carousel presets
- Does NOT backup the actual artwork files (too large) — only the index/config
- This isn't explained clearly in the UI
- No indication of backup contents or size before creating

### Journey Q: Preserving Vernis on IPFS (Pinning the Software)

1. Settings → **Preserve** (last item under "System" category)
2. Description explains: "Pin the Vernis software itself to IPFS so others can access it"
3. Taps **Create Archive & Pin to IPFS**
4. Status updates during archival process
5. On completion: displays IPFS CID, gateway URL, QR code, archive size, date
6. CID can be copied to clipboard
7. Gateway URL is clickable (links to `https://ipfs.io/ipfs/Qm...`)

**Verifying the pin:**
8. Settings → **IPFS Pinning** (separate section)
9. Shows: Pinned to IPFS count, Connected Peers count
10. Expandable "Pinned CIDs" list shows all pinned hashes
11. The Vernis archive CID should appear in this list

**Sharing with others:**
12. Under "Pin Existing CID" in Preserve section
13. Another Vernis user can paste the CID → tap **Pin CID**
14. This downloads and pins the exact same Vernis installation

**Key observations:**
- "Preserve" is at the bottom of the sidebar — easy to miss
- The relationship between "Preserve" and "IPFS Pinning" sections could be confusing
- Good that it generates QR code for easy sharing
- Archive is verified clean (no passwords/real names)

### Journey R: Using External Storage

1. Connect USB drive to Pi
2. Settings → **External Drive** (under "Storage")
3. Taps **Scan for Drives** → detected drives appear
4. Selects a drive → taps **Use External Drive**
5. Current Configuration updates to show external path
6. **Migrate Files** card appears → can move existing files to external drive
7. **Read-Only Mode** toggle available (use external as read-only source)

**Key observations:**
- Migration process exists but unclear if it moves or copies
- Read-only mode useful for pre-loaded USB sticks
- External storage restricted to `/mnt/` or `/media/` paths (security)

### Journey S: Downloading Diagnostic Report

1. Settings → **About** (under "Meta" category)
2. Taps **Download Diagnostic Report** button
3. Downloads text file containing: system info, memory, storage, display, thermal, fan, network, services, Chromium, IPFS, Hue, recent logs
4. Can share this file for troubleshooting

---

## 4. UX Review - Ranked Issues

### CRITICAL (Blocks or confuses users significantly)

**C1. No First-Run Setup / Onboarding Wizard**
- When device boots for the first time with no WiFi and no art, user lands on Home with no guidance
- WiFi setup is buried in Settings > Wi-Fi (12th sidebar item)
- **Recommendation**: Add a first-run overlay or redirect to a setup wizard when `0 Downloaded` and no WiFi detected. Steps: 1) Connect WiFi, 2) Browse Library, 3) Install first collection

**C2. "Install & Pin" button label is confusing for non-technical users**
- "Pin" is IPFS jargon — most users don't know what it means
- Users just want to "Download" or "Install" their art
- **Recommendation**: Rename to just "Install" or "Download". Keep "& Pin" only in advanced settings or show as secondary info

**C3. Easter eggs require physical keyboard — no touch alternative**
- Touch-only devices (4" screen) cannot unlock Lab experiments via typing codes
- The only alternative is DOOM puzzle (which itself must be unlocked first)
- **Recommendation**: Add a hidden touch gesture (e.g., tap logo 7 times) or a code entry field somewhere accessible

**C4. No WiFi connection feedback on Home page**
- If WiFi disconnects, only the status bar (bottom, collapsed by default) shows "Offline"
- No prominent banner or notification
- **Recommendation**: Show a connection-lost banner (like the storage warning banner) when WiFi drops

### HIGH (Significant usability impact)

**H1. Settings page Performance section is too long**
- Contains: Device Info, Thermal Monitoring, Throttle Status, Performance Profiles, Advanced Settings (CPU/Turbo/Frequency), Performance Overlay, Benchmark
- User must scroll extensively to find specific controls
- **Recommendation**: Split into sub-tabs or collapsible cards within the section

**H2. Storage information is spread across 4 different locations**
- Home status bar → storage summary
- Library page → storage ring donut chart
- Settings > IPFS Pinning → "Storage Allocation" (Device Storage / Available for NFTs / Wear Leveling)
- Settings > Storage Health → actual free disk space
- These show different numbers and can confuse users
- **Recommendation**: Unify storage display language. Add tooltip/help text explaining why numbers differ

**H3. No "test connection" button for Ethereum RPC**
- User enters a custom RPC URL and saves — no way to verify it works
- Must go to Lab and try loading a PixelChain to see if it fails
- **Recommendation**: Add "Test Connection" button next to Save that tries a simple `eth_blockNumber` call

**H4. Backup doesn't explain what's included/excluded**
- Users might expect artwork files are backed up (they're not — too large)
- Only settings, CSVs, metadata, and carousels are included
- **Recommendation**: Show a brief list of what's included before creating backup. Add file size estimate

**H5. Single CID add gives no download progress**
- After "Add to Gallery" succeeds, the CID is indexed but the actual file hasn't downloaded yet
- User goes to Gallery expecting to see it, but it may not be there yet
- **Recommendation**: Show a "downloading..." state or redirect to manage page with progress indicator

**H6. Screen Saver section is misleadingly named**
- It's actually "Screen Timeout / Power Management" (turns screen off after X minutes)
- Users expecting an animated screensaver will be confused
- **Recommendation**: Rename to "Screen Timeout" or "Display Power"

### MEDIUM (Noticeable but manageable)

**M1. Lab page is empty/blank if no easter eggs unlocked**
- If user somehow navigates to lab.html directly, they see an empty page
- Lab card on Home is hidden until something is unlocked, but direct URL access is possible
- **Recommendation**: Show an engaging "discover the secrets" teaser on the Lab page when nothing is unlocked

**M2. No confirmation before large downloads**
- Tapping "Install & Pin" on a large collection (e.g., 1000+ NFTs) starts immediately
- No warning about download size, estimated time, or storage impact
- **Recommendation**: Show collection size estimate and storage impact before starting: "This will download ~2.3 GB. You have 5.1 GB free. Continue?"

**M3. Gallery splash screen is always shown (even on quick revisits)**
- "Vernis - Your Forever Gallery" splash plays every time gallery opens
- Regular users may find this slow/annoying
- **Recommendation**: Skip splash if gallery was opened in the last 5 minutes, or make it shorter on repeat visits

**M4. Display Output options don't explain compatibility**
- Auto / Internal / External / Mirror — but not all devices support all modes
- No indication of which display is currently connected
- **Recommendation**: Gray out unavailable options. Show currently detected display(s)

**M5. HTTPS setup is manual SSH commands only**
- No in-UI toggle to enable HTTPS
- Requires terminal access and command-line knowledge
- **Recommendation**: Add a "Generate Self-Signed Certificate" button that runs the commands automatically (for technical users this is still Settings, not SSH)

**M6. Manage NFTs toolbar is complex with many toggles**
- Filters, Collections, Carousels subtabs with many buttons each
- First-time users may not understand the carousel concept
- **Recommendation**: Add brief helper text under the toolbar: "Select artworks below, then use Show Only Selected to create a custom slideshow"

**M7. Carousel/Preset system naming is unclear**
- "Carousel" = the set of visible NFTs in gallery rotation
- "Show Only Selected" creates a carousel, "Hide Selected" modifies it
- Non-obvious relationship between these actions
- **Recommendation**: Use more descriptive labels: "Create Slideshow from Selected" instead of "Show Only Selected"

### LOW (Minor polish items)

**L1. Hue lights section scroll arrows are small for 4" screens**
- Up/down arrows for scrolling the lights list work but could be larger
- Already improved to meet 44px minimum, but on 4" screen still tight

**L2. Theme preview could show a sample gallery image**
- Currently shows 3 color swatches per theme
- A miniature gallery preview would help users choose

**L3. Copyright says 2025 in footer**
- Should be updated to 2025-2026 or just current year

**L4. "Scan" button next to WiFi network name is not obviously a button**
- Inline next to text input — could be mistaken for a label
- **Recommendation**: Make it more visually distinct (accent color, icon)

**L5. IPFS "Run Garbage Collection" button has no explanation**
- Technical users understand it, but others won't know what it does
- **Recommendation**: Add helper text: "Removes unused cached data to free IPFS storage space"

**L6. Preserve section QR code is small (120x120px)**
- On 4" screen this is tiny and hard to scan
- **Recommendation**: Make QR code larger or add "enlarge" tap option

**L7. Help & Guide section could link to relevant Settings sections**
- Currently text-only instructions
- Linking "Settings > Wi-Fi" in the text to actually navigate there would be helpful

### NICE-TO-HAVE (Enhancement ideas)

**N1. Add a "What's New" popup on version updates**
- After software update, show changelog highlights on first visit

**N2. Favorites system in Gallery**
- Long-press or double-tap to favorite an artwork
- Filter gallery to show only favorites

**N3. Gallery statistics**
- "You've viewed 234 artworks this month"
- Most-viewed artwork, time spent in gallery mode

**N4. Quick-access settings from Gallery**
- Swipe up from bottom in gallery to adjust timing/crossfade without leaving

**N5. Collection preview before installing**
- Show sample artwork thumbnails in Library before downloading

**N6. Dark/Light mode auto-switch based on time of day**
- Light during day, dark at night (configurable schedule)

**N7. Battery/UPS status indicator**
- If connected to a UPS, show battery level in status bar

---

## Summary Table

| # | Issue | Severity | Area |
|---|-------|----------|------|
| C1 | No first-run setup wizard | Critical | Home/Settings |
| C2 | "Install & Pin" confusing label | Critical | Library |
| C3 | Easter eggs need keyboard (no touch) | Critical | Library/Lab |
| C4 | No WiFi disconnect notification | Critical | Home |
| H1 | Performance section too long | High | Settings |
| H2 | Storage info in 4 different places | High | Multiple |
| H3 | No RPC test connection button | High | Settings |
| H4 | Backup contents not explained | High | Settings |
| H5 | Single CID no download progress | High | Add Collection |
| H6 | "Screen Saver" misleading name | High | Settings |
| M1 | Empty Lab page if nothing unlocked | Medium | Lab |
| M2 | No download size warning | Medium | Library |
| M3 | Gallery splash always shown | Medium | Gallery |
| M4 | Display options no compatibility info | Medium | Settings |
| M5 | HTTPS requires SSH | Medium | Settings |
| M6 | Manage toolbar complex | Medium | Manage |
| M7 | Carousel naming unclear | Medium | Manage |
| L1 | Hue scroll arrows small on 4" | Low | Settings |
| L2 | Theme preview could show gallery | Low | Settings |
| L3 | Copyright year outdated | Low | All pages |
| L4 | WiFi Scan button not distinct | Low | Settings |
| L5 | GC button no explanation | Low | Settings |
| L6 | Preserve QR code small | Low | Settings |
| L7 | Help section not linked | Low | Settings |
| N1-N7 | Enhancement ideas | Nice-to-have | Various |
