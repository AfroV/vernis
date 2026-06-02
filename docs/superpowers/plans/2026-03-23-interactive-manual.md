# Interactive Owner's Manual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained interactive HTML manual for Vernis digital art frame owners, matching the walnut-dark premium design.

**Architecture:** Single `manual.html` file with all CSS, fonts (base64), JS, and content inlined. Card-based hub landing page with 9 chapter cards. Tapping a card shows that chapter with CSS transitions. URL input persisted to localStorage enables live links to the user's device. Settings page updated to link to the manual.

**Tech Stack:** HTML, CSS (walnut-dark theme vars hardcoded), vanilla JS, base64-embedded woff2 fonts (Playfair Display, Cormorant Garamond)

**Spec:** `docs/superpowers/specs/2026-03-23-interactive-manual-design.md`

**Note on innerHTML usage:** This manual uses `.innerHTML` to render chapter content from a hardcoded JS object (not user input). All content strings are author-controlled static HTML embedded in the same file — there is no external/untrusted input involved, so this is safe from XSS. Using DOM construction methods for 9 chapters of rich HTML would add significant complexity with no security benefit.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `manual.html` | Create | Self-contained interactive manual — all CSS, fonts, JS, SVG icons, and chapter content inline |
| `settings.html` | Modify (lines ~5184-5632, `#section-help`) | Replace `#section-help` content with single "Open User Manual" card |

---

### Task 1: Scaffold manual.html with embedded fonts and base CSS

Create the foundational HTML file with doctype, embedded fonts, CSS custom properties (walnut-dark hardcoded), base typography, and the decorative frame. No interactive content yet — just the shell that everything builds on.

**Files:**
- Create: `manual.html`

**Context:** The file must be fully self-contained (no external CSS/JS/fonts). For the decorative frame: read `index.html:126-170` for the CSS (`.main-frame`, `.main-frame-border`, `.main-frame-border-inner`, `.corner-ornament`, `.side-line`, `.main-frame-vignette`), and `index.html:600-620` for the HTML markup. Copy both verbatim. The walnut-dark color values are hardcoded as CSS custom properties on `:root`.

**Font embedding:** Download woff2 fonts from Google Fonts. For Playfair Display Bold and Cormorant Garamond Regular + SemiBold. Convert to base64 and embed as `@font-face` blocks. If files are >100KB each, subset to Latin with `pyftsubset` first.

- [ ] **Step 1: Download and prepare font files**

```bash
# Download Playfair Display
curl -L "https://fonts.google.com/download?family=Playfair+Display" -o /tmp/playfair.zip
unzip -o /tmp/playfair.zip -d /tmp/playfair

# Download Cormorant Garamond
curl -L "https://fonts.google.com/download?family=Cormorant+Garamond" -o /tmp/cormorant.zip
unzip -o /tmp/cormorant.zip -d /tmp/cormorant
```

Check file sizes. If any woff2 is >100KB, subset:
```bash
pip3 install fonttools brotli
pyftsubset font.ttf --output-file=font-latin.woff2 --flavor=woff2 --unicodes="U+0000-00FF,U+2000-206F,U+2190-21FF"
```

Convert to base64:
```bash
base64 -i font.woff2 | tr -d '\n' > font.b64
```

- [ ] **Step 2: Create manual.html with DOCTYPE, fonts, and base CSS**

Create `manual.html` with:
- `<!DOCTYPE html>`, charset, viewport meta
- `<style>` block containing:
  - `@font-face` declarations with base64 font data
  - `:root` with all walnut-dark CSS custom properties (copy from spec)
  - Base `body` styles: `background: var(--bg-primary)`, `color: var(--text-primary)`, `font-family: 'Cormorant Garamond', serif`, `margin: 0`
  - User-select disable (matches index.html kiosk pattern)
  - Scrollbar hide (`::-webkit-scrollbar { width: 0 }`)
