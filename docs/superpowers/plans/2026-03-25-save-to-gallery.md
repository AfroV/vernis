# Atelier "Save to Gallery" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users permanently save Atelier generators (Gazer, PixelChain, Punk, Glyph, Burner) to the gallery slideshow as self-contained HTML files with embedded preview fallbacks.

**Architecture:** Backend endpoint creates a single `.html` file per generator in the NFT directory (`/opt/vernis/nfts/`). The HTML loads the live generator in an iframe when online and falls back to an embedded base64 preview image when offline. The thumbnail API is extended to extract previews from `<meta>` tags in these HTML files. All existing gallery infrastructure (slideshow, Manage Art, carousels, hide/show, delete) works without frontend changes — the spec lists `manage.html` as modified, but the backend thumbnail handler makes that unnecessary.

**Tech Stack:** Flask (Python backend), vanilla JS frontend, PIL for thumbnail resizing, base64 encoding

**Spec:** `docs/superpowers/specs/2026-03-25-atelier-save-to-gallery-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app.py` | Modify | New `POST /api/atelier/save-to-gallery` endpoint, extend glob extensions to include `html`, modify thumbnail API to handle `.html` files |
| `lab.html` | Modify | Add "Save to Gallery" bookmark buttons on all 5 card types + 5 fullscreen overlays, `saveToGallery()` function with preview capture |

No changes to `gallery.html` or `manage.html` — the backend thumbnail handler for `.html` files makes Manage Art work automatically via the existing `/api/thumbnail/<filename>` path.

---

### Task 1: Backend — `POST /api/atelier/save-to-gallery` endpoint

Creates the core API endpoint that validates input, fetches/receives preview images, generates thumbnail-sized meta preview, and writes the self-contained HTML file.

**Files:**
- Modify: `backend/app.py` (add new endpoint after the existing carousel endpoints, around line 3665)

**Reference:** Read the HTML template in the spec (lines 150-200) and the Generator URLs table (lines 110-117).

- [ ] **Step 1: Add the endpoint route and validation**

Add this after the carousel save endpoint (around line 3665) in `backend/app.py`:

```python
@app.route("/api/atelier/save-to-gallery", methods=["POST"])
def save_to_gallery():
    """Save an Atelier generator as an HTML file in the NFT directory"""
    import base64
    import re

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    gen_type = data.get("type", "")
    gen_id = data.get("id")
    name = data.get("name", "")
    preview_url = data.get("preview_url")
    preview_data = data.get("preview_data")

    # Validate type
    allowed_types = ["gazer", "pixelchain", "punk", "glyph", "burner"]
    if gen_type not in allowed_types:
        return jsonify({"error": "Invalid type"}), 400

    # Validate id
    try:
        gen_id = int(gen_id)
        if gen_id < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid id"}), 400

    # Validate preview_data if provided
    if preview_data:
        if not preview_data.startswith("data:image/"):
            return jsonify({"error": "Invalid preview data"}), 400
        if len(preview_data) > 5 * 1024 * 1024:
            return jsonify({"error": "Preview data too large (max 5MB)"}), 400

    # Check if already exists
    filename = f"{gen_type}-{gen_id}.html"
    filepath = NFT_DIR / filename
    if filepath.exists():
        return jsonify({"status": "exists", "filename": filename})

    # Build generator URL
    if gen_type == "gazer":
        contract = "0xa7d8d9ef8d8ce8992df33d8b8cf4aebabd5bd270"
        token_id = 215000000 + gen_id
        generator_url = f"https://generator.artblocks.io/{contract}/{token_id}"
    else:
        generator_url = f"http://localhost/lab.html?type={gen_type}&id={gen_id}&fullscreen=1"

    # Obtain preview as base64 data URI
    full_preview = None
    if preview_data:
        full_preview = preview_data
    elif preview_url:
        try:
            resp = requests.get(preview_url, timeout=15)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/png").split(";")[0]
            b64 = base64.b64encode(resp.content).decode("ascii")
            full_preview = f"data:{content_type};base64,{b64}"
        except Exception:
            full_preview = None

    # SVG placeholder if no preview available (sanitize name to prevent XSS)
    if not full_preview:
        safe_svg_name = re.sub(r'[^a-zA-Z0-9 #]', '', name)
        full_preview = "data:image/svg+xml;base64," + base64.b64encode(
            b'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400">'
            b'<rect width="400" height="400" fill="#1a1a1a"/>'
            b'<text x="200" y="200" text-anchor="middle" fill="#666" font-size="48" font-family="sans-serif">'
            + safe_svg_name.encode("utf-8") +
            b'</text></svg>'
        ).decode("ascii")

    # Generate thumbnail-sized preview for meta tag (max 300px, JPEG Q70)
    thumb_preview = full_preview
    try:
        from PIL import Image
        import io
        if not full_preview.startswith("data:image/svg"):
            header, b64data = full_preview.split(",", 1)
            img_bytes = base64.b64decode(b64data)
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (0, 0, 0))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((300, 300), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=70)
            thumb_preview = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        thumb_preview = full_preview

    # Escape for HTML attributes
    safe_name = name.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")

    # Build HTML
    html_content = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator-type" content="{gen_type}">
<meta name="generator-id" content="{gen_id}">
<meta name="generator-name" content="{safe_name}">
<meta name="generator-preview" content="{thumb_preview}">
<style>
  * {{ margin: 0; padding: 0; }}
  body {{ background: #000; overflow: hidden; }}
  iframe, img {{ position: absolute; top: 0; left: 0; width: 100vw; height: 100vh; border: none; }}
  img {{ object-fit: contain; }}
  .hidden {{ display: none; }}
</style>
</head>
<body>
<img id="fb" src="{full_preview}" alt="{safe_name}">
<iframe id="gen" class="hidden" src="{generator_url}" allow="autoplay"></iframe>
<script>
  var gen = document.getElementById('gen');
  var fb = document.getElementById('fb');
  var loaded = false;
  gen.addEventListener('load', function() {{
    loaded = true;
    fb.classList.add('hidden');
    gen.classList.remove('hidden');
  }});
  gen.classList.remove('hidden');
  fb.classList.remove('hidden');
  gen.style.opacity = '0';
  setTimeout(function() {{
    if (loaded) {{
      gen.style.opacity = '1';
      fb.classList.add('hidden');
    }} else {{
      gen.classList.add('hidden');
    }}
  }}, 8000);
</script>
</body>
</html>'''

    # Write file
    NFT_DIR.mkdir(parents=True, exist_ok=True)
    filepath.write_text(html_content, encoding="utf-8")

    return jsonify({"status": "saved", "filename": filename})
```

