# Apple HomeView integration — research

**Status:** path (b) is built, behind a feature flag that is off by default. The Shortcut still has to be published (see "Building and publishing the Shortcut").
**Researched:** 2026-10-15 (HomeView announced 2026-10-13, ships 2026-11-13 —
nobody has hands-on access yet, so every device-behaviour claim below comes
from Apple's press material and specs, not from testing).

## Goal

Let a Vernis owner see the NFTs from their wallet on an Apple HomeView, as the
photo-frame / idle slideshow, without changing how Vernis itself displays art
and without touching the IPFS node.

## What HomeView actually is (verified facts)

| | Source |
|---|---|
| 7" diagonal Liquid Retina, **1088 × 1088 px, square (1:1)**, 220 ppi | Apple tech specs, Macworld |
| A18, HomeView software 27.2, needs iPhone on iOS 27.2+ | Apple newsroom, specs |
| **No App Store.** Built-in apps only (incl. Safari, Home, Photos face); "third-party audio and video apps" run *from a nearby iPhone* | Apple specs, Macworld |
| Photos face / living photo frame is fed by a **shared iCloud album** ("a living photo frame that loved ones near and far can help fill") | Apple newsroom |
| AirPlay is listed **only as "Multiroom audio with AirPlay"**. Nothing about receiving AirPlay video, photos or screen mirroring | Apple tech specs |

Two corrections to the brief: the screen is 7" diagonal (≈ 5" per side), not
~6"; and the press material only promises **shared** albums as the photo-frame
source — whether a normal (non-shared) album or the whole library can also be
picked is not stated. Treat "shared album" as the only guaranteed input until
someone has a device.

**Target export format:** square JPEG, **2048 × 2048**. 1088 is the native
panel size, but iCloud Shared Albums resize photos to 2048 px on the long
edge anyway, so 2048 is the largest size that survives. It also leaves
headroom if Photos crops or zooms (a Portrait-style depth effect is mentioned).

## Options

### a) Vernis writes to a shared iCloud album directly (from Linux)

**There is no official API.** An Apple engineer stated it plainly: "No, there is
no API to post to Shared Albums" (Apple Developer Forums, thread 717066).

The only Linux route is the unofficial `pyicloud` library (actively maintained
fork `timlaing/pyicloud`, v2026.10.0 released 2026-10-12):

- **It can upload — but only to the private library and its normal albums**
  (`api.photos.upload(path, album="…")`), JPEG only, via Apple's
  `photosupload` web service.
- **Shared albums (shared streams) are on a separate "legacy adapter".** The
  docs describe it for reading only; no upload/post to a shared stream is
  documented. So pyicloud **cannot do what HomeView needs** today.
- Even the private-album upload would need the owner's Apple ID password and a
  2FA-trusted session stored on the Pi. Per pyicloud's own docs, the trusted
  session expires (historically ~2 months) and must be re-confirmed with a
  2FA code. Accounts with Advanced Data Protection need "Access iCloud Data on
  the Web" turned on, or web-based access fails.
- **Terms:** the iCloud Terms of Service, section V.B(10), forbid
  "accessing the Service through any automated means, like scripts or web
  crawlers". A headless Pi logging into iCloud with the owner's credentials is
  exactly that. Section IV.A also says not to share account credentials.

| Feasibility | Stability | Apple terms |
|---|---|---|
| ❌ Can't post to shared albums at all | ❌ Reverse-engineered, breaks when Apple changes the web API; re-auth every few weeks | ❌ Violates iCloud ToS V.B(10) |

**Verdict: reject.** It also requires storing Apple credentials on the device,
which we don't want on a box that sits on a shelf in other people's homes.

### b) iPhone Shortcut pulls from a local Vernis endpoint

Vernis serves a curated set of square JPEGs on the LAN. A Shortcut on the
owner's iPhone fetches them (`Get Contents of URL` → JSON list → loop →
`Get Contents of URL` per image) and adds them to a shared album. Apple's own
software does the iCloud write, as the owner, on the owner's device.

What is known:

- **Fetching is fully automatable.** `Get Contents of URL` handles JSON and
  images; personal automations (Time of Day, Wi-Fi join, Charger, etc.) can be
  set to run without asking.
- **The shared-album step is the weak point.** The built-in
  `Post to Shared Album` action has historically had no album/message
  parameters and **always shows a compose sheet** (Matthew Cassinelli's action
  reference: "always prompts"). So a fully unattended run will stop at that
  sheet and wait for one tap. Apple added a `postToSharedAlbum` App Intents
  *schema* in iOS 18, but that is for third-party apps to implement, not a
  system action we can call. **Must be re-checked on iOS 27.2** — if the action
  has gained parameters, this becomes fully automatic.
