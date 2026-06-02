# Atelier "Save to Gallery" — Design Spec

## Problem

Users can explore generative art in the Atelier (Gazer, PixelChain, etc.) but have no way to permanently add pieces to their gallery slideshow. "Send to Frame" is a one-shot override that navigates the Pi's browser — it doesn't persist. A customer with 8 Gazers has no way to include them in their daily art rotation alongside their IPFS-downloaded artworks.

## Solution

Add a "Save to Gallery" button to every Atelier card and fullscreen mode. When tapped, the backend creates a single `.html` file in the NFT directory. This file:

1. Loads the live generator in an iframe when online
2. Falls back to an embedded base64 preview image when offline
3. Contains `<meta>` tags with type, id, and name for identification

One file per saved generator. No companion images, no separate data stores. The file integrates with the existing NFT system — slideshow, Manage Art, carousels, hide/show, delete.

## Users

- **Collector**: Owns specific tokens (e.g., 8 Gazers) and wants them in the daily slideshow rotation
- **Explorer**: Discovers pieces in the Atelier and wants to save favorites for later viewing

## Constraints

- Must work with all Atelier content types (Gazer, PixelChain, future additions)
- Gallery already handles `.html` files in iframes — no gallery changes needed
- The `nft_list_detailed` endpoint must be extended to glob `.html` files
- Generator URLs require internet — offline fallback shows embedded preview image
- No new data stores — single `.html` file per generator in the existing NFT directory
- Preview image embedded as base64 data URI inside the HTML file (avoids iframe sandbox origin issues — gallery sets `sandbox="allow-scripts"` without `allow-same-origin`, so relative/absolute URL references from inside the iframe would fail)
- `preview_data` field limited to 5MB max; backend validates it starts with `data:image/`
- Non-Gazer generator URLs use `http://localhost/lab.html?...` — these require the Vernis web server to be running. This is always true on the Pi in normal operation.

---

## Files Changed

| File | Action | Responsibility |
|------|--------|----------------|
| `lab.html` | Modify | Add "Save to Gallery" button on cards + fullscreen overlays, JS save function |
| `backend/app.py` | Modify | New `POST /api/atelier/save-to-gallery` endpoint, extend `nft_list_detailed` glob, modify thumbnail API for `.html` files, modify delete to be aware of single-file generators |
| `manage.html` | Modify | Add thumbnail handling for `.html` files (extract preview from HTML or use generator icon) |

---

## User Flow