- [ ] **Step 2: Verify endpoint placement**

Confirm the endpoint is placed correctly after the carousel endpoints. Check that `NFT_DIR`, `request`, `jsonify`, and `requests` are already imported at the top of `app.py` (they are — `requests` is imported globally at line 12).

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat: add POST /api/atelier/save-to-gallery endpoint"
```

---

### Task 2: Backend — Extend glob extensions and thumbnail API

Add `'html'` to all NFT file enumeration loops and teach the thumbnail API to extract embedded previews from `.html` files.

**Files:**
- Modify: `backend/app.py`
  - Line 516, 522: `pinned_art()` — two loops
  - Line 596: `download_progress()`
  - Line 3519: `nft_list_detailed()`
  - Line 4053: `scan_nft_metadata()`
  - Line 5129: `setup_status()`
  - Line 9015-9086: `get_thumbnail()` — add `.html` handler
  - Line 9098: `generate_all_thumbnails()` — already excludes `html`, no change needed

- [ ] **Step 1: Add `'html'` to 6 glob extension loops**

In each of these locations, change from:
```python
for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4']:
```
to:
```python
for ext in ['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'mp4', 'html']:
```

Locations (use find-and-replace on the old string — it appears at these lines):
1. **Line 516** — `pinned_art()`, internal storage loop
2. **Line 522** — `pinned_art()`, external storage loop
3. **Line 596** — `download_progress()`
4. **Line 3519** — `nft_list_detailed()`
5. **Line 4053** — `scan_nft_metadata()`
6. **Line 5129** — `setup_status()`

**Do NOT modify** line 9098 (`generate_all_thumbnails`) — its loop is `['jpg', 'jpeg', 'png', 'gif', 'webp']` (already excludes `html` and `mp4`), and it uses `PIL.Image.open()` which would crash on HTML files.

- [ ] **Step 2: Add `.html` handler to thumbnail API**

In `get_thumbnail()` (line 9016), add this handler **after** the video handler (line 9034, `return Response(svg, mimetype='image/svg+xml')`) and **before** the cached thumbnail check (line 9037, `if thumbnail_path.exists()`):

```python
        # Handle HTML generator files - extract preview from meta tag
        if filename.lower().endswith('.html'):
            import re
            import base64 as b64mod
            try:
                html_text = original_path.read_text(encoding='utf-8')
                match = re.search(r'<meta\s+name="generator-preview"\s+content="([^"]+)"', html_text)
                if match:
                    data_uri = match.group(1)
                    header, b64data = data_uri.split(',', 1)
                    img_bytes = b64mod.b64decode(b64data)
                    mime = header.split(':')[1].split(';')[0] if ':' in header else 'image/jpeg'
                    return Response(img_bytes, mimetype=mime)
            except Exception:
                pass
            svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
                <rect width="200" height="200" fill="#1a1a1a"/>
                <text x="100" y="105" text-anchor="middle" fill="#666" font-size="12">Generator</text>
            </svg>'''
            return Response(svg, mimetype='image/svg+xml')
```

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat: extend glob extensions for html, add html thumbnail handler"
```

---

### Task 3: Frontend — `saveToGallery()` function and preview capture helpers

Add the core JavaScript function that handles all 5 content types, captures previews, and calls the backend.

**Files:**
- Modify: `lab.html` — add function near `sendToFrame()` (around line 4402)

**Reference:**
- `sendToFrame()` at line 4339 uses `idMap` for type→input-ID mapping
- Input IDs: `gazer-number`, `pxc-number`, `punk-number`, `glyph-number`, `burner-number`
- PixelChain canvas: `id="pxc-canvas"` (line 1461)
- Punk image: `id="punk-image"` (line 1760) — `<img>` element with SVG src
- Glyph text: `id="glyph-art"` (line 1898) — `<pre>` element
- Toast function: `showEasterEggToast()` (line 4651)
- Gazer constants: `ART_BLOCKS_CONTRACT` (line 2668), `BASE_TOKEN_ID` (line 2670)

- [ ] **Step 1: Add the `saveToGallery()` function**

Add this after `sendToFrame()` (after line 4402):

```javascript
function saveToGallery(type) {
  var idMap = {
    punk: "punk-number",
    glyph: "glyph-number",
    pixelchain: "pxc-number",
    gazer: "gazer-number",
    burner: "burner-number",
  };
  var nameMap = {
    punk: "Punk",
    glyph: "Glyph",
    pixelchain: "PixelChain",
    gazer: "Gazer",
    burner: "Burner",
  };
  var inputEl = document.getElementById(idMap[type]);
  if (!inputEl) return;
  var id = parseInt(inputEl.value) || 0;
  var name = nameMap[type] + " #" + id;

  var body = { type: type, id: id, name: name };

  if (type === "gazer") {
    var tokenId = 215000000 + id;
    body.preview_url = "https://media.artblocks.io/" + tokenId + ".png";
    doSaveToGallery(body, name);
  } else if (type === "pixelchain") {
    var canvas = document.getElementById("pxc-canvas");
    if (canvas) {
      body.preview_data = canvas.toDataURL("image/png");
    }
    doSaveToGallery(body, name);
  } else if (type === "punk") {
    capturePunkPreview(function (dataUrl) {
      if (dataUrl) body.preview_data = dataUrl;
      doSaveToGallery(body, name);
    });
    return;
  } else if (type === "glyph") {
    captureGlyphPreview(function (dataUrl) {
      if (dataUrl) body.preview_data = dataUrl;
      doSaveToGallery(body, name);
    });
    return;
  } else {
    doSaveToGallery(body, name);
  }
}

function doSaveToGallery(body, name) {
  fetch("/api/atelier/save-to-gallery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.status === "saved") {
        showEasterEggToast(name + " added to Gallery");
      } else if (data.status === "exists") {
        showEasterEggToast(name + " is already in your Gallery");
      } else if (data.error) {
        showEasterEggToast("Error: " + data.error);
      }
    })
    .catch(function () {
      showEasterEggToast("Failed to save — try again");
    });
}

function capturePunkPreview(callback) {
  var img = document.getElementById("punk-image");
  if (!img || !img.src) return callback(null);
  var canvas = document.createElement("canvas");
  canvas.width = 300;
  canvas.height = 300;
  var ctx = canvas.getContext("2d");
  var tempImg = new Image();
  tempImg.crossOrigin = "anonymous";
  tempImg.onload = function () {
    ctx.drawImage(tempImg, 0, 0, 300, 300);
    callback(canvas.toDataURL("image/png"));
  };
  tempImg.onerror = function () { callback(null); };
  tempImg.src = img.src;
}

function captureGlyphPreview(callback) {
  var pre = document.getElementById("glyph-art");
  if (!pre || !pre.textContent.trim()) return callback(null);
  var canvas = document.createElement("canvas");
  canvas.width = 300;
  canvas.height = 300;
  var ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, 300, 300);
  ctx.fillStyle = "#000000";
  ctx.font = "6px monospace";
  var lines = pre.textContent.split("\n");
  for (var i = 0; i < lines.length; i++) {
    ctx.fillText(lines[i], 4, 10 + i * 6);
  }
  callback(canvas.toDataURL("image/png"));
}
```

- [ ] **Step 2: Commit**

```bash
git add lab.html
git commit -m "feat: add saveToGallery() function with preview capture"
```

---

### Task 4: Frontend — Add Save to Gallery buttons on all cards and enable logic

Add the bookmark button to each of the 5 Atelier card action rows, and wire up enable/disable gating to match the existing Send to Frame buttons.

**Files:**
- Modify: `lab.html`

**Bookmark SVG icon** (same for all buttons):
```html
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
</svg>
```

- [ ] **Step 1: Add bookmark button to Gazer card**

After the Gazer "Send to Frame" button (line 1295, before the Fullscreen button at line 1296), insert:

```html
              <button
                class="card-action-btn"
                id="gazer-card-save-btn"
                title="Save to Gallery"
                onclick="saveToGallery('gazer')"
                disabled
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
              </button>
```

- [ ] **Step 2: Add bookmark button to PixelChain card**

After the PixelChain "Send to Frame" button (line 1411, before the Fullscreen button), insert:

```html
              <button
                class="card-action-btn"
                id="pxc-card-save-btn"
                title="Save to Gallery"
                onclick="saveToGallery('pixelchain')"
                disabled
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
              </button>
```

- [ ] **Step 3: Add bookmark button to Punk card**

After the Punk "Send to Frame" button (line 1717, before the Fullscreen button), insert:

```html
              <button
                class="card-action-btn"
                id="punk-card-save-btn"
                title="Save to Gallery"
                onclick="saveToGallery('punk')"
                disabled
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
              </button>
```

- [ ] **Step 4: Add bookmark button to Glyph card**

After the Glyph "Send to Frame" button (line 1859, before the Fullscreen button), insert:

```html
              <button
                class="card-action-btn"
                id="glyph-card-save-btn"
                title="Save to Gallery"
                onclick="saveToGallery('glyph')"
                disabled
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
              </button>
```

- [ ] **Step 5: Add bookmark button to Burner card**

After the Burner "Send to Frame" button (line 2004, before the Fullscreen button), insert:

```html
              <button
                class="card-action-btn"
                id="burner-card-save-btn"
                title="Save to Gallery"
                onclick="saveToGallery('burner')"
                disabled
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
              </button>
```

- [ ] **Step 6: Enable save buttons alongside send buttons**

Add a `document.getElementById("...-card-save-btn").disabled = false;` line immediately after each existing send-button enable line. Here are the exact locations and code:

**Gazer** (line 2723 — uses cached variable `gazerCardSendBtn`):
```javascript
// After: gazerCardSendBtn.disabled = false;
// Add:
document.getElementById("gazer-card-save-btn").disabled = false;
```

**PixelChain** (line 3094):
```javascript
// After: document.getElementById("pxc-card-send-btn").disabled = false;
// Add:
document.getElementById("pxc-card-save-btn").disabled = false;
```

**Punk** (lines 4213 AND 4226 — two load paths):
```javascript
// After each: document.getElementById("punk-card-send-btn").disabled = false;
// Add:
document.getElementById("punk-card-save-btn").disabled = false;
```

**Glyph** (line 4271):
```javascript
// After: document.getElementById("glyph-card-send-btn").disabled = false;
// Add:
document.getElementById("glyph-card-save-btn").disabled = false;
```

**Burner** (line 3833):
```javascript
// After: document.getElementById("burner-card-send-btn").disabled = false;
// Add:
document.getElementById("burner-card-save-btn").disabled = false;
```

- [ ] **Step 7: Commit**

```bash
git add lab.html
git commit -m "feat: add Save to Gallery bookmark buttons on all Atelier cards"
```

---

### Task 5: Frontend — Add Save to Gallery buttons on all fullscreen overlays

Add the bookmark button to each of the 5 fullscreen overlay control rows. **Important layout notes:**
- Gazer and PixelChain fullscreens use **flex containers** — buttons flow automatically, no positioning needed
- Punk and Glyph fullscreens use **absolute positioning** — each button needs explicit `style="top: ...; left/right: ..."`
- Burner fullscreen uses a **flex container** — no positioning needed

**Files:**
- Modify: `lab.html`

**Existing Punk fullscreen button positions** (all `top: 20px`):
- Close: `right: 20px`
- Hue: `right: 80px`
- Send: `left: 20px`
- → New save button: `left: 80px` (next to send)

**Existing Glyph fullscreen button positions** (all `top: 20px`):
- Close: `right: 20px`
- Hue: `right: 80px`
- Send: `left: 20px`
- → New save button: `left: 80px` (next to send)

- [ ] **Step 1: Add bookmark button to Gazer fullscreen**

Before the close button in the Gazer fullscreen controls (before line 2455, after the send button), insert:

```html
        <button
          class="fullscreen-btn-control"
          id="gazer-fs-save"
          title="Save to Gallery"
          onclick="saveToGallery('gazer')"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
          </svg>
        </button>
```

- [ ] **Step 2: Add bookmark button to PixelChain fullscreen**

Before the close button in PixelChain fullscreen controls (before line 2523, after the send button), insert:

```html
            <button
              class="pxc-fs-btn fs-btn"
              id="pxc-fs-save-btn"
              title="Save to Gallery"
              onclick="saveToGallery('pixelchain')"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
              </svg>
            </button>
```

- [ ] **Step 3: Add bookmark button to Punk fullscreen**

After the Punk send button (after line 2232), insert with **explicit absolute positioning** at `top: 20px; left: 80px`:

```html
      <button
        class="fs-btn"
        id="punk-fs-save"
        onclick="saveToGallery('punk')"
        style="top: 20px; left: 80px"
        title="Save to Gallery"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
```

- [ ] **Step 4: Add bookmark button to Glyph fullscreen**

After the Glyph send button (after line 2314), insert with **explicit absolute positioning** at `top: 20px; left: 80px`:

```html
      <button
        class="fs-btn fs-btn-light"
        id="glyph-fs-save"
        onclick="saveToGallery('glyph')"
        style="top: 20px; left: 80px"
        title="Save to Gallery"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
```

- [ ] **Step 5: Add bookmark button to Burner fullscreen**

After the Burner send button (after line 2386), insert:

```html
            <button
              class="fs-btn"
              id="burner-fs-save"
              title="Save to Gallery"
              onclick="saveToGallery('burner'); startBurnerControlsTimer();"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
              </svg>
            </button>
```

Note: Burner send button also calls `startBurnerControlsTimer()` to reset the auto-hide timer — do the same for the save button.

- [ ] **Step 6: Commit**

```bash
git add lab.html
git commit -m "feat: add Save to Gallery buttons on all fullscreen overlays"
```

---

### Task 6: Deploy and Manual Testing

Deploy to Pi and run through the spec's testing checklist.

- [ ] **Step 1: Deploy to Pi**

```bash
# Deploy app.py to backend
cat backend/app.py | sshpass -p '<device-password>' ssh afrol@10.0.0.28 "cat > /tmp/app.py && echo '<device-password>' | sudo -S mv /tmp/app.py /opt/vernis/"

# Restart Flask
sshpass -p '<device-password>' ssh afrol@10.0.0.28 "echo '<device-password>' | sudo -S systemctl restart vernis-api"

# Deploy lab.html to web UI
cat lab.html | sshpass -p '<device-password>' ssh afrol@10.0.0.28 "cat > /tmp/lab.html && echo '<device-password>' | sudo -S mv /tmp/lab.html /var/www/vernis/"
```

- [ ] **Step 2: Test Gazer save flow**

1. Open Atelier, load Gazer #247
2. Tap save bookmark on card → verify toast "Gazer #247 added to Gallery"
3. Verify file exists: `ls /opt/vernis/nfts/gazer-247.html`
4. Tap save again → verify "Gazer #247 is already in your Gallery"
5. Open fullscreen, tap save bookmark → verify same "already" toast

- [ ] **Step 3: Test gallery and Manage Art integration**

1. Open gallery → verify Gazer #247 appears as live iframe
2. Open Manage Art → verify thumbnail shows the Art Blocks preview image
3. Hide Gazer #247 → verify excluded from gallery
4. Unhide and delete → verify `.html` file removed

- [ ] **Step 4: Test PixelChain save**

1. Load PixelChain #42
2. Tap save → verify canvas preview captured and toast shown
3. Check Manage Art thumbnail

- [ ] **Step 5: Test offline fallback**

1. Save a Gazer, disconnect WiFi
2. Open gallery → verify fallback preview image shows instead of blank iframe

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete Atelier Save to Gallery feature"
```