- Fallback that is certainly fully automatic: `Save to Photo Album` into a
  **normal** album. Only useful if HomeView turns out to accept normal albums
  too (unknown until November).

**Chosen trigger: manual, from Settings (decided 2026-10-16).** A Vernis that
is already set up rarely gets new art, so a background automation isn't worth
its setup cost. Leaving it out removes the step we can't do for the owner
(automations can't be shared by link), and it avoids the question of whether the
compose sheet can appear while the phone is locked, because the owner is
already holding the phone.

Flow:

1. **Once:** turn HomeView on in Settings, install the Shortcut (iCloud link /
   QR on the card), allow access on first run, pick or create the shared album,
   and select that album on HomeView's Photos face. About 2–3 minutes.
2. **When there is new art:** the owner opens Vernis Settings on the iPhone.
   The HomeView card says e.g. "3 new pieces not sent". The owner taps **Send to
   HomeView**. Shortcuts opens, fetches only those pieces, and shows the
   compose sheet with the album already picked. The owner taps **Post**. Three
   taps in total, and no Shortcuts knowledge needed after setup.

The button is a `shortcuts://run-shortcut?name=…&input=text&text=<batch URL>`
link. It only works on an iPhone/iPad, so on a desktop or the kiosk the card
shows a QR code that opens the Settings page on the phone instead.

| Feasibility | Stability | Apple terms |
|---|---|---|
| ✅ Uses only public, supported features | ✅ Shortcuts actions and plain HTTP are stable; no Apple login on the Pi | ✅ Owner's own device, Apple's own app |

Costs/risks:

- One **Post** tap per send, possibly zero if iOS 27.2 has gained an album
  parameter (verify).
- The iPhone must be on the same LAN as Vernis (or we expose the endpoint
  through the existing HTTPS/remote setup — not proposed).
- Duplicates: Vernis remembers what has been sent, not the Shortcut (see the
  batch endpoint below). If the owner cancels the compose sheet, the card's
  **Send again** re-sends the last batch.
- Removing art from the album when the owner removes it from Vernis can't be
  automated (Shortcuts has no "remove from shared album" action). The card
  lists "removed from Vernis since last send" so the owner knows what to
  delete in Photos.
- The button opens the Shortcut by name. If the owner renames or deletes it,
  iOS shows an error, so the card keeps the install link visible.
- Security: the endpoint only exposes images the owner has already chosen to
  display, read-only. It must respect the Security modes (see below).

### c) AirPlay from Vernis to HomeView (pyatv)

- **HomeView is not documented as an AirPlay video/photo receiver.** Apple's
  specs list only "Multiroom audio with AirPlay"; no press or spec source
  mentions AirPlay video or screen mirroring *to* HomeView.
- pyatv's supported-features page lists `play_url` (AirPlay video) for
  **Apple TV** only, and `stream_file` for audio to HomePod/speakers. Photo
  sharing is part of the AirPlay protocol but is **not implemented** in pyatv.
- Even on a device that accepted AirPlay video, it's a live session: it takes
  over the screen while connected and isn't the idle photo-frame — the opposite
  of what we want.

| Feasibility | Stability | Apple terms |
|---|---|---|
| ❌ No evidence HomeView receives AirPlay video/photos | ⚠️ pyatv is solid for Apple TV, untested on HomeView | ✅ AirPlay is a public protocol |

**Verdict: reject for now.** Re-check once the device ships — if it turns out to
accept AirPlay video, it could be a separate "push this piece now" button, not
the idle slideshow.

### d) Not in the brief, worth noting

- **Safari on HomeView** pointing at the Vernis gallery page would work today
  with zero new code, but it isn't the idle face and probably times out back to
  the clock face. Fine as a manual "show my Vernis now" trick, not a solution.
- **Manual fallback with no Shortcut:** a Vernis page with "Download all as
  ZIP" / iOS share sheet → the owner adds them to a shared album by hand. Good
  enough as v0, and it reuses the same export endpoint as (b).

## Recommendation

**Build (b): a local, read-only export of curated 1:1 JPEGs plus an iPhone
Shortcut that pulls them into a shared album.** It's the only path that is
feasible today, is stable, and stays within Apple's terms. It keeps the Pi free
of Apple credentials and needs **no new Python dependencies**: Pillow already
handles the conversion, Flask serves the files.

Re-check before or right after building, once a HomeView ships (2026-11-13):

1. Does `Post to Shared Album` on iOS 27.2 take an album parameter and run
   without the compose sheet? (decides whether it's 0 or 1 tap per sync)
2. Can the Photos face use a normal album too? (if yes, `Save to Photo Album`
   makes it fully automatic)
3. How does the Photos face crop non-square or very small images, and does it
   show animated GIFs? (decides whether we need to letterbox/pad or can crop)
4. Does HomeView accept AirPlay video after all? (reopens option c as an extra)

## Implementation (built 2026-10-16)

Decisions: path (b), sent manually from Settings; **padded** to a square, never
cropped; source is the **gallery**, with **favorites** as an option; **2048 px**.
Off by default. All code is in the "HomeView export" section of
`backend/app.py`, the "Apple HomeView" card in `settings.html` (Display
section, below Preview Mode), and `tests/test_homeview.py`.

**Reuse (no duplication):**

- **Wallet fetching:** nothing new. Wallet collections are imported and kept
  in sync by the existing code into `NFT_DIR` / external storage. The export
  reads the files already on disk through `_art_listing_dirs()`, so it never
  makes its own OpenSea, RPC or IPFS calls.
- **Selection:** what the gallery shows, which is every art file minus
  `hidden-nfts.json`, or only the pieces in `favorites.json`. It uses the
  gallery's filename rule: no dotfiles (for example macOS `._` files on a NAS),
  and case-sensitive extensions. HTML art is included only if the first 4 KB
  contains a raster `generator-preview` image.
- **Conversion:** a sibling of the thumbnail pipeline. `_extract_frame` gained
  a `max_side` parameter for full-size video frames. The `generator-preview`
  decoding is now one helper, `_html_preview_image`, shared with the
  thumbnail route. Video, SVG and AVIF use the same `_external_decoder` slot
  as thumbnails, so a 416 MB Pi never runs two decoders at once.

**Files and endpoints:**

| | |
|---|---|
| `/opt/vernis/homeview-config.json` | `{"enabled": false, "source": "gallery" \| "favorites"}` |
| `/opt/vernis/homeview-state.json` | `sent` (id → filename), `last_batch`, and `fetched` (which pieces of the last batch the Shortcut has downloaded). `id` = sha256 of the filename, truncated; files are named by CID, so this stays stable across storage moves. **Kept when the feature is turned off**, so turning it back on doesn't re-post everything |
| `/opt/vernis/homeview-export/` | JPEGs of the **last batch only**; older ones are deleted when a new batch is made, so disk use is at most one batch. Emptied when the feature is turned off |
| `GET/POST /api/homeview/config` | Also returns `size`, `shortcut_name`, `shortcut_url` |
| `GET /api/homeview/status` | `not_sent`, `removed` (sent but no longer in the selection), `storage_offline`, `last_batch`, `batch_max`. While external storage is offline, `removed` is empty: those pieces are out of reach, not removed |
| `POST /api/homeview/batch` | Takes up to 50 pending pieces, marks them sent, pre-renders them in a background thread and returns `{batch, count, remaining}`. `{"resend": true}` returns the last batch again. "Pending" means pieces of the last batch the Shortcut **never downloaded** (for example, the owner tapped Send before installing it), then pieces never sent |
| `GET /api/homeview/manifest?batch=<id>` | The Shortcut's input: `{items: [{id, url, title, artist}]}` with absolute URLs (honours `X-Forwarded-Proto` when HTTPS is on) |
| `GET /api/homeview/image/<id>.jpg` | Only for pieces in the last batch that are still in the selection; renders on demand if the background render hasn't reached that piece yet. Serving it records the piece as downloaded |
| `POST /api/homeview/removed/clear` | "Done, I've deleted them": forgets the removed pieces, so one that comes back counts as new. Refused (409) while external storage is offline, so pieces that are only out of reach aren't posted again as duplicates later |

Every endpoint returns 403 while the feature is off.

**Rendering:** fit inside 2048 × 2048 on black, centred. Pixel art at ≤ 512 px
is scaled by a whole factor with NEAREST so it stays crisp; everything else
uses LANCZOS. Transparency is flattened onto black. GIF → first frame,
video → frame at 1 s, SVG → `rsvg-convert` (already installed by
`install-vernis.sh`), HTML → its `generator-preview` image. EXIF orientation is applied. Images
over 16 MP are decoded by ffmpeg in its own process, not by Pillow in
vernis-api, so a huge PNG can't make the OOM killer take out the API on a 416 MB
Pi. JPEG quality 90, 4:4:4.

**Security:** GETs are open to the LAN in every mode (`classify_endpoint`),
which is no new exposure since `/nfts/*` already serves the originals. Images
are limited to the last batch, so nobody on the LAN can make the Pi render the
whole collection by walking through IDs. The three POSTs are `control`
endpoints and need the PIN in mode C, which the card handles through
`VernisPinPrompt`. The Shortcut only does GETs.

**Settings card:** a toggle, a source picker, "N new pieces not sent yet",
**Send to HomeView** and **Send last batch again**, the list of removed pieces,
and first-time setup steps. On anything that isn't an iPhone/iPad, including
the kiosk, the buttons are replaced by a QR code that opens
`settings.html#section-display` on the phone.

The button opens
`shortcuts://run-shortcut?name=Vernis%20HomeView&input=text&text=<manifest URL>`.
The manifest URL is built from `location.origin`, so the Shortcut needs no
setup of the Vernis address.

**New dependencies:** none. **Apple credentials on the device:** none.
**Caddy/ufw/install script:** no changes (routes are under `/api/`, and the
config files are created on first use).

### Building and publishing the Shortcut (one time, by the maintainer)

The Shortcut has to be built in the Shortcuts app on an iPhone, iPad or Mac
and published as an iCloud link. Vernis can't serve a `.shortcut` file
itself, because iOS only opens signed ones.

Name: **Vernis HomeView** (must match `HOMEVIEW_SHORTCUT_NAME`).

1. Shortcut details: receives **Text**. If there is no input: **Stop and
   respond** "Open Vernis Settings and tap Send to HomeView".
2. **Get Contents of URL**: *Shortcut Input* (method GET).
3. **Get Dictionary Value**: *Value* for key `items` in *Contents of URL*.
4. **Repeat with Each** item in *Dictionary Value*:
   1. **Get Dictionary Value**: *Value* for key `url` in *Repeat Item*.
   2. **Get Contents of URL**: *Dictionary Value*.
5. **Post to Shared Album**: *Repeat Results*.
6. (Optional) **Show Notification**: "Sent to HomeView".

Then Share → **Copy iCloud Link**, put it in `HOMEVIEW_SHORTCUT_URL` in
`backend/app.py`, and release. Until then the card says the link is "coming in
a Vernis update".

### Still to check on a real HomeView (from 2026-11-13)

The four questions under "Recommendation" above, plus: does running the
Shortcut through `shortcuts://` from Safari work without extra prompts, and
does the iOS 27.2 **Post to Shared Album** action now take an album
parameter? If it does, set it in the Shortcut and sending becomes one tap
fewer.

On a Pi (not testable on the dev Mac): SVG export through `rsvg-convert`, and
what the Shortcut does when one image returns 500 (a piece that can't be
rendered) — whether it skips that piece or stops the whole run.

## Sources

- Apple Newsroom, "Meet Apple HomeView…" (2026-10):
  https://www.apple.com/newsroom/2026/10/meet-apple-homeview-a-new-way-to-enjoy-entertainment-and-manage-the-home/
- Apple HomeView tech specs: https://www.apple.com/apple-homeview/specs/
- MacRumors, "Apple Announces HomeView" (2026-10-13):
  https://www.macrumors.com/2026/10/13/apple-announces-homeview-smart-home-hub/
- Macworld HomeView guide:
  https://www.macworld.com/article/676817/new-homeview-homepod-mini-screen-rumours-release-date.html
- Apple Developer Forums, "Adding Photos to public iCloud album with web API":
  https://developer.apple.com/forums/thread/717066
- pyicloud (timlaing fork) Photos docs:
  https://github.com/timlaing/pyicloud/blob/main/docs/services/photos.md and
  authentication guide: https://github.com/timlaing/pyicloud/blob/main/docs/guides/authentication.md
- iCloud Terms of Service: https://www.apple.com/legal/internet-services/icloud/en/terms.html
- Shortcuts "Save to Shared Album" action reference (Cassinelli):
  https://matthewcassinelli.com/actions/save-to-shared-album/
- App Intents `postToSharedAlbum` schema:
  https://developer.apple.com/documentation/appintents/appschema/photosintent/posttosharedalbum
- Apple Support, personal automations that run without asking:
  https://support.apple.com/guide/shortcuts/add-automations-apdfbdbd7123/ios
- pyatv supported features: https://pyatv.dev/documentation/supported_features/