- Decorative frame CSS (copy from `index.html:126-170`) and HTML (copy from `index.html:600-620`):
  - `.main-frame` with `.main-frame-border`, `.main-frame-border-inner`
  - 4x `.corner-ornament` (tl, tr, bl, br)
  - 2x `.side-line` (l, r)
  - `.main-frame-vignette`
- Empty `<div id="hub-view">` and `<div id="chapter-view" style="display:none">`

- [ ] **Step 3: Verify the frame renders correctly**

Open `manual.html` in a browser. Verify:
- Dark background (`#0f0e0c`)
- Gold decorative frame border visible
- Corner ornaments at all 4 corners
- Side accent lines visible
- Vignette subtle darkening at edges
- No external resource errors in console

- [ ] **Step 4: Commit**

```bash
git add manual.html
git commit -m "feat: scaffold manual.html with embedded fonts and decorative frame"
```

---

### Task 2: Hub view — hero section and URL input

Build the hub landing page header: VERNIS title, diamond ornament, subtitle, URL input with localStorage persistence, and status indicator.

**Files:**
- Modify: `manual.html`

**Context:** Read `index.html:62-124` for the hero section CSS (`.hero h1` gold gradient, `.hero-diamond`, `.hero-line-top`, `.hero-line-below`, `.hero-separator`). Copy the visual pattern exactly. The URL input is a new element — styled with gold border, transparent background, centered, max-width 400px.

- [ ] **Step 1: Add hero section HTML inside `#hub-view`**

```html
<div class="hero">
  <div class="hero-diamond"></div>
  <div class="hero-line-top"></div>
  <h1>VERNIS</h1>
  <div class="hero-line-below"></div>
  <p>OWNER'S MANUAL</p>
  <div class="hero-separator"></div>
</div>
```

Add matching CSS (copy hero styles from `index.html:62-124`). The subtitle uses `letter-spacing: 0.3em`.

- [ ] **Step 2: Add URL input section**

Below the hero, add:

```html
<div class="url-section">
  <input type="url" id="vernis-url"
    placeholder="Enter your Vernis address (e.g. http://10.0.0.28)"
    autocomplete="off" spellcheck="false">
  <div id="url-status" class="url-status">
    <span class="url-status-text">Enter URL above to enable links</span>
  </div>
</div>
```

CSS for `.url-section`:
- `text-align: center`, `margin: 30px auto`, `max-width: 460px`, `padding: 0 24px`

CSS for `#vernis-url`:
- `width: 100%`, `padding: 14px 20px`, `border-radius: 10px`
- `border: 1px solid var(--border-medium)`, `background: var(--bg-secondary)`
- `color: var(--text-primary)`, `font-family: 'Cormorant Garamond', serif`, `font-size: 16px`
- `outline: none`, focus: `border-color: var(--accent-primary)`
- `box-sizing: border-box`

CSS for `.url-status`:
- `margin-top: 10px`, `font-size: 13px`, `color: var(--text-muted)`
- `.url-status.active .url-status-text` color `var(--accent-primary)`
- `.url-status-dot` — `display: inline-block`, `width: 6px`, `height: 6px`, `border-radius: 50%`, `background: #22c55e`, `margin-right: 6px`, `vertical-align: middle`

- [ ] **Step 3: Add URL persistence JavaScript**

Add a `<script>` block at the end of `<body>`. The URL input logic:

1. On input change (debounced 500ms): validate starts with `http://` or `https://`, strip trailing slash, save to `localStorage('vernis-manual-url')`
2. On save: call `updateLinks()` — finds all `[data-vernis-link]` elements, sets `href` to `savedUrl + '/' + element.dataset.vernisLink`, removes `link-disabled` class, adds `target="_blank"`. If no URL: removes href, adds `link-disabled`, sets title tooltip.
3. On load: restore URL from localStorage. If restored value doesn't start with `http://` or `https://`, discard it. Otherwise populate input and call `updateLinks()`.
4. Status indicator: green dot + "Links active" when valid URL saved, muted prompt when empty.

- [ ] **Step 4: Verify hero and URL input**

