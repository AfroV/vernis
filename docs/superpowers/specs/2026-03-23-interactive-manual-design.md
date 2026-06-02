# Interactive Owner's Manual — Design Spec

## Problem

Vernis has no user-facing documentation. The startup wizard was removed. Users connecting to their frame for the first time have no guidance on setup, features, or troubleshooting. The manual replaces the wizard with a richer, always-available reference.

## Solution

A single self-contained `manual.html` file styled in the Vernis walnut-dark premium design. A card-based hub page with 9 chapter cards. Tapping a card opens that chapter inline. A URL input at the top lets users enter their Vernis address so all links in the manual point directly to their device's pages.

## Users

- **New owner**: Just received a Vernis frame, needs to connect and set up.
- **Existing user**: Wants a reference for features they haven't explored (Lab, Hue, Bluetooth, carousels).
- **Troubleshooter**: Something isn't working and they need guidance.

## Constraints

- Accessed from phone or laptop browser (not the Pi kiosk screen).
- Fully self-contained single HTML file — no external CSS, JS, or font dependencies. Works offline.
- Must match the Vernis walnut-dark visual design (same as index.html).
- No images — all content is text, SVG icons, and styled HTML.

---

## File

**`manual.html`** — deployed to `/var/www/vernis/manual.html`

---

## Page Structure

### Hub View (Landing)

The default view when `manual.html` loads.

**Layout (top to bottom):**
1. Decorative frame (fixed, same as index.html) — double border, corner ornaments, side lines, vignette
2. "VERNIS" title — Playfair Display 80px, gold gradient (`linear-gradient(135deg, #d4af37, #f5e6a3, #d4af37)`), `letter-spacing: 0.15em`
3. Diamond ornament + decorative lines (same pattern as index.html hero)
4. "Owner's Manual" subtitle — Cormorant Garamond 22px, `#d4cfc4`, `letter-spacing: 0.3em`
5. URL input section:
   - Gold-bordered input field, placeholder: "Enter your Vernis address (e.g. http://10.0.0.28)"
   - Status indicator below the input (centered, small text): green dot + "Links active" when URL is saved, muted "Enter URL above to enable links" when empty
   - Value saved to `localStorage` key `vernis-manual-url` on input change (debounced 500ms)
   - On load, restores saved URL and updates all live links
6. Decorative separator line
7. Chapter card grid — responsive: 3 columns on desktop (>1024px), 2 on tablet (>640px), 1 on phone
8. Footer — "Vernis v3" in muted text

### Chapter View

Displayed when user taps a chapter card. Replaces the hub content (no page navigation, just DOM show/hide).

**Layout:**
1. Decorative frame remains (fixed)
2. Back button — top-left, chevron + "Back", returns to hub view
3. Chapter title — Playfair Display with gold gradient, same style as hero but smaller (42px)
4. Diamond ornament + line below title
5. Chapter content — scrollable, padded, max-width 800px centered
6. "Back to Manual" button at bottom of content

**Transitions:** CSS transitions, 300ms ease-out:
- Hub → Chapter: hub fades out (`opacity 1→0`), chapter slides in from right (`translateX(30px)→0` + `opacity 0→1`)
- Chapter → Hub (back): chapter fades out (`opacity 1→0`), hub fades in (`opacity 0→1`). Intentionally fade-only (no slide) to distinguish back navigation from forward.
- Use CSS classes `.view-entering` / `.view-exiting` toggled by JS. `setTimeout` to swap `display:none` after transition completes.

---

## Visual Design

### Theme (hardcoded walnut-dark)

```css
--bg-primary: #0f0e0c;
--bg-secondary: #1a1815;
--bg-tertiary: #231e19;
--text-primary: #e8e0d4;
--text-secondary: #d4cfc4;
--text-muted: #8b7b68;
--accent-primary: #d4af37;
--accent-secondary: #f5e6a3;
--border-light: #2a2420;
--border-medium: #3d352d;
```

### Fonts (base64 embedded)

- **Playfair Display** (Bold, ~80KB woff2) — headings, title, chapter names
- **Cormorant Garamond** (Regular + SemiBold, ~60KB each woff2) — body text, descriptions, steps

Embedded as `@font-face` with `src: url(data:font/woff2;base64,...)`.

**Font sourcing:** Download woff2 files from Google Fonts API:
- `https://fonts.google.com/download?family=Playfair+Display` (use Bold weight)
- `https://fonts.google.com/download?family=Cormorant+Garamond` (use Regular + SemiBold weights)