1. User enters a token number in the Atelier (e.g., Gazer #247)
2. Static preview loads in the card
3. User taps the save icon (bookmark) on the card — or taps it in fullscreen overlay
4. `POST /api/atelier/save-to-gallery` with type, id, preview data, and metadata
5. Backend creates `gazer-247.html` with embedded preview
6. Toast: "Gazer #247 added to Gallery"
7. If file already exists: Toast: "Gazer #247 is already in your Gallery"
8. Artwork now appears in slideshow and Manage Art

---

## Backend Endpoint

### `POST /api/atelier/save-to-gallery`

**Request body:**

```json
{
  "type": "gazer",
  "id": 247,
  "name": "Gazer #247",
  "preview_url": "https://media.artblocks.io/215000247.png"
}
```

For Gazer, the backend fetches the preview from `preview_url` and converts it to base64 for embedding.

For content types where the preview is rendered client-side (PixelChain, Punk, Glyph), the frontend captures a canvas `dataURL` and sends it directly:

```json
{
  "type": "pixelchain",
  "id": 42,
  "name": "PixelChain #42",
  "preview_data": "data:image/png;base64,iVBOR..."
}
```

**Backend logic:**

1. Validate `type` is in allowed list (`gazer`, `pixelchain`, `punk`, `glyph`, `burner`)
2. Validate `id` is a non-negative integer
3. If `preview_data` provided: validate it starts with `data:image/` and is under 5MB
4. Determine filename: `{type}-{id}.html` (e.g., `gazer-247.html`)
5. Check if file already exists in NFT directory → return `{ "status": "exists", "filename": "gazer-247.html" }`
6. Obtain the preview image as a base64 data URI:
   - If `preview_url` provided: fetch the image, convert to `data:image/png;base64,...`
   - If `preview_data` provided: use directly
   - If neither or fetch fails: use a small inline SVG placeholder (generic artwork icon)
7. Build the generator URL based on type and id (see Generator URLs section)
8. Generate the HTML file from the template (see HTML Template section)
9. Write the HTML file to the NFT directory
10. Return `{ "status": "saved", "filename": "gazer-247.html" }`

**Error handling:**
- Preview download failure: use the SVG placeholder — the artwork still works live when online
- Invalid type: return 400 `{ "error": "Invalid type" }`
- Invalid id: return 400 `{ "error": "Invalid id" }`
- `preview_data` too large: return 400 `{ "error": "Preview data too large (max 5MB)" }`

### Generator URLs by Type

| Type | Generator URL | Preview Source |
|------|---------------|----------------|
| `gazer` | `https://generator.artblocks.io/0xa7d8d9ef8d8ce8992df33d8b8cf4aebabd5bd270/{215000000 + id}` | Server fetches `https://media.artblocks.io/{215000000 + id}.png`, converts to base64 |
| `pixelchain` | `http://localhost/lab.html?type=pixelchain&id={id}&fullscreen=1` | Frontend sends canvas `toDataURL()` as `preview_data` |
| `punk` | `http://localhost/lab.html?type=punk&id={id}&fullscreen=1` | Frontend sends SVG-to-canvas `toDataURL()` as `preview_data` |
| `glyph` | `http://localhost/lab.html?type=glyph&id={id}&fullscreen=1` | Frontend sends SVG-to-canvas `toDataURL()` as `preview_data` |
| `burner` | `http://localhost/lab.html?type=burner&id={id}&fullscreen=1` | No preview — backend uses SVG placeholder (cross-origin iframe cannot be captured) |

Note: Punks and Glyphs are easter-egg features. The save button is added universally — if the section is visible, the button is there.

### Extend File Glob Extensions

Add `'html'` to the glob extensions list in **all** functions that enumerate NFT files. The codebase has multiple `for ext in [...]` loops:

1. **`nft_list_detailed()`** — primary gallery file list (required)
2. **`/api/pinned-art`** — alternate gallery listing used by some code paths (required)
3. **Metadata scan** — so generators appear in metadata/collection filters (required)
4. **Download progress NFT count** — minor, for accurate file counts
5. **Setup check `has_art`** — minor, so generators count as "has art"

Search for `for ext in ['jpg'` in `app.py` and add `'html'` to each occurrence, **except** `generate_all_thumbnails()` which uses `PIL.Image.open()` directly — skip `.html` files there or add a guard.

```python
for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'html']:
```

This makes saved generators appear in all gallery file lists automatically.

### HTTP Status Codes

- `"status": "saved"` → HTTP 200
- `"status": "exists"` → HTTP 200 (frontend differentiates by the `status` field)
- Validation errors → HTTP 400

---

## HTML Template

Each saved generator is a single self-contained HTML file. The preview image is embedded as a base64 data URI, making the fallback fully functional inside the gallery's sandboxed iframe (`sandbox="allow-scripts"` without `allow-same-origin`).

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator-type" content="{type}">
<meta name="generator-id" content="{id}">
<meta name="generator-name" content="{name}">
<meta name="generator-preview" content="{base64_data_uri}">
<style>
  * { margin: 0; padding: 0; }
  body { background: #000; overflow: hidden; }
  iframe, img { position: absolute; top: 0; left: 0; width: 100vw; height: 100vh; border: none; }
  img { object-fit: contain; }
  .hidden { display: none; }
</style>
</head>
<body>
<img id="fb" src="{base64_data_uri}" alt="{name}">
<iframe id="gen" class="hidden" src="{generator_url}" allow="autoplay"></iframe>
<script>
  var gen = document.getElementById('gen');
  var fb = document.getElementById('fb');
  var loaded = false;
  // Listen for successful iframe load
  gen.addEventListener('load', function() {
    // The load event fires even for error pages, so we check after a short delay
    // to let the content initialize. For cross-origin iframes we can't inspect content,
    // but a successful load means the server responded.
    loaded = true;
    fb.classList.add('hidden');
    gen.classList.remove('hidden');
  });
  // Show iframe after a brief delay to let it attempt loading
  // If it hasn't loaded by 8 seconds, keep showing the preview
  gen.classList.remove('hidden');
  fb.classList.remove('hidden');
  gen.style.opacity = '0';
  setTimeout(function() {
    if (loaded) {
      gen.style.opacity = '1';
      fb.classList.add('hidden');
    } else {
      gen.classList.add('hidden');
    }
  }, 8000);
</script>
</body>
</html>
```

**How it works:**
1. Page loads showing the preview image immediately (good perceived performance)
2. Iframe starts loading the generator URL in the background (invisible, `opacity: 0`)
3. If the iframe loads successfully within 8 seconds: hide preview, show live generator
4. If it doesn't load (offline, DNS timeout, etc.): hide iframe, keep showing preview
5. The base64 preview image works regardless of sandbox restrictions or network state

The `<meta name="generator-preview">` tag stores a thumbnail-sized version of the preview (resized to max 300px wide, JPEG quality 70) so the thumbnail API can extract it quickly without parsing a large file. The full-resolution preview is only in the `<img src>` tag. For Gazer previews fetched by the server, the backend generates both sizes. For client-sent `preview_data`, the backend resizes to create the thumbnail version.

---

## Lab UI Changes

### Card Button

Add a "Save to Gallery" button to each Atelier card's action button row. Same `.card-action-btn` class as "Send to Frame" and "Fullscreen". Uses a bookmark SVG icon.

```html
<button class="card-action-btn" title="Save to Gallery" onclick="saveToGallery('gazer')">
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
  </svg>
</button>
```

The button is disabled until a token preview has loaded (same gating as "Send to Frame" and "Fullscreen").

### Fullscreen Button

Add the same bookmark icon button to each fullscreen overlay's control row. Use the same button class as the existing controls in each section:
- **Gazer fullscreen**: uses `.fullscreen-btn-control` class
- **PixelChain fullscreen**: uses `.pxc-fs-btn` / `.fs-btn` classes
- **Punk/Glyph/Burner fullscreen**: uses `.fs-btn` class

Match the existing pattern per section.

### `saveToGallery(type)` Function

```javascript
function saveToGallery(type) {
  // 1. Determine id from the active input for this type
  // 2. Determine name (e.g., "Gazer #247")
  // 3. Build request body:
  //    For Gazer: { type, id, name, preview_url } — server fetches the image
  //    For PixelChain: { type, id, name, preview_data } — capture canvas.toDataURL()
  //    For Punk/Glyph: { type, id, name, preview_data } — SVG to canvas to dataURL
  //    For Burner: { type, id, name } — no preview, server uses placeholder
  // 4. POST /api/atelier/save-to-gallery
  // 5. On success (status "saved"): showInfo("{name} added to Gallery")
  // 6. On exists (status "exists"): showInfo("{name} is already in your Gallery")
  // 7. On error: showError("Failed to save — try again")
}
```

### Preview Capture for Non-Gazer Types

- **PixelChain**: The token is already rendered in a `<canvas>` element. Call `canvas.toDataURL('image/png')` and send as `preview_data`.
- **Punk**: SVG is rendered inline. Create a temporary canvas, draw the SVG via `drawImage()` with a blob URL, call `toDataURL()`.
- **Glyph**: Same approach — SVG to canvas to `dataURL`.
- **Burner**: iframe content cannot be captured cross-origin. Send no preview — backend uses a generic SVG placeholder icon.

---

## Gallery Behavior

No changes needed to `gallery.html`. The gallery already:
- Loads `.html` files in `<iframe sandbox="allow-scripts">` elements
- Shows an "interact" button for iframe content

**Auto-advance note:** The gallery intentionally pauses auto-advance for `.html` files — the slideshow stops on a saved generator until the user taps next. This is desirable behavior: live generative art is meant to be watched, not skipped after 30 seconds. Users who want to continue can tap next or use the "interact" button.

The saved HTML files will be served at `/nfts/gazer-247.html` and appear in the file list from `nft-list-detailed`. The embedded fallback handles the sandbox restriction.

---

## Manage Art Changes

### Thumbnail Handling

The existing thumbnail API (`/api/thumbnail/<filename>`) opens files with PIL, which fails for `.html` files. Add a handler:

When `filename` ends with `.html`:
1. Read the file and extract the `<meta name="generator-preview" content="...">` tag value
2. If found: decode the base64 data URI, return as image response
3. If not found: return the default placeholder SVG

This keeps the existing thumbnail endpoint working for all file types.

### Display in Grid

`.html` files appear in the grid like any other artwork. The thumbnail comes from the embedded preview (via the modified thumbnail API). No changes needed to `renderNFTs()` — the existing `<img src="/api/thumbnail/{filename}">` path works once the backend handles `.html`.

### Delete

The delete endpoint (`nft_delete`) only needs to delete the single `.html` file — there is no companion image to clean up. No changes needed to the delete logic.

---

## Testing

1. Open Atelier, load Gazer #247, tap save button on card → verify toast, verify `.html` file created in NFT dir
2. Open Atelier, go fullscreen on Gazer #247, tap save button → verify toast
3. Try saving same Gazer again → verify "already in Gallery" toast
4. Open gallery → verify Gazer #247 appears in slideshow as live iframe
5. Open Manage Art → verify Gazer #247 has preview thumbnail (extracted from embedded base64)
6. Hide Gazer #247 in Manage Art → verify it's excluded from slideshow
7. Delete Gazer #247 in Manage Art → verify `.html` file removed, no orphaned files
8. Add Gazer to a carousel → verify it persists across load/save
9. Disconnect WiFi → open gallery with saved Gazer → verify fallback shows embedded preview image (not a blank iframe)
10. Test PixelChain save → verify canvas preview captured, embedded, and displayed in Manage Art
11. Verify no duplicate entries — only the `.html` file appears in Manage Art and gallery (not a separate preview image)