Open in browser. Verify:
- "VERNIS" in gold gradient with diamond + lines
- "OWNER'S MANUAL" subtitle below
- URL input centered, gold border on focus
- Type a URL with `http://` prefix — status shows "Links active" with green dot
- Reload — URL persists
- Clear input — status reverts to muted prompt

- [ ] **Step 5: Commit**

```bash
git add manual.html
git commit -m "feat: add hub hero section and URL input with localStorage"
```

---

### Task 3: Hub view — chapter card grid with SVG icons

Add the 9 chapter cards in a responsive grid. Each card has an inline SVG icon, title, and description. Cards are clickable but navigation logic comes in the next task.

**Files:**
- Modify: `manual.html`

**Context:** Card CSS inspired by `index.html:172-244`. The manual uses `margin-top: 40px` (tighter than index.html's 60px since the URL input section is above the cards). Key details: `.cards` uses `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))`, `.card` has `border-radius: 16px`, gold top-bar `::before`, hover effects guarded by `@media (hover: hover) and (pointer: fine)`.

- [ ] **Step 1: Add card grid CSS**

```css
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 28px;
  margin-top: 40px;
  padding: 0 50px 80px;
  max-width: 1200px;
  margin-left: auto;
  margin-right: auto;
}
```

Card styles: `background: var(--bg-secondary)`, `border: 1px solid var(--border-light)`, `border-radius: 16px`, `padding: 42px 36px`, `text-align: center`, `cursor: pointer`, `position: relative`, `overflow: hidden`.

Card `::before` pseudo-element: gold gradient top-bar (4px), `opacity: 0`, transitions on hover.

Hover effects wrapped in `@media (hover: hover) and (pointer: fine)`: `translateY(-8px)`, `border-color: var(--accent-primary)`, `::before` opacity 1.

Card icon: `.card-icon` 40px centered, SVG `fill: none`, `stroke: currentColor`, `stroke-width: 1.5`.

Card title: `font-family: 'Playfair Display', serif`, 26px, 700 weight.

Card description: 15px, `color: var(--text-secondary)`.

Responsive: 1 column on phone (<768px with smaller padding), 2 columns on tablet (641-1023px), auto-fit on desktop.

- [ ] **Step 2: Add decorative separator line before cards**

A `.section-divider` — 300px wide, 1px, gold gradient, 0.4 opacity, centered.

- [ ] **Step 3: Add 9 chapter cards with inline SVG icons**

Each card: `<div class="card" onclick="showChapter('chapter-id')">` with:
- `.card-icon` containing a simple SVG (24x24 viewBox, stroke-based)
- `<h3>` title
- `<p>` description

Cards and their icons (per spec):
1. Getting Started — rocket (launch/startup metaphor)
2. Adding Art — plus-circle
3. Managing Art — 4-square grid
4. Gallery — image/frame with landscape
5. Display & Themes — palette (color/design metaphor)
6. Connectivity — WiFi signal arcs
7. Lab — flask/beaker
8. Settings — gear
9. Troubleshooting — wrench

- [ ] **Step 4: Add footer**

```html
<div class="footer">Vernis v3</div>
```

Styled: centered, muted text, 13px, letter-spacing 0.1em, padding-bottom 40px.

- [ ] **Step 5: Verify card grid renders**

Open in browser. Verify:
- 9 cards in responsive grid (resize window to check 3/2/1 columns)
- Each card has gold SVG icon, Playfair title, description
- Hover lifts card and shows gold top-bar (desktop only)
- Footer shows below cards

- [ ] **Step 6: Commit**

```bash
git add manual.html
git commit -m "feat: add 9 chapter cards with SVG icons and responsive grid"
```

---

### Task 4: Chapter view with navigation transitions

Add the chapter view container, back button, view switching logic with CSS transitions, and placeholder content for testing.

**Files:**
- Modify: `manual.html`

**Context:** The spec defines transitions: Hub to Chapter = hub fades out + chapter slides from right (300ms ease-out). Chapter to Hub = chapter fades out + hub fades in (fade-only, no slide — intentional asymmetry). The spec names the entering class `.view-entering` — this plan uses `.view-entering-chapter` for clarity since only the chapter slides in (hub uses fade-only). Use `.view-exiting` / `.view-entering-chapter` CSS classes toggled by JS with `setTimeout` for display swap after transition completes.

- [ ] **Step 1: Add chapter view HTML structure**

Inside `#chapter-view`:

- Back button (fixed position, top-left, below frame corner): chevron SVG + "Back" text
- `.chapter-content` container (max-width 800px, centered, padded)
- `#chapter-title` heading (gold gradient, 42px Playfair)
- Diamond + separator ornaments below title
- `#chapter-body` div (chapter HTML rendered here)
- "Back to Manual" button at bottom

- [ ] **Step 2: Add chapter view and transition CSS**

Back button: `position: fixed`, `top: 76px`, `left: 24px`, z-index 1002, transparent bg, white text, Cormorant Garamond 18px.

Chapter title: 42px Playfair Display, gold gradient `-webkit-background-clip: text`.

"Back to Manual" button: gold border, transparent bg, gold text, 10px radius.

Transition CSS:
- `#hub-view, #chapter-view` get `transition: opacity 300ms ease-out, transform 300ms ease-out`
- `.view-exiting`: `opacity: 0 !important`
- `.view-entering-chapter`: `opacity: 0; transform: translateX(30px)`

Responsive: chapter padding reduces on mobile, title 32px, back button repositioned.

- [ ] **Step 3: Add chapter content styling CSS**

Section headings: `.ch-section-title` — Playfair 24px, gold color, margin-top 40px.
Section lines: `.ch-section-line` — 120px, gold gradient fade, 0.4 opacity.

Numbered steps: `.step` flex container with `.step-num` (28px gold circle, dark text, Playfair bold 14px) + `.step-text` (17px, line-height 1.7, secondary color).

Callouts: `.tip` (gold left border 3px, gold-tinted bg) and `.warning` (amber left border, amber-tinted bg).

Live links: `a[data-vernis-link]` gold color, underline on hover. `.link-disabled` muted color, default cursor, no underline.

UI labels: `.ui-label` — tertiary bg, light gold text, 1px border, 4px radius, 2px 8px padding.

- [ ] **Step 4: Add view switching JavaScript**

`showChapter(id)` function:
1. Look up chapter data from `chapters` object
2. Set title text via `textContent`
3. Set body content (from hardcoded chapter HTML strings — these are author-controlled, not user input)
4. Call `updateLinks()` to apply URL to new `data-vernis-link` elements
5. Add `.view-exiting` to hub, show chapter with `.view-entering-chapter`, force reflow, remove entering class
6. After 300ms timeout: hide hub, remove exiting class, scroll to top

`showHub()` function:
1. Add `.view-exiting` to chapter, show hub with opacity 0
2. Force reflow, set hub opacity 1
3. After 300ms: hide chapter, remove exiting class, scroll to top

- [ ] **Step 5: Add placeholder chapter data for testing**

Add one test chapter entry in the `chapters` object to verify the full flow works:

```javascript
chapters['getting-started'] = {
  title: 'Getting Started',
  content: '<h3 class="ch-section-title">Powering On</h3><div class="ch-section-line"></div>' +
    '<div class="step"><div class="step-num">1</div><div class="step-text">Connect power to your Vernis frame</div></div>' +
    '<div class="tip"><strong>Tip:</strong> Test tip callout</div>' +
    '<p><a data-vernis-link="connect.html">Open Connect Page</a></p>'
};
```

- [ ] **Step 6: Verify navigation works**

Open in browser. Verify:
- Click "Getting Started" card: hub fades out, chapter slides in from right
- Chapter title shows in gold gradient with ornaments
- Placeholder content: gold step number, text, tip callout, live link
- Back button returns to hub (fade-only, no slide)
- "Back to Manual" bottom button also returns to hub
- Scroll resets to top on both transitions
- Live link functional if URL is set

- [ ] **Step 7: Commit**

```bash
git add manual.html
git commit -m "feat: add chapter view with navigation transitions and content styling"
```

---

### Task 5: Write chapter content — Getting Started, Adding Art, Managing Art

Write the actual content for chapters 1-3. Read the relevant source files to understand feature behavior. Write 2-5 numbered steps per section, with tips and live links.

**Files:**
- Modify: `manual.html`

**Context for content writing:**
- **Getting Started**: Read `connect.html` for WiFi/BT connection flow, `index.html` kiosk connect overlay (lines ~449-500) for QR code behavior
- **Adding Art**: Read `add.html` for CSV upload, single CID, file upload flows
- **Managing Art**: Read `manage.html` for carousel, metadata, sorting features

The implementer writes all chapter content based on the section headings in the spec. Content should be written by reading the relevant Vernis source files to understand each feature's actual behavior. Each section should have 2-5 numbered steps with concise instructions. Tone: clear, friendly, premium — not overly technical. Assume the reader is not a developer.

- [ ] **Step 1: Write Getting Started chapter content**

Replace the placeholder `chapters['getting-started']` with full content covering 5 sections:
1. **Powering On** — plug in, wait for splash, home screen appears on the frame
2. **Connecting to WiFi** — scan QR code shown on the frame screen, or navigate to Connect page and enter WiFi credentials
3. **Connecting via Bluetooth** — fallback when no WiFi: pair phone with the Vernis device name, connect to PAN, visit `http://10.44.0.1`
4. **Finding Your Address** — IP shown on home screen connect card and on the connect page
5. **Opening the Web Interface** — type the address in any phone/laptop browser

Each section uses: `<h3 class="ch-section-title">`, `<div class="ch-section-line">`, then `.step` > `.step-num` + `.step-text`. Add `.tip` callouts and `data-vernis-link` links where relevant.

Live links to include: `connect.html`, `settings.html`

- [ ] **Step 2: Write Adding Art chapter content**

`chapters['adding-art']` with 5 sections:
1. **Adding via CSV** — navigate to Add page, upload CSV file, monitor download progress
2. **CSV Template** — download template button, explain columns: name, cid, metadata_url
3. **Single Artwork** — enter IPFS CID directly, tap Add
4. **Uploading Files** — drag and drop or file picker in Upload Files section
5. **CSV Library** — browse pre-made collections in the library, tap Install

Live links: `add.html`, `library.html`

- [ ] **Step 3: Write Managing Art chapter content**

`chapters['managing-art']` with 6 sections:
1. **Viewing Artworks** — grid view of all downloaded art with thumbnails
2. **Sorting** — use dropdown to sort by collection, date added, or name
3. **Custom Carousels** — select artworks, save as named carousel, load/delete/export carousels
4. **Metadata Editing** — select files, tap Edit, set name/artist/collection fields
5. **Scan Metadata** — tap Scan All to auto-extract collection names from filenames
6. **Bulk Operations** — select all/none, delete selected artworks

Live links: `manage.html`

- [ ] **Step 4: Verify chapters 1-3 render correctly**

Open browser, navigate to each chapter. Verify:
- Section headings in gold with underline
- Numbered steps with gold circles
- Tip callouts with gold left border
- Live links gold and functional (if URL set) — clicking opens in a new tab (`target="_blank"`)
- Content is readable and well-spaced

- [ ] **Step 5: Commit**

```bash
git add manual.html
git commit -m "feat: add chapter content for Getting Started, Adding Art, Managing Art"
```

---

### Task 6: Write chapter content — Gallery, Display & Themes, Connectivity

Write content for chapters 4-6.

**Files:**
- Modify: `manual.html`

**Context for content writing:**
- **Gallery**: Read `gallery.html` for slideshow controls, Hue sync, info panel, swipe navigation
- **Display & Themes**: Read `settings.html` display section for theme picker, orientation, supersize, HDMI
- **Connectivity**: Read `connect.html` for BT tab, paired devices list; `settings.html` WiFi section

- [ ] **Step 1: Write Gallery chapter content**

`chapters['gallery']` with 5 sections:
1. **Starting the Gallery** — tap View Art on home screen, or use the gallery link
2. **Navigation** — swipe or tap screen edges for prev/next, tap center to show/hide controls
3. **Display Duration** — adjust image and video duration in Settings > Display
4. **Artwork Info** — tap the "i" button to see name, artist, description from metadata
5. **Hue Light Sync** — tap sun icon to sync Philips Hue lights with artwork colors

Live links: `gallery.html`, `settings.html`

- [ ] **Step 2: Write Display & Themes chapter content**

`chapters['display-themes']` with 5 sections:
1. **Choosing a Theme** — Walnut (warm gold), Gallery (museum neutral), XCOPY (neon punk)
2. **Light and Dark Modes** — toggle between light and dark variants of each theme
3. **Screen Orientation** — select 0/90/180/270 degree rotation for your mounting orientation
4. **Supersize Modes** — A/B/C for different UI element scaling on touch screens
5. **External Display** — HDMI output mode, mirror mode for showing art on a second screen

Live links: `settings.html`

- [ ] **Step 3: Write Connectivity chapter content**

`chapters['connectivity']` with 5 sections:
1. **WiFi Networks** — scan for available networks, select one, enter password
2. **Connection Status** — current network name and device IP displayed
3. **Bluetooth PAN Setup** — enable discoverable mode, pair your device, connect to the PAN network
4. **Paired Devices** — view list of paired devices, remove/unpair a device
5. **Connection Troubleshooting** — quick fixes for WiFi and Bluetooth issues

Live links: `connect.html`, `settings.html`

- [ ] **Step 4: Verify chapters 4-6**

Open browser, navigate to each chapter. Verify content renders correctly, steps are numbered, tips show, links work.

- [ ] **Step 5: Commit**

```bash
git add manual.html
git commit -m "feat: add chapter content for Gallery, Display, Connectivity"
```

---

### Task 7: Write chapter content — Lab, Settings, Troubleshooting

Write content for chapters 7-9.

**Files:**
- Modify: `manual.html`

**Context for content writing:**
- **Lab**: Read `lab.html` for Gazer (Art Blocks), PixelChain (ASCII), Hue sync, remote rendering
- **Settings**: Read `settings.html` for all sections: storage, IPFS, backup, security, thermal, CPU, updates
- **Troubleshooting**: Synthesize common issues from project knowledge

Note: Autoglyphs and CryptoPunks are easter-egg features (hidden by default). Omit from the manual.

- [ ] **Step 1: Write Lab chapter content**

`chapters['lab']` with 4 sections:
1. **Gazer** — paste an Art Blocks token URL, view live generative art, fullscreen mode
2. **PixelChain** — paste a PixelChain contract, view ASCII art in fullscreen with auto-hiding controls
3. **Hue Sync in Lab** — tap sun icon in fullscreen lab modes for real-time color matching with Hue lights
4. **Remote Rendering** — set up a Docker renderer on another machine, stream generative art to the Pi display

Live links: `lab.html`

- [ ] **Step 2: Write Settings chapter content**

`chapters['settings']` with 7 sections:
1. **Storage** — view disk usage and allocation, mount external USB/SD drive
2. **IPFS** — node status, pin management, gateway configuration
3. **Backup & Restore** — create backup archive, import from backup file, progress tracking
4. **Security** — device password, optional HTTPS setup
5. **Thermal** — temperature monitoring, fan mode selection (auto/silent/full)
6. **CPU Profiles** — eco/balanced/performance/maximum presets
7. **System Updates** — check for updates, automatic security updates toggle

Live links: `settings.html`

- [ ] **Step 3: Write Troubleshooting chapter content**

`chapters['troubleshooting']` with 7 sections:
1. **Can't Connect** — check WiFi status, try Bluetooth PAN, verify correct IP address
2. **Gallery Empty** — no art downloaded yet, navigate to Add or Library page
3. **Downloads Stuck** — check internet connection, verify IPFS status, retry download
4. **Display Issues** — color problems (check over_voltage), wrong rotation, screen flickering
5. **Storage Full** — check usage in Settings, remove unused art, connect external drive
6. **Restarting Services** — restart API, IPFS, or kiosk from Settings > System
7. **Diagnostic Report** — download system report from Settings > System for support

Use `.warning` callouts for destructive actions (delete art, factory reset).

Live links: `settings.html`

- [ ] **Step 4: Verify all 9 chapters render and navigate correctly**

Open browser. Click through all 9 chapter cards. Verify:
- Every chapter has content (no empty chapters)
- Section headings, steps, tips, warnings all render correctly
- Back button works from every chapter
- "Back to Manual" button works from every chapter
- Live links appear gold and functional in each chapter (if URL set)

- [ ] **Step 5: Commit**

```bash
git add manual.html
git commit -m "feat: add chapter content for Lab, Settings, Troubleshooting"
```

---

### Task 8: Replace Help & Guide section in settings.html

Replace the existing inline help content in `settings.html` with a single card linking to `manual.html`.

**Files:**
- Modify: `settings.html:5184-5632` (the `#section-help` section — runs from line 5185 to the closing `</section>` at approximately line 5632)

**Context:** The `#section-help` section contains 5+ `.settings-card` divs with inline First Setup, Getting Art Collections, Viewing Your Art, and more instructions. Replace ALL cards after the section header (keep the `<div class="section-header">` intact) with a single card pointing to the manual. Read the full section to find the closing `</section>` — do not stop at line 5340.

- [ ] **Step 1: Read current Help section boundaries**

Read `settings.html` starting at line 5184 through the closing `</section>` tag. Identify the exact range of content to replace: everything after the `</div>` closing the section-header, up to but not including `</section>`.

- [ ] **Step 2: Replace Help section content**

Keep: `<section class="settings-section" id="section-help">` and its `<div class="section-header"><h1>Help & Guide</h1><p>...</p></div>`.

Replace all `.settings-card` divs after the header with:

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

- [ ] **Step 3: Verify settings page**

Open `settings.html`, navigate to Help & Guide section. Verify:
- Section title "Help & Guide" still shows with subtitle
- Single card with centered description text
- "Open User Manual" button with gold border
- Button click navigates to `manual.html`
- No leftover old help content (First Setup, Getting Art, etc. are gone)

- [ ] **Step 4: Commit**

```bash
git add settings.html
git commit -m "feat: replace Help & Guide inline content with manual link"
```

---

### Task 9: Final polish and responsive testing

Final pass over both files. Verify responsive breakpoints, transitions, self-containment, and no console errors.

**Files:**
- Modify: `manual.html` (if fixes needed)

- [ ] **Step 1: Test phone viewport (375px wide)**

Open browser dev tools, set viewport to 375x812. Verify:
- Cards stack to 1 column
- Hero text scales appropriately
- URL input fits within padding
- Chapter content readable with adequate margins
- Back button visible and not overlapping frame
- No horizontal overflow or content clipping

- [ ] **Step 2: Test tablet viewport (768px wide)**

Set viewport to 768x1024. Verify:
- Cards in 2 columns
- Comfortable spacing between cards and content

- [ ] **Step 3: Test desktop (1440px wide)**

Full width. Verify:
- Cards in 3 columns
- Content max-width 1200px centered
- Decorative frame visible at all sizes
- Hover effects work on cards

- [ ] **Step 4: Verify self-containment**

Disconnect from network (airplane mode or disable WiFi). Reload `manual.html`. Verify:
- Page renders fully (fonts load from base64)
- No failed resource loads in browser console
- All styling and icons intact
- JavaScript works (card clicks, URL input, transitions)

- [ ] **Step 5: Fix any issues found**

Apply fixes for any breakpoint, transition, or self-containment issues discovered.

- [ ] **Step 6: Final commit**

```bash
git add manual.html
git commit -m "fix: responsive polish and final adjustments for manual"
```