Convert to base64 with `base64 -i font.woff2 | tr -d '\n'` and embed inline in `@font-face` declarations. If font files are too large (>100KB each), use `pyftsubset` from `fonttools` to subset to Latin characters only before base64 encoding.

### Decorative Frame

Identical to index.html:
- `.main-frame` fixed overlay with double border (outer 1px at 16px inset, inner 0.5px at 26px inset)
- Corner ornaments (50px L-shapes) at all four corners
- Side accent lines (vertical, 15%-85% height, 0.18 opacity)
- Vignette: `radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.25) 100%)`

### Cards

Same style as index.html cards:
- Background: `var(--bg-secondary)` with `var(--border-light)` border
- Border-radius: 16px
- Padding: 42px 36px
- Gold gradient top-bar (4px, `opacity: 0` → `1` on hover)
- Hover effects wrapped in `@media (hover: hover) and (pointer: fine)` to prevent sticky hover on touch devices
- Hover: `translateY(-8px)` + border turns gold
- Icon: inline SVG, 40px, gold colored
- Title: Playfair Display 26px
- Description: 15px, `var(--text-secondary)`

### Chapter Content Styling

- **Step numbers**: Gold circles (28px diameter, `#d4af37` background, `#0f0e0c` text, Playfair Display bold)
- **Step text**: Cormorant Garamond 17px, line-height 1.7
- **Tip callout**: Left border 3px `#d4af37`, background `rgba(212,175,55,0.06)`, padding 16px 20px, border-radius 8px
- **Warning callout**: Left border 3px `#f0ad4e`, background `rgba(240,173,78,0.06)`
- **Live links**: Gold colored (`#d4af37`), underline on hover, `cursor: pointer`. Disabled state: `#8b7b68`, no underline, `cursor: default`, title tooltip "Enter your Vernis URL to enable this link"
- **Section headings**: Playfair Display 24px, gold color, with thin gold line below (120px, gradient fade)
- **Keyboard shortcuts / UI labels**: Inline code style — `#231e19` background, `#f5e6a3` text, 1px `#3d352d` border, border-radius 4px, padding 2px 8px

---

## Live Links

### URL Input

```html
<input type="url" id="vernis-url" placeholder="Enter your Vernis address (e.g. http://10.0.0.28)">
```

**Behavior:**
1. On input change (debounced 500ms): validate starts with `http://` or `https://`, strip trailing slash, save to `localStorage('vernis-manual-url')`
2. On save: call `updateLinks()` — finds all `[data-vernis-link]` elements, sets `href` to `savedUrl + '/' + element.dataset.vernisLink`
3. On load: restore URL from localStorage. If restored value does not start with `http://` or `https://`, discard it (clear localStorage key). Otherwise populate input and call `updateLinks()`.
4. Status indicator updates: green dot when URL valid and saved, muted prompt when empty
5. No reachability check — the manual does not verify the URL is reachable. If the user enters a wrong IP, links simply won't load. This is acceptable since the manual is a static reference document.

### Link Markup

```html
<a data-vernis-link="settings.html">Open Settings</a>
<a data-vernis-link="gallery.html">Launch Gallery</a>
<a data-vernis-link="add.html">Add Art</a>
```

Links open in a new tab (`target="_blank"`).

### Linkable Pages

All Vernis pages: `index.html`, `settings.html`, `gallery.html`, `manage.html`, `add.html`, `lab.html`, `library.html`, `connect.html`, `remote.html`

---

## Chapters

### 1. Getting Started
**Icon:** Rocket SVG
**Card description:** "First-time setup and connection"
**Sections:**
- Powering on your Vernis frame
- Connecting to WiFi (QR code or manual)
- Connecting via Bluetooth PAN (fallback)
- Finding your Vernis address
- Opening the web interface

**Live links:** connect.html, settings.html

### 2. Adding Art
**Icon:** Plus-circle SVG
**Card description:** "Import collections and upload files"
**Sections:**
- Adding a collection via CSV
- Downloading the CSV template
- Adding a single artwork by CID
- Uploading files directly
- Browsing the CSV library

**Live links:** add.html, library.html

### 3. Managing Art
**Icon:** Grid SVG
**Card description:** "Organize, sort, and curate"
**Sections:**
- Viewing your artworks
- Sorting by collection, date, or name
- Creating custom carousels (save, load, delete, import)
- Editing NFT metadata (name, artist, collection)
- Scanning metadata from filenames
- Bulk select and delete

**Live links:** manage.html

### 4. Gallery
**Icon:** Frame SVG
**Card description:** "View your art in fullscreen"
**Sections:**
- Starting the gallery
- Navigation (prev/next, swipe)
- Slideshow mode and display duration (image/video timing)
- Artwork info panel (i button)
- Hue light sync (if Hue bridge configured)

**Live links:** gallery.html, settings.html

### 5. Display & Themes
**Icon:** Palette SVG
**Card description:** "Themes, orientation, and display modes"
**Sections:**
- Choosing a theme (Walnut, Gallery, XCOPY)
- Light and dark modes
- Screen orientation (0/90/180/270)
- Supersize modes (A, B, C)
- External display (HDMI) and mirror mode

**Live links:** settings.html

### 6. Connectivity
**Icon:** Signal SVG
**Card description:** "WiFi and Bluetooth setup"
**Sections:**
- Scanning and connecting to WiFi networks
- Viewing current connection status
- Bluetooth PAN setup (pairing, connecting to network)
- Managing paired Bluetooth devices
- Troubleshooting connection issues

**Live links:** connect.html, settings.html

### 7. Lab
**Icon:** Flask SVG
**Card description:** "Generative art and experiments"
**Sections:**
- Gazer — Art Blocks live rendering
- PixelChain — ASCII art viewer
- Hue sync in lab modes
- Remote rendering (Docker)

Note: Autoglyphs and CryptoPunks are easter-egg features (hidden by default). Omit from the manual.

**Live links:** lab.html

### 8. Settings
**Icon:** Gear SVG
**Card description:** "Storage, IPFS, security, and more"
**Sections:**
- Storage management and health
- IPFS configuration and pinning
- Backup and restore
- Security (password, HTTPS)
- Thermal monitoring and fan control
- CPU performance profiles
- System updates

**Live links:** settings.html

### 9. Troubleshooting
**Icon:** Wrench SVG
**Card description:** "Common issues and fixes"
**Sections:**
- Can't connect to Vernis (WiFi/BT)
- Gallery not showing artworks
- Downloads stuck or failing
- Display color issues
- Storage full
- Restarting services
- Factory reset / diagnostic report

**Live links:** settings.html

---

## Settings Integration

The existing **Help & Guide** section (`#section-help`) in `settings.html` contains inline setup instructions (First Setup, Bluetooth, WiFi Hotspot). This content is superseded by the manual. Replace the entire `#section-help` content with a single card containing:

- Section header: "Help & Guide" (keep existing)
- A "User Manual" button that navigates to `manual.html`
- Brief text: "Complete setup instructions, feature guides, and troubleshooting"

```html
<div class="settings-card" style="text-align:center; padding: 40px 24px;">
  <p style="color: var(--text-secondary); margin-bottom: 20px; font-size: 15px;">
    Complete setup instructions, feature guides, and troubleshooting
  </p>
  <button onclick="window.location.href='manual.html'"
    style="padding: 12px 28px; border-radius: 10px; border: 1px solid var(--accent-primary);
    background: transparent; color: var(--accent-primary); font-size: 16px;
    font-family: var(--font-body); cursor: pointer;">
    Open User Manual
  </button>
</div>
```

---

## Chapter Content

The implementer writes all chapter content based on the section headings listed above. Content should be written by reading the relevant Vernis source files (HTML pages and `backend/app.py`) to understand each feature's actual behavior. Each section should have 2-5 numbered steps with concise instructions. Tone: clear, friendly, premium — not overly technical. Assume the reader is not a developer.

---

## Files Changed

| File | Action | Responsibility |
|------|--------|----------------|
| `manual.html` | Create | Self-contained interactive manual with all CSS, fonts, JS, and content inline |
| `settings.html` | Modify | Replace Help & Guide section content with single "Open User Manual" button |

---

## Testing

1. Open `manual.html` on phone — verify responsive layout, cards readable, scrolling smooth.
2. Open on desktop — verify 3-column grid, hover effects work.
3. Enter a Vernis URL — verify links turn gold and active, open correct pages in new tab.
4. Clear URL — verify links show disabled state.
5. Reload page — verify URL persists from localStorage.
6. Navigate all 9 chapters — verify back button works, content displays correctly.
7. Test with no network — verify page renders fully (fonts, styles, icons all embedded).
8. Verify Settings > Help & Guide shows "Open User Manual" button and it navigates correctly.
