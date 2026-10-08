"""Vernis Curator: talk to the frame through an AI of the owner's choice.

The phone or laptop sends text (typed or dictated) to POST /api/curator/chat.
The frame forwards it to the configured provider (Claude, Grok, OpenAI, or a
local Ollama / LM Studio server) with the frame's own commands as tools, runs
the tool calls locally, and returns the reply for the browser to read aloud.

API keys stay on the device (/opt/vernis/curator-config.json, mode 600) and
are never returned to the browser. Tools only read state or change what is
displayed; nothing here deletes, unpins, or touches wallets.
"""

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import socket
import subprocess
import time
import threading
import urllib.parse
from datetime import datetime, timezone

import requests
from flask import Blueprint, Response, jsonify, request

curator_bp = Blueprint("curator", __name__)

CONFIG_FILE = "/opt/vernis/curator-config.json"
# Claude calls run in their own venv (the SDK needs newer packages than Debian's
# system Python has):  python3 -m venv /opt/vernis/curator-venv &&
#                      /opt/vernis/curator-venv/bin/pip install anthropic
CLAUDE_PY = "/opt/vernis/curator-venv/bin/python"
CLAUDE_HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "curator_claude.py")
API = "http://127.0.0.1:5000"
CDP = "http://127.0.0.1:9222"
KIOSK = "http://127.0.0.1"
PREVIEW_KEY = "vernis-gallery-preview"
SWITCH_WAIT_S = 3.5  # gallery polls /api/remote/poll every second
MAX_SHOW = 500
MAX_TOOL_ROUNDS = 6
MAX_HISTORY = 20
XAI_STT_URL = "https://api.x.ai/v1/stt"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_SPEAK_CHARS = 1200
VOICE_DEFAULTS = {
    "tts": "piper",       # piper | browser | off
    "piper_url": "",      # e.g. http://192.168.1.20:5005 (a Piper http_server on the home network)
    "piper_voice": "en_GB-cori-high",  # voice file name on the Piper server; "" = its default
    "stt": "grok",        # grok | browser
    "language": "en",
}

# Only local servers may point elsewhere; hosted providers are pinned so a saved
# key can never be sent to an address someone else typed in.
CUSTOM_URL_PROVIDERS = ("ollama", "lmstudio")

PROVIDERS = {
    "grok": {"label": "Grok (xAI)", "base_url": "https://api.x.ai/v1", "model": "grok-4.20-0309-non-reasoning", "needs_key": True},
    "claude": {"label": "Claude (Anthropic)", "base_url": "", "model": "claude-opus-5", "needs_key": True},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "", "needs_key": True},
    "ollama": {"label": "Ollama (local)", "base_url": "http://localhost:11434/v1", "model": "auto", "needs_key": False},
    "lmstudio": {"label": "LM Studio (local)", "base_url": "http://localhost:1234/v1", "model": "auto", "needs_key": False},
}

SYSTEM_PROMPT = (
    "You are the curator inside a Vernis digital art frame that shows the owner's NFT collection. "
    "Use the tools to see what is on screen, change the artwork, show an artist or collection, and "
    "check the health of the frame's IPFS archive. When asked about a piece, call now_showing first "
    "and talk about it the way a gallery curator would: the artist, the ideas, the context. "
    "Your replies are read aloud in a live conversation, so keep them short: one or two sentences, "
    "like a person talking, unless the owner asks you to tell more. Plain spoken words only: no "
    "markdown, lists, emoji, CIDs or hex addresses. Answer in the language the owner speaks. "
    "While you talk about a piece the slideshow is paused for you; use resume_slideshow when the "
    "owner wants it to continue. A collection name is not the artist: if no artist is given, don't "
    "name one. Only mention pieces, versions or titles that a tool actually returned, and never say "
    "something is on screen unless show, next_artwork, previous_artwork or now_showing just confirmed it "
    "(find_artworks does not change the screen). When asked for another version, call show with that "
    "version's exact title. To suggest what else to look at, call list_artists and name only artists it "
    "returned; never suggest famous artists from your own knowledge, they may not be in this collection. "
    "You cannot delete, unpin, or access wallets; if asked, say so briefly."
)

ACTIVE_JS = (
    "(() => { const el = document.querySelector('body > img.active, body > video.active, "
    "body > iframe.gallery-artwork.active'); return el ? el.src : null; })()"
)
PUBLIC_FIELDS = ("name", "artist", "collection", "description", "year", "tags",
                 "attributes", "medium", "chain", "token_id", "contract", "cid")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
NOT_A_NAME = re.compile(r"^(0x[0-9a-fA-F]+(_\d+)?|\d+)$")


class ToolError(Exception):
    pass


def claude_helper(payload, *args, timeout=120):
    if not os.path.exists(CLAUDE_PY):
        raise ToolError("Claude support is not installed on this frame (missing /opt/vernis/curator-venv).")
    try:
        proc = subprocess.run([CLAUDE_PY, CLAUDE_HELPER, *args], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ToolError("Claude took too long to answer.") from exc
    try:
        out = json.loads(proc.stdout)
    except ValueError as exc:
        raise ToolError(f"Claude helper failed: {proc.stderr.strip()[-300:]}") from exc
    if out.get("error"):
        raise ToolError(out["error"])
    return out


# -- Config ----------------------------------------------------------------------

def load_config():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("provider", "grok")
    cfg.setdefault("keys", {})
    cfg.setdefault("models", {})
    cfg.setdefault("base_urls", {})
    cfg["voice"] = {**VOICE_DEFAULTS, **(cfg.get("voice") or {})}
    return cfg


def save_config(cfg):
    tmp = CONFIG_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


def clean_server_url(url, allow_v1=True):
    """A home-network server address as scheme://host[:port][/v1], or None.

    The frame requests fixed paths under this address (/models, /api/ps,
    /synthesize...), so no path, query or fragment of the user's own is
    allowed."""
    url = str(url or "").strip().rstrip("/")
    if not url or "?" in url or "#" in url or "\\" in url:
        return None
    try:
        u = urllib.parse.urlparse(url)
        u.port  # raises on a malformed port
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        return None
    if u.path not in ("", "/v1" if allow_v1 else ""):
        return None
    return f"{u.scheme}://{u.netloc}{u.path}"


def provider_settings(cfg, name):
    p = PROVIDERS[name]
    custom = clean_server_url(cfg["base_urls"].get(name)) if name in CUSTOM_URL_PROVIDERS else None
    return {
        "model": cfg["models"].get(name) or p["model"],
        "base_url": (custom or p["base_url"]).rstrip("/"),
        "key": cfg["keys"].get(name, ""),
    }


def public_config(cfg):
    voice = dict(cfg["voice"])
    voice["stt_ready"] = bool(cfg["keys"].get("grok"))  # Grok STT uses the saved Grok key
    out = {"provider": cfg["provider"], "providers": {}, "voice": voice,
           "save_tokens": cfg.get("save_tokens", True)}
    for name, p in PROVIDERS.items():
        s = provider_settings(cfg, name)
        key = s["key"]
        out["providers"][name] = {
            "label": p["label"], "model": s["model"], "base_url": s["base_url"],
            "needs_key": p["needs_key"], "has_key": bool(key),
            "key_hint": ("…" + key[-4:]) if len(key) > 8 else "",
        }
    return out


# -- Frame access ----------------------------------------------------------------

def api(path, method="GET", body=None, timeout=20):
    try:
        r = requests.request(method, API + path, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise ToolError(f"Vernis API not reachable: {exc}") from exc
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 and isinstance(data, dict):
        data["_status"] = r.status_code
    return data


def kiosk_page():
    try:
        targets = requests.get(CDP + "/json/list", timeout=3).json()
    except (requests.RequestException, ValueError) as exc:
        raise ToolError(f"kiosk browser not reachable: {exc}") from exc
    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not pages:
        raise ToolError("kiosk browser has no open page")
    return pages[0]


def cdp(page, method, params=None):
    import websocket
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10)
    try:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                if "error" in msg:
                    raise ToolError(f"browser: {msg['error'].get('message')}")
                return msg.get("result", {})
    finally:
        ws.close()
    raise ToolError("browser did not answer")


def evaluate(page, expression):
    result = cdp(page, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return result.get("result", {}).get("value")


def on_gallery(page):
    return urllib.parse.urlparse(page.get("url", "")).path.endswith("/gallery.html")


def public_meta(meta, filename=""):
    out = {k: meta[k] for k in PUBLIC_FIELDS if meta.get(k) not in (None, "", [], {})}
    for key in ("artist", "collection"):
        # A bare 0x address is a wallet or contract, not a name.
        if isinstance(out.get(key), str) and ADDRESS.match(out[key]):
            out[f"{key}_address"] = out.pop(key)
    if isinstance(out.get("tags"), list):
        out["tags"] = [t.strip() for t in out["tags"] if isinstance(t, str) and t.strip()]
    if filename and out.get("name") in (filename, filename.rsplit(".", 1)[0]):
        del out["name"]  # Vernis falls back to the file name; that is not a title
    return out


def artwork_info(filename):
    safe = urllib.parse.quote(filename, safe="")
    info = api(f"/api/nft-artwork-info/{safe}")
    if info.get("_status") or info.get("error"):
        info = api(f"/api/nft-metadata/{safe}")
    if info.get("_status") or info.get("error"):
        return {}
    return public_meta(info, filename)


# -- Tools -----------------------------------------------------------------------

def t_now_showing(_args):
    page = kiosk_page()
    if not on_gallery(page):
        return {"gallery_running": False,
                "hint": "The frame is on its menu/home screen, not showing artwork. "
                        "show_all starts the gallery."}
    src = evaluate(page, ACTIVE_JS)
    if not src:
        return {"gallery_running": True, "artwork": None, "hint": "The gallery is loading."}
    filename = urllib.parse.unquote(urllib.parse.urlparse(src).path.rsplit("/", 1)[-1])
    info = artwork_info(filename)
    return {"gallery_running": True, "filtered_selection": "preview=" in page.get("url", ""),
            "artwork": info or None, **({} if info else {"hint": "No metadata for this file."})}


def _step(command):
    _cancel_resume()
    page = kiosk_page()
    if not on_gallery(page):
        if not api("/api/remote/start-gallery", "POST", {}).get("success"):
            raise ToolError("could not start the gallery")
        time.sleep(SWITCH_WAIT_S + 2)
        return {"started_gallery": True, **t_now_showing({})}
    res = api("/api/remote/command", "POST", {"command": command})
    if not res.get("success"):
        raise ToolError(res.get("error") or f"{command} failed")
    time.sleep(SWITCH_WAIT_S)  # also lets the gallery pick up the command before the next one
    result = t_now_showing({})
    if command == "prev" and hold_artwork():
        # Going back means the owner wants to see that piece: keep it on screen.
        result["slideshow"] = "paused on this piece; it continues when the owner says so"
    return result


SEARCH_STOPWORDS = {
    "the", "a", "an", "of", "by", "and", "or", "in", "on", "to", "me", "my", "show", "find", "search",
    "version", "piece", "pieces", "artwork", "artworks", "art", "work", "works", "nft", "nfts", "one",
    "collection", "called", "named", "please", "some", "something", "from", "with", "all",
    "vis", "meg", "av", "og", "en", "et", "den", "det", "verket", "verk", "samlingen", "samling",
}


def _words(text):
    return re.findall(r"[\w$]+", str(text).casefold())


def _library():
    """Metadata for every file in the gallery, with its hidden flag."""
    nfts = api("/api/nft-metadata").get("nfts") or {}
    listed = api("/api/nft-list-detailed")
    items = listed if isinstance(listed, list) else (listed.get("nfts") or [])
    hidden = set() if isinstance(listed, list) else set(listed.get("hidden") or [])
    hidden |= {n["filename"] for n in items if n.get("hidden")}
    return [(n["filename"], nfts.get(n["filename"]) or {}, n["filename"] in hidden) for n in items]


def search_library(query, by="any"):
    """Rank artworks by the query words they contain. A word also matches longer words
    that start with it ('doom' finds 'Doomed'); rare words count more than common ones
    (so in 'doomed blue' the title 'The Doomed' beats every '(blue)' variant), and title
    words count more than tags or descriptions."""
    import math
    terms = [w for w in _words(query) if w not in SEARCH_STOPWORDS] or _words(query)
    if not terms:
        return []

    def has(words, t):
        return any(w == t or (len(t) >= 3 and w.startswith(t)) for w in words)

    rows = []
    for f, m, is_hidden in _library():
        attrs = [a.get("value") for a in (m.get("attributes") or []) if isinstance(a, dict)]
        fields = {
            "name": _words(m.get("name") or f.rsplit(".", 1)[0]),
            "artist": _words(m.get("artist") or ""),
            "collection": _words(m.get("collection") or ""),
            "other": _words(" ".join([m.get("description") or "", " ".join(map(str, m.get("tags") or [])),
                                      " ".join(map(str, attrs)), f])),
        }
        if by == "artist":
            fields = {"artist": fields["artist"]}
        elif by == "collection":
            fields = {"collection": fields["collection"]}
        hit = {t: max([{"name": 3, "artist": 2, "collection": 2}.get(k, 1) for k, ws in fields.items() if has(ws, t)] or [0])
               for t in terms}
        rows.append((f, m, is_hidden, fields, hit))
    n = max(len(rows), 1)
    df = {t: sum(1 for r in rows if r[4][t]) for t in terms}
    idf = {t: math.log((n + 1) / (df[t] + 1)) + 1 for t in terms}
    need = max(1, (len(terms) + 1) // 2)
    results = []
    for f, m, is_hidden, fields, hit in rows:
        matched = [t for t in terms if hit[t]]
        if len(matched) < need:
            continue
        score = sum(hit[t] * idf[t] for t in matched)
        if " ".join(fields.get("name", [])) == " ".join(terms):
            score += 10  # exact title
        results.append({
            "file": f, "score": round(score, 3), "hidden": is_hidden, "words": matched,
            "in_artist": bool(fields.get("artist")) and all(has(fields["artist"], t) for t in terms),
            "in_collection": bool(fields.get("collection")) and all(has(fields["collection"], t) for t in terms),
            "name": m.get("name"), "artist": m.get("artist"), "collection": m.get("collection")})
    results.sort(key=lambda r: (-r["score"], r["hidden"], str(r["name"])))
    return results


def library_artists(limit=12):
    """Artists in the slideshow, most works first (wallet addresses and numbers left out)."""
    counts = {}
    for _f, m, is_hidden in _library():
        a = str(m.get("artist") or "").strip()
        if a and not is_hidden and not ADDRESS.match(a) and not NOT_A_NAME.match(a):
            counts[a] = counts.get(a, 0) + 1
    return [a for a, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))][:limit]


def t_list_artists(_args):
    counts, collections = {}, {}
    for _f, m, is_hidden in _library():
        if is_hidden:
            continue
        for key, bucket in (("artist", counts), ("collection", collections)):
            v = str(m.get(key) or "").strip()
            if v and not ADDRESS.match(v) and not NOT_A_NAME.match(v):
                bucket[v] = bucket.get(v, 0) + 1
    top = lambda d: [{"name": k, "works": n} for k, n in
                     sorted(d.items(), key=lambda kv: (-kv[1], kv[0].casefold()))[:25]]
    return {"artists": top(counts), "artist_count": len(counts),
            "collections": top(collections), "collection_count": len(collections)}


def _brief(r):
    out = {k: r[k] for k in ("name", "artist", "collection") if r.get(k) and not ADDRESS.match(str(r[k]))}
    if r["hidden"]:
        out["hidden_from_slideshow"] = True
    return out


def t_find(args):
    query = str(args.get("query", "")).strip()
    if len(query) < 2:
        raise ToolError("query must be at least 2 characters")
    hits = search_library(query, args.get("by", "any"))
    visible = [h for h in hits if not h["hidden"]]
    terms = [w for w in _words(query) if w not in SEARCH_STOPWORDS] or _words(query)
    unmatched = [t for t in terms if not any(t in h["words"] for h in hits)]
    return {"query": query, "matches": len(hits), "visible": len(visible), "hidden": len(hits) - len(visible),
            "top": [_brief(h) for h in hits[:8]],
            **({"no_match_for": unmatched} if unmatched else {}),
            **({} if hits else {"artists_in_collection": library_artists()}),
            "screen": "unchanged. find_artworks only searches; to put a piece on screen call show "
                      "with its exact title (e.g. show query='The Doomed (mono)').",
            "note": "Hidden pieces were hidden from the slideshow by the owner; show them only if asked."}


def t_show(args):
    query = str(args.get("query", "")).strip()
    if len(query) < 2:
        raise ToolError("query must be at least 2 characters")
    hits = search_library(query, args.get("by", "any"))
    include_hidden = bool(args.get("include_hidden"))
    # An artist or collection name means all of its works; otherwise it's a title search
    # and the best match (or equally good ones) is shown.
    group = [h for h in hits if h["in_artist"]] or [h for h in hits if h["in_collection"]]
    visible_group = [h for h in group if not h["hidden"]]
    if group and include_hidden:
        pool = group
    elif visible_group:
        pool = visible_group
    else:
        # No visible artist/collection by that name: fall back to the best visible titles,
        # so 'another DOOM version' finds The Doomed even though DOOM Party is hidden.
        pool = hits if include_hidden else [h for h in hits if not h["hidden"]]
        if pool:
            pool = [h for h in pool if h["score"] == pool[0]["score"]]
    if not pool:
        hidden_ones = group or hits
        if hidden_ones:
            return {"shown": 0, "query": query, "hidden_matches": len(hidden_ones),
                    "examples": [_brief(h) for h in hidden_ones[:5]],
                    "hint": "These pieces exist but are hidden from the slideshow. Tell the owner and offer "
                            "to show them anyway (call show again with include_hidden=true)."}
        return {"shown": 0, "query": query, "artists_in_collection": library_artists(),
                "hint": "Nothing in the collection matches. Suggest only artists from artists_in_collection."}
    picked = pool
    selection = [h["file"] for h in picked][:MAX_SHOW]
    page = kiosk_page()
    if urllib.parse.urlparse(page.get("url", "")).netloc not in ("127.0.0.1", "localhost"):
        raise ToolError("kiosk is not on the Vernis page")
    evaluate(page, f"localStorage.setItem({json.dumps(PREVIEW_KEY)}, "
                   f"{json.dumps(json.dumps(selection))}); true")
    # A fresh URL every time, so the frame reloads even if it already shows a selection.
    cdp(page, "Page.navigate", {"url": f"{KIOSK}/gallery.html?preview=1&t={int(time.time() * 1000)}"})
    time.sleep(SWITCH_WAIT_S + 2)
    shown_hidden = sum(1 for h in picked if h["hidden"])
    terms = [w for w in _words(query) if w not in SEARCH_STOPWORDS] or _words(query)
    unmatched = [t for t in terms if not any(t in h["words"] for h in picked)]
    extra = {"example_titles": sorted({h["name"] for h in picked if h.get("name")})[:8],
             "all_shown_count": len(selection)}
    if unmatched:
        extra["no_match_for"] = unmatched
        extra["note"] = ("Nothing shown matches " + ", ".join(repr(w) for w in unmatched) +
                         ". Say so plainly; don't claim such a version exists.")
    return {**extra, "shown": len(selection), "query": query, "hidden_included": shown_hidden,
            "artists": sorted({h["artist"] for h in picked if h.get("artist")})[:10],
            "now_showing": t_now_showing({}).get("artwork")}


_resume_timer = None
_resume_lock = threading.Lock()
AUTO_RESUME_S = 180


def _cancel_resume():
    global _resume_timer
    with _resume_lock:
        if _resume_timer:
            _resume_timer.cancel()
            _resume_timer = None


def hold_artwork(auto_resume=True):
    """Pause the slideshow so the piece stays while it's discussed; resume later by itself."""
    global _resume_timer
    try:
        if not on_gallery(kiosk_page()):
            return False
    except ToolError:
        return False
    api("/api/remote/command", "POST", {"command": "pause"})
    _cancel_resume()
    if auto_resume:
        with _resume_lock:
            _resume_timer = threading.Timer(AUTO_RESUME_S, lambda: api("/api/remote/command", "POST", {"command": "play"}))
            _resume_timer.daemon = True
            _resume_timer.start()
    return True


def t_pause(_args):
    if not hold_artwork(auto_resume=False):
        return {"paused": False, "hint": "The gallery isn't running."}
    return {"paused": True, "hint": "This piece stays on screen until the owner asks to continue."}


def t_resume(_args):
    _cancel_resume()
    page = kiosk_page()
    if not on_gallery(page):
        return t_show_all({})
    api("/api/remote/command", "POST", {"command": "play"})
    return {"playing": True}


def t_show_all(_args):
    if not api("/api/remote/start-gallery", "POST", {}).get("success"):
        raise ToolError("could not start the gallery")
    return {"gallery_running": True}


def t_archive_health(_args):
    ipfs = api("/api/ipfs/status")
    storage = api("/api/health/storage")
    library = api("/api/csv-library", timeout=30).get("collections") or []
    local = [c for c in library if c.get("source") == "local"]
    checked = sorted((c["last_checked"] for c in local if c.get("last_checked")), reverse=True)
    ago = None
    if checked:
        try:
            last = datetime.fromisoformat(checked[0].replace("Z", "+00:00"))
            hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            ago = f"{round(hours)} hours ago" if hours < 48 else f"{round(hours / 24)} days ago"
        except ValueError:
            pass
    return {
        "ipfs": {"running": ipfs.get("running"), "pinned": ipfs.get("pinned"), "peers": ipfs.get("peers")},
        "storage": {k: storage.get(k) for k in ("status", "free_gb", "total_gb")},
        "artworks_in_gallery": api("/api/remote/status").get("nft_count"),
        "collections": len(local),
        "failed_downloads": sum(c.get("failed_count", 0) or 0 for c in local),
        "last_checked": checked[0] if checked else None,
        "last_checked_ago": ago,
    }


TOOLS = {
    "now_showing": (t_now_showing, "What artwork the frame shows right now: title, artist, collection, "
                    "description and attributes.", {}, []),
    "next_artwork": (lambda a: _step("next"), "Show the next artwork, then report what is on screen.", {}, []),
    "previous_artwork": (lambda a: _step("prev"), "Go back to the previous artwork and keep it on screen (pauses the slideshow), then report what is on screen.",
                         {}, []),
    "find_artworks": (t_find, "Search the owner's collection by title, artist, collection, description or "
                      "tags. Does NOT change the screen; use show afterwards to display a result. Use it to "
                      "answer 'do I have…' or 'what is in…'.",
                      {"query": {"type": "string", "description": "Words to look for, e.g. 'DOOMED' or 'DOOM Party'."},
                       "by": {"type": "string", "enum": ["artist", "collection", "any"],
                              "description": "Limit the search. Default any."}}, ["query"]),
    "show": (t_show, "Show artworks on the frame that match a title, artist or collection (word match, "
             "so 'doomed blue' finds 'The Doomed'). A single title match is shown on its own.",
             {"query": {"type": "string", "description": "Title, artist or collection words."},
              "by": {"type": "string", "enum": ["artist", "collection", "any"],
                     "description": "What to match. Default any."},
              "include_hidden": {"type": "boolean",
                                 "description": "Also show pieces the owner hid from the slideshow (only when asked)."}},
             ["query"]),
    "show_all": (t_show_all, "Return to the full gallery of all artworks.", {}, []),
    "pause_slideshow": (t_pause, "Keep the current artwork on screen (stop the slideshow) until asked to continue.", {}, []),
    "resume_slideshow": (t_resume, "Continue the slideshow (start showing the next artworks again).", {}, []),
    "list_artists": (t_list_artists, "The artists and collections in the owner's slideshow, most works first. "
                     "Use it before suggesting what else to show.", {}, []),
    "archive_health": (t_archive_health, "Health of the art archive: IPFS node, pinned count, storage, "
                       "failed downloads, last checked.", {}, []),
}


def run_tool(name, args):
    if name not in TOOLS:
        return {"error": f"unknown tool {name}"}, False
    try:
        return TOOLS[name][0](args or {}), True
    except ToolError as exc:
        return {"error": str(exc)}, False


def tool_schemas():
    return [(name, desc, {"type": "object", "properties": props, "required": req})
            for name, (_fn, desc, props, req) in TOOLS.items()]


# -- Providers -------------------------------------------------------------------

def chat_openai_compatible(s, history, actions):
    """Grok, OpenAI, Ollama and LM Studio all speak the chat-completions API."""
    headers = {"Content-Type": "application/json"}
    if s["key"]:
        headers["Authorization"] = f"Bearer {s['key']}"
    tools = [{"type": "function", "function": {"name": n, "description": d, "parameters": p}}
             for n, d, p in tool_schemas()]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    for _ in range(MAX_TOOL_ROUNDS):
        r = requests.post(f"{s['base_url']}/chat/completions", headers=headers, timeout=120,
                          json={"model": s["model"], "messages": messages, "tools": tools},
                          allow_redirects=False)
        if r.status_code >= 400:
            raise ToolError(f"provider error {r.status_code}: {r.text[:300]}")
        msg = r.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or ""
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except ValueError:
                args = {}
            result, ok = run_tool(name, args)
            actions.append({"tool": name, "args": args, "ok": ok})
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
    return "I did several things but ran out of steps. Ask me again if something is missing."


def chat_claude(s, history, actions):
    tools = [{"name": n, "description": d, "input_schema": p} for n, d, p in tool_schemas()]
    messages = list(history)
    for _ in range(MAX_TOOL_ROUNDS):
        response = claude_helper({"api_key": s["key"], "request": {
            "model": s["model"],
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "tools": tools,
            "messages": messages,
            "output_config": {"effort": "low"},  # short spoken replies; keeps voice latency down
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }})["response"]
        if response["stop_reason"] == "refusal":
            return "I can't help with that one."
        content = response["content"]
        if response["stop_reason"] != "tool_use":
            return "".join(b.get("text", "") for b in content if b["type"] == "text")
        messages.append({"role": "assistant", "content": content})
        results = []
        for block in content:
            if block["type"] != "tool_use":
                continue
            result, ok = run_tool(block["name"], block.get("input") or {})
            actions.append({"tool": block["name"], "args": block.get("input") or {}, "ok": ok})
            results.append({"type": "tool_result", "tool_use_id": block["id"],
                            "content": json.dumps(result, ensure_ascii=False), "is_error": not ok})
        messages.append({"role": "user", "content": results})
    return "I did several things but ran out of steps. Ask me again if something is missing."


# -- Routes ----------------------------------------------------------------------

@curator_bp.route("/api/curator/config", methods=["GET"])
def curator_get_config():
    cfg = load_config()
    out = public_config(cfg)
    provider = cfg["provider"]
    if provider in CUSTOM_URL_PROVIDERS and out["providers"][provider]["model"] in ("", "auto"):
        # Show which model "auto" means right now (None if the server can't be reached).
        out["providers"][provider]["live_model"] = loaded_model(provider_settings(cfg, provider)["base_url"])
    return jsonify(out)


@curator_bp.route("/api/curator/config", methods=["POST"])
def curator_set_config():
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    provider = data.get("provider", cfg["provider"])
    if provider not in PROVIDERS:
        return jsonify({"error": "unknown provider"}), 400
    cfg["provider"] = provider
    if "model" in data:
        cfg["models"][provider] = str(data["model"]).strip()[:120]
    if "base_url" in data and provider in CUSTOM_URL_PROVIDERS:
        url = str(data["base_url"]).strip()
        if url:
            url = clean_server_url(url)
            if not url:
                return jsonify({"error": "Server address must look like http://host:port or http://host:port/v1"}), 400
        if url != cfg["base_urls"].get(provider, ""):
            cfg["keys"].pop(provider, None)  # a key never follows a new address
        cfg["base_urls"][provider] = url
    if "save_tokens" in data:
        cfg["save_tokens"] = bool(data["save_tokens"])
    voice = data.get("voice")
    if isinstance(voice, dict):
        v = cfg["voice"]
        if voice.get("tts") in ("piper", "browser", "off"):
            v["tts"] = voice["tts"]
        if voice.get("stt") in ("grok", "browser"):
            v["stt"] = voice["stt"]
        if isinstance(voice.get("language"), str) and re.match(r"^[a-z]{2}$", voice["language"]):
            v["language"] = voice["language"]
        if "piper_voice" in voice:
            name = str(voice["piper_voice"]).strip()
            if name and not re.match(r"^[A-Za-z0-9_-]{1,64}$", name):
                return jsonify({"error": "invalid voice name"}), 400
            v["piper_voice"] = name
        if "piper_url" in voice:
            url = str(voice["piper_url"]).strip().rstrip("/")
            if url:
                url = clean_server_url(url, allow_v1=False)
                if not url:
                    return jsonify({"error": "Voice server must look like http://host:port"}), 400
            v["piper_url"] = url
    if data.get("clear_key"):
        cfg["keys"].pop(provider, None)
    elif data.get("api_key"):
        cfg["keys"][provider] = str(data["api_key"]).strip()
    save_config(cfg)
    return jsonify({"success": True, **public_config(cfg)})


@curator_bp.route("/api/curator/models", methods=["GET"])
def curator_models():
    """List the models a provider offers, for the Settings dropdown."""
    cfg = load_config()
    provider = request.args.get("provider", cfg["provider"])
    if provider not in PROVIDERS:
        return jsonify({"error": "unknown provider"}), 400
    s = provider_settings(cfg, provider)
    if PROVIDERS[provider]["needs_key"] and not s["key"]:
        return jsonify({"error": "Save an API key for this provider first."}), 400
    try:
        if provider == "claude":
            ids = claude_helper({"api_key": s["key"]}, "models", timeout=30)["models"]
        else:
            headers = {"Authorization": f"Bearer {s['key']}"} if s["key"] else {}
            r = requests.get(f"{s['base_url']}/models", headers=headers, timeout=15,
                             allow_redirects=False)
            r.raise_for_status()
            ids = [m["id"] for m in r.json().get("data", [])]
    except Exception as exc:  # shown to the owner in Settings
        return jsonify({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}), 502
    return jsonify({"provider": provider, "models": sorted(ids)})


# -- Local models: use whatever is loaded, find servers on the network ----------

def _server_root(base_url):
    return re.sub(r"/v1/?$", "", base_url.rstrip("/"))


def loaded_model(base_url):
    """The model currently loaded in LM Studio or Ollama at base_url, or None."""
    root = _server_root(base_url)
    try:  # LM Studio's own API says which models are loaded
        r = requests.get(f"{root}/api/v0/models", timeout=4, allow_redirects=False)
        if r.ok:
            models = r.json().get("data", [])
            for m in models:
                if m.get("state") == "loaded" and m.get("type") in ("llm", "vlm"):
                    return m["id"]
    except (requests.RequestException, ValueError):
        pass
    try:  # Ollama lists running models
        r = requests.get(f"{root}/api/ps", timeout=4, allow_redirects=False)
        if r.ok and r.json().get("models"):
            return r.json()["models"][0]["name"]
    except (requests.RequestException, ValueError):
        pass
    try:  # any OpenAI-compatible server: first chat model it offers
        r = requests.get(f"{base_url.rstrip('/')}/models", timeout=4, allow_redirects=False)
        if r.ok:
            ids = [m["id"] for m in r.json().get("data", []) if "embed" not in m["id"]]
            return ids[0] if ids else None
    except (requests.RequestException, ValueError):
        pass
    return None


def resolve_model(provider, s):
    if provider in CUSTOM_URL_PROVIDERS and s["model"] in ("", "auto"):
        model = loaded_model(s["base_url"])
        if not model:
            label = PROVIDERS[provider]["label"].split(" (")[0]
            raise ToolError(f"Can't reach {label} at {s['base_url']}. Is it running with "
                            f"'Serve on Local Network' turned on? (Settings → AI Curator → Find on my network)")
        s["model"] = model
    return s


@curator_bp.route("/api/curator/discover", methods=["GET"])
def curator_discover():
    """Look for LM Studio (port 1234) and Ollama (port 11434) on the home network."""
    from concurrent.futures import ThreadPoolExecutor
    ip = lan_ip()
    prefix = ip.rsplit(".", 1)[0]

    def probe(target):
        host, port, kind = target
        try:
            with socket.create_connection((host, port), timeout=0.4):
                pass
        except OSError:
            return None
        base = f"http://{host}:{port}/v1"
        return {"provider": kind, "base_url": base, "host": host, "model": loaded_model(base)}

    targets = [(f"{prefix}.{i}", port, kind) for i in range(1, 255)
               for port, kind in ((1234, "lmstudio"), (11434, "ollama"))]
    with ThreadPoolExecutor(max_workers=64) as pool:
        found = [f for f in pool.map(probe, targets) if f]
    return jsonify({"found": found, "frame_ip": ip})


# -- Saving tokens: answer simple things locally, reuse earlier answers -----------

CACHE_FILE = "/opt/vernis/curator-cache.json"
CACHE_MAX = 500
CACHE_DAYS = 30
STATE_CHANGING = {"next_artwork", "previous_artwork", "show", "show_all", "pause_slideshow", "resume_slideshow"}
TEXT = {
    "en": {
        "no_meta": "This piece has no title or artist saved on the frame, so I can't tell you much about it. Want to see the next one?",
        "here": "Here's {name} by {artist}.",
        "here_noartist": "Here's {name}.",
        "all": "Back to the full gallery.",
        "showing": "Showing {n} works by {q}. On screen now: {name}.",
        "not_found": "I couldn't find {q} in your collection.",
        "try_artists": " You have works by {names}.",
        "home": "The frame is on its home screen right now. Say \"show all\" to start the gallery.",
        "archive_ok": "Your archive looks healthy. {pinned} pieces are pinned on the frame's own IPFS node, with {free} GB free.",
        "archive_bad": "Your archive needs attention: {failed} downloads failed. {pinned} pieces are pinned, with {free} GB free.",
        "archive_down": "The frame's IPFS node isn't running right now, so new pieces aren't being pinned.",
        "checked": " Last checked {ago}.",
        "paused": "Okay, I'll keep this one on screen. Say continue when you want to move on.",
        "holding": "I'll keep it on screen.",
        "resumed": "Carrying on with the slideshow.",
    },
    "no": {
        "no_meta": "Dette verket har ingen tittel eller kunstner lagret på rammen, så jeg kan ikke si så mye om det. Vil du se det neste?",
        "here": "Her er {name} av {artist}.",
        "here_noartist": "Her er {name}.",
        "all": "Tilbake til hele galleriet.",
        "showing": "Viser {n} verk av {q}. På skjermen nå: {name}.",
        "not_found": "Jeg fant ikke {q} i samlingen din.",
        "try_artists": " Du har verk av {names}.",
        "home": "Rammen står på hjemskjermen nå. Si «vis alt» for å starte galleriet.",
        "archive_ok": "Arkivet ditt ser bra ut. {pinned} verk er pinnet på rammens egen IPFS-node, og det er {free} GB ledig.",
        "archive_bad": "Arkivet trenger tilsyn: {failed} nedlastinger feilet. {pinned} verk er pinnet, og det er {free} GB ledig.",
        "archive_down": "Rammens IPFS-node kjører ikke akkurat nå, så nye verk blir ikke pinnet.",
        "checked": " Sist sjekket {ago}.",
        "paused": "Greit, jeg holder dette verket på skjermen. Si fortsett når du vil videre.",
        "holding": "Jeg holder det på skjermen.",
        "resumed": "Fortsetter visningen.",
    },
}
INTENTS = [  # (intent, pattern) for short commands only
    ("pause", r"^(pause|pause it|stop|hold|hold on|wait|stay|stay here|keep (this|it)( one)?|stop the slideshow|"
              r"pause the slideshow|stopp|pause|vent|behold (denne|dette)|stopp lysbildene)( please| takk)?$"),
    ("resume", r"^(continue|resume|play|keep going|carry on|go on|start again|continue the slideshow|"
               r"fortsett|spill av|start igjen|kjør videre)( please| takk)?$"),
    ("next", r"^(next|next one|next piece|skip|another one|neste|neste verk|vis neste|hopp over)( please| takk)?$"),
    ("previous", r"^(previous|previous one|go back|back|last one|forrige|tilbake|gå tilbake|vis forrige)( please| takk)?$"),
    ("show_all", r"^(show (me )?(all|everything|the (whole|full) (gallery|collection))|vis (meg )?(alt|alle|hele (galleriet|samlingen)))$"),
    ("archive", r"^(is my (archive|art|collection) (safe|ok|okay|healthy)|archive (health|status)|how is my archive|"
                r"er arkivet (mitt )?(trygt|ok|i orden)|arkivstatus|hvordan går det med arkivet)$"),
    ("describe", r"^(what('s| is) (on (the )?(screen|frame)|this|showing|that)|tell me about (it|this|this piece|the piece)|"
                 r"what am i looking at|hva er (dette|på skjermen)|hva vises( nå)?|fortell (meg )?om (dette|verket))$"),
    ("show", r"^(show me|show|vis meg|vis) (?P<q>.+)$"),
]


def load_cache():
    try:
        with open(CACHE_FILE) as f:
            c = json.load(f)
    except (OSError, ValueError):
        c = {}
    c.setdefault("answers", {})
    c.setdefault("stats", {"local": 0, "cached": 0, "ai": 0})
    return c


def save_cache(c):
    answers = c["answers"]
    cutoff = time.time() - CACHE_DAYS * 86400
    for k in [k for k, v in answers.items() if v.get("ts", 0) < cutoff]:
        del answers[k]
    if len(answers) > CACHE_MAX:
        for k in sorted(answers, key=lambda k: answers[k].get("ts", 0))[:len(answers) - CACHE_MAX]:
            del answers[k]
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(c, f)
    os.replace(tmp, CACHE_FILE)


def normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.casefold())).strip()


def reply_language(cfg, text):
    if re.search(r"[æøå]|\b(hva|vis|neste|forrige|takk|jeg|er|det|ikke|verket|arkivet)\b", text, re.I):
        return "no"
    return "en"


def current_file():
    """File name of the artwork on screen ('' if none), used to key cached answers."""
    try:
        page = kiosk_page()
        if not on_gallery(page):
            return ""
        src = evaluate(page, ACTIVE_JS) or ""
        return urllib.parse.unquote(urllib.parse.urlparse(src).path.rsplit("/", 1)[-1])
    except ToolError:
        return ""


def _art_line(t, art):
    if not art or not art.get("name"):
        return t["no_meta"]
    if art.get("artist"):
        return t["here"].format(name=art["name"], artist=art["artist"])
    return t["here_noartist"].format(name=art["name"])


def local_answer(text, lang, actions):
    """Answer a short command without the AI. Returns (reply, kind) or (None, intent)."""
    t = TEXT[lang]
    norm = normalize(text)
    if len(norm.split()) > 8:
        return None, None
    for intent, pattern in INTENTS:
        m = re.match(pattern, norm)
        if not m:
            continue
        if intent in ("next", "previous"):
            result, ok = run_tool(f"{intent}_artwork", {})
            actions.append({"tool": f"{intent}_artwork", "args": {}, "ok": ok})
            if not ok:
                return None, intent
            line = _art_line(t, result.get("artwork"))
            if intent == "previous" and result.get("slideshow"):
                line += " " + t["holding"]
            return line, intent
        if intent == "pause":
            result, ok = run_tool("pause_slideshow", {})
            actions.append({"tool": "pause_slideshow", "args": {}, "ok": ok})
            return (t["paused"] if ok and result.get("paused") else t["home"]), intent
        if intent == "resume":
            result, ok = run_tool("resume_slideshow", {})
            actions.append({"tool": "resume_slideshow", "args": {}, "ok": ok})
            return (t["resumed"] if ok else None), intent
        if intent == "show_all":
            result, ok = run_tool("show_all", {})
            actions.append({"tool": "show_all", "args": {}, "ok": ok})
            return (t["all"] if ok else None), intent
        if intent == "archive":
            result, ok = run_tool("archive_health", {})
            actions.append({"tool": "archive_health", "args": {}, "ok": ok})
            if not ok:
                return None, intent
            ipfs, storage = result.get("ipfs") or {}, result.get("storage") or {}
            if not ipfs.get("running"):
                reply = t["archive_down"]
            else:
                key = "archive_bad" if result.get("failed_downloads") else "archive_ok"
                reply = t[key].format(pinned=f"{ipfs.get('pinned') or 0:,}", free=storage.get("free_gb", "?"),
                                      failed=result.get("failed_downloads"))
            if result.get("last_checked_ago"):
                reply += t["checked"].format(ago=result["last_checked_ago"])
            return reply, intent
        if intent == "describe":
            result, ok = run_tool("now_showing", {})
            actions.append({"tool": "now_showing", "args": {}, "ok": ok})
            if ok and not result.get("gallery_running"):
                return t["home"], intent
            if ok and not (result.get("artwork") or {}).get("name"):
                return t["no_meta"], intent
            hold_artwork()  # keep it on screen while it's described
            return None, intent  # has metadata: let the AI describe it (and cache that)
        if intent == "show":
            q = m.group("q").strip()
            if q in ("all", "everything", "alt", "alle") or len(q) < 2:
                return None, None
            result, ok = run_tool("show", {"query": q})
            actions.append({"tool": "show", "args": {"query": q}, "ok": ok})
            if not ok:
                return None, intent
            if not result.get("shown"):
                reply = t["not_found"].format(q=q)
                names = (result.get("artists_in_collection") or [])[:3]
                if names:
                    reply += t["try_artists"].format(names=", ".join(names))
                return reply, intent
            art = result.get("now_showing") or {}
            # Use the artist's own spelling (XCOPY, not xcopy) when one matches.
            shown_as = next((a for a in result.get("artists", []) if q.casefold() in a.casefold()), q)
            return t["showing"].format(n=result["shown"], q=shown_as, name=art.get("name") or "?"), intent
    return None, None


@curator_bp.route("/api/curator/chat", methods=["POST"])
def curator_chat():
    data = request.get_json(silent=True) or {}
    history = [{"role": m["role"], "content": str(m["content"])[:4000]}
               for m in (data.get("messages") or [])
               if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
    history = history[-MAX_HISTORY:]
    if not history or history[-1]["role"] != "user":
        return jsonify({"error": "send at least one user message"}), 400
    while history and history[0]["role"] != "user":
        history.pop(0)
    cfg = load_config()
    provider = cfg["provider"]
    s = provider_settings(cfg, provider)
    question = history[-1]["content"]
    lang = reply_language(cfg, question)
    actions = []
    started = time.monotonic()

    def done(reply, source, model=None):
        # Talking about the piece on screen: keep it there until the owner moves on.
        tools_used = [a["tool"] for a in actions]
        if "now_showing" in tools_used and not set(tools_used) & STATE_CHANGING:
            hold_artwork()
        return jsonify({"reply": reply.strip(), "actions": actions, "provider": provider,
                        "model": model or s["model"], "source": source,
                        "ms": int((time.monotonic() - started) * 1000)})

    save_tokens = cfg.get("save_tokens", True)
    cache = load_cache() if save_tokens else None
    if save_tokens:
        reply, intent = local_answer(question, lang, actions)
        if reply:
            cache["stats"]["local"] += 1
            save_cache(cache)
            return done(reply, "local")
        # Same question about the same artwork as before: reuse the earlier answer.
        base = f"{lang}|{normalize(question)}|"
        hit = cache["answers"].get(base + current_file()) or cache["answers"].get(base)
        if hit:
            hit["hits"] = hit.get("hits", 0) + 1
            hit["ts"] = time.time()
            cache["stats"]["cached"] += 1
            save_cache(cache)
            actions.append({"tool": "saved answer", "args": {}, "ok": True})
            return done(hit["reply"], "cached")

    if PROVIDERS[provider]["needs_key"] and not s["key"]:
        return jsonify({"error": "no_key", "message": "Add an API key in Settings → AI Curator."}), 400
    try:
        resolve_model(provider, s)
        if not s["model"]:
            return jsonify({"error": "no_model", "message": "Choose a model in Settings → AI Curator."}), 400
        if provider == "claude":
            reply = chat_claude(s, history, actions)
        else:
            reply = chat_openai_compatible(s, history, actions)
    except ToolError as exc:
        return jsonify({"error": "provider", "message": str(exc), "actions": actions}), 502
    except Exception as exc:
        return jsonify({"error": "provider", "message": f"{type(exc).__name__}: {str(exc)[:300]}",
                        "actions": actions}), 502

    if save_tokens and reply.strip():
        cache["stats"]["ai"] += 1
        # Only answers that didn't change the screen can be replayed later.
        if not any(a["tool"] in STATE_CHANGING or a["tool"] == "archive_health" for a in actions):
            # Answers about the piece on screen are tied to it; general ones are not.
            about_screen = any(a["tool"] == "now_showing" for a in actions)
            cache["answers"][f"{lang}|{normalize(question)}|{current_file() if about_screen else ''}"] = {
                "reply": reply.strip(), "ts": time.time(), "hits": 0}
        save_cache(cache)
    return done(reply, "ai")


@curator_bp.route("/api/curator/client-log", methods=["POST"])
def curator_client_log():
    """Errors from the Curator page (e.g. a phone's browser), written to the service log."""
    data = request.get_json(silent=True) or {}
    msg = str(data.get("message", ""))[:500].replace("\n", " ")
    ua = request.headers.get("User-Agent", "")[:120]
    print(f"[curator-page] {request.remote_addr}: {msg} | {ua}", flush=True)
    return jsonify({"ok": True})


# -- Voice -----------------------------------------------------------------------

@curator_bp.route("/api/curator/speak", methods=["POST"])
def curator_speak():
    """Text to speech through a Piper http_server (on the frame or a computer at home)."""
    cfg = load_config()
    url = clean_server_url(cfg["voice"].get("piper_url"), allow_v1=False)
    if cfg["voice"].get("tts") != "piper" or not url:
        return jsonify({"error": "no_voice_server"}), 400
    text = str((request.get_json(silent=True) or {}).get("text", "")).strip()[:MAX_SPEAK_CHARS]
    if not text:
        return jsonify({"error": "no text"}), 400
    try:
        body = {"text": text}
        if cfg["voice"].get("piper_voice"):
            body["voice"] = cfg["voice"]["piper_voice"]
        r = requests.post(f"{url}/synthesize", json=body, timeout=60, allow_redirects=False)
    except requests.RequestException as exc:
        return jsonify({"error": f"voice server not reachable: {exc}"}), 502
    if r.status_code != 200 or not r.content.startswith(b"RIFF"):
        return jsonify({"error": f"voice server error {r.status_code}"}), 502
    # 16-bit audio always has an even number of data bytes; an odd count means the samples
    # are shifted and would play as loud noise (Piper does this with some --sentence-silence
    # values). Refuse it so the page falls back to the browser voice.
    i = r.content.find(b"data")
    if i < 0 or int.from_bytes(r.content[i + 4:i + 8], "little") % 2:
        return jsonify({"error": "voice server sent damaged audio (check --sentence-silence)"}), 502
    return Response(r.content, mimetype="audio/wav", headers={"Cache-Control": "no-store"})


def stt_keyterms():
    """Artist and collection names from the library, so 'XCOPY' isn't heard as 'x copy'."""
    try:
        nfts = api("/api/nft-metadata").get("nfts") or {}
    except ToolError:
        return []
    counts = {}
    for m in nfts.values():
        for k in ("artist", "collection"):
            name = m.get(k)
            if isinstance(name, str) and 1 < len(name.strip()) <= 40 and not NOT_A_NAME.match(name.strip()):
                counts[name.strip()] = counts.get(name.strip(), 0) + 1
    return [n for n, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:20]


@curator_bp.route("/api/curator/listen", methods=["POST"])
def curator_listen():
    """Speech to text: the browser's recording goes to Grok STT with the saved Grok key."""
    cfg = load_config()
    key = cfg["keys"].get("grok")
    if not key:
        return jsonify({"error": "no_key", "message": "Speech recognition uses Grok: add a Grok API key in Settings."}), 400
    audio = request.files.get("audio")
    if not audio:
        return jsonify({"error": "no audio"}), 400
    blob = audio.read(MAX_AUDIO_BYTES + 1)
    if not blob or len(blob) > MAX_AUDIO_BYTES:
        return jsonify({"error": "recording is empty or too long"}), 400
    fields = [("language", cfg["voice"].get("language", "en")), ("format", "true")]
    fields += [("keyterm", t) for t in stt_keyterms()]
    started = time.monotonic()
    try:
        r = requests.post(XAI_STT_URL, headers={"Authorization": f"Bearer {key}"}, data=fields,
                          files={"file": (audio.filename or "speech.webm", blob,
                                          audio.mimetype or "application/octet-stream")},
                          timeout=60, allow_redirects=False)
    except requests.RequestException as exc:
        return jsonify({"error": "stt", "message": f"Grok speech recognition not reachable: {exc}"}), 502
    if r.status_code != 200:
        return jsonify({"error": "stt", "message": f"Grok speech recognition error {r.status_code}: {r.text[:200]}"}), 502
    return jsonify({"text": (r.json().get("text") or "").strip(), "ms": int((time.monotonic() - started) * 1000)})


# -- Connected apps (MCP on the home network, paired with a token or QR code) ----

APPS_FILE = "/opt/vernis/curator-apps.json"
APP_KINDS = {"phone": "Phone", "lmstudio": "LM Studio", "claude-code": "Claude Code", "other": "AI app"}
PHONE_PATHS = ("/api/curator/chat", "/api/curator/speak", "/api/curator/listen", "/api/curator/client-log",
               "/api/curator/live/session", "/api/curator/tool", "/api/curator/hold")
MCP_INSTRUCTIONS = (
    "Tools for the owner's Vernis digital art frame, which shows their NFT collection. Act as a "
    "curator: use now_showing to see what is on screen and talk about it. Tools only read state or "
    "change what is displayed; they cannot delete, unpin or reach wallets."
)


def load_apps():
    try:
        with open(APPS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_apps(apps):
    tmp = APPS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(apps, f, indent=2)
    os.replace(tmp, APPS_FILE)


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def app_for_token(token):
    """The connected app a token belongs to, or None. Records when it was last used."""
    if not token or not token.startswith("vrn_"):
        return None
    digest = _hash(token)
    apps = load_apps()
    for a in apps:
        if hmac.compare_digest(a.get("hash", ""), digest):
            now = int(time.time())
            if now - a.get("last_used", 0) > 60:
                a["last_used"] = now
                save_apps(apps)
            return a
    return None


def phone_request_allowed(req):
    """Lets a paired phone use the curator in Locked mode without a PIN (chat and voice only)."""
    return req.path in PHONE_PATHS and app_for_token(req.headers.get("X-Vernis-App-Token", "")) is not None


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def qr_data_uri(text):
    import qrcode
    img = qrcode.make(text, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@curator_bp.route("/api/curator/apps", methods=["GET"])
def curator_apps():
    return jsonify({"apps": [{k: a.get(k) for k in ("id", "name", "kind", "created", "last_used")}
                             for a in load_apps()]})


@curator_bp.route("/api/curator/apps", methods=["POST"])
def curator_add_app():
    data = request.get_json(silent=True) or {}
    kind = data.get("kind") if data.get("kind") in APP_KINDS else "other"
    token = "vrn_" + secrets.token_urlsafe(24)
    apps = load_apps()
    taken = {a["name"] for a in apps}
    name, n = APP_KINDS[kind], 2
    while name in taken:
        name, n = f"{APP_KINDS[kind]} {n}", n + 1
    app_id = secrets.token_hex(4)
    apps.append({"id": app_id, "name": name, "kind": kind, "hash": _hash(token),
                 "created": int(time.time()), "last_used": 0})
    save_apps(apps)
    base = f"http://{lan_ip()}"
    mcp_url = f"{base}/api/mcp"
    out = {"id": app_id, "name": name, "kind": kind, "token": token, "mcp_url": mcp_url}
    if kind == "phone":
        # The token rides in the #fragment, which browsers never send to a server.
        out["phone_url"] = f"{base}/curator.html#pair={token}"
        out["qr"] = qr_data_uri(out["phone_url"])
    elif kind == "claude-code":
        out["snippet"] = (f'claude mcp add --transport http vernis {mcp_url} '
                          f'--header "Authorization: Bearer {token}"')
    else:
        out["snippet"] = json.dumps({"mcpServers": {"vernis": {
            "url": mcp_url, "headers": {"Authorization": f"Bearer {token}"}}}}, indent=2)
    return jsonify(out)


@curator_bp.route("/api/curator/apps/remove", methods=["POST"])
def curator_remove_app():
    app_id = (request.get_json(silent=True) or {}).get("id")
    apps = load_apps()
    kept = [a for a in apps if a.get("id") != app_id]
    if len(kept) == len(apps):
        return jsonify({"error": "not found"}), 404
    save_apps(kept)
    return jsonify({"success": True})


def _mcp_reply(msg):
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:
        return None  # notification
    params = msg.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "vernis", "title": "Vernis art frame", "version": "1.0"},
                  "instructions": MCP_INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": p,
                             "annotations": {"readOnlyHint": n in ("now_showing", "archive_health", "list_artists", "find_artworks"),
                                             "destructiveHint": False}}
                            for n, d, p in tool_schemas()]}
    elif method == "tools/call":
        name = params.get("name", "")
        if name not in TOOLS:
            result = {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}
        else:
            payload, ok = run_tool(name, params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
            if ok:
                result["structuredContent"] = payload
            else:
                result["isError"] = True
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


@curator_bp.route("/api/mcp", methods=["GET", "POST", "DELETE"])
def curator_mcp():
    """MCP (streamable HTTP, JSON responses) for AI apps on the home network."""
    origin = request.headers.get("Origin")
    if origin and urllib.parse.urlparse(origin).hostname not in (lan_ip(), "localhost", "127.0.0.1"):
        return jsonify({"error": "origin not allowed"}), 403
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if app_for_token(token) is None:
        time.sleep(0.5)  # slow down guessing
        return (jsonify({"error": "Connect this app in Vernis Settings → AI Curator → Connect an app."}),
                401, {"WWW-Authenticate": "Bearer"})
    if request.method != "POST":
        return "", 405  # no server-initiated stream; JSON responses only
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}), 400
    if isinstance(body, list):
        replies = [r for r in (_mcp_reply(m) for m in body if isinstance(m, dict)) if r]
        return (jsonify(replies), 200) if replies else ("", 202)
    reply = _mcp_reply(body)
    return (jsonify(reply), 200) if reply else ("", 202)


# -- Live mode: real-time speech with Grok Voice Agent -----------------------------
# The browser talks straight to xAI over a WebSocket using a short-lived client
# secret minted here (the real key never leaves the frame). Tool calls come back
# to the frame through /api/curator/tool.

XAI_CLIENT_SECRETS_URL = "https://api.x.ai/v1/realtime/client_secrets"
LIVE_MODEL = "grok-voice-think-fast-1.0"
LIVE_VOICES = ("Ara", "Eve", "Rex", "Sal", "Leo")
LIVE_INSTRUCTIONS = SYSTEM_PROMPT + (
    " This is a live spoken conversation: answer in one short sentence unless asked for more, "
    "and say a few words before you use a tool so there is no silence."
)


@curator_bp.route("/api/curator/live/session", methods=["POST"])
def curator_live_session():
    cfg = load_config()
    key = cfg["keys"].get("grok")
    if not key:
        return jsonify({"error": "no_key", "message": "Live mode uses Grok: add a Grok API key in Settings."}), 400
    try:
        r = requests.post(XAI_CLIENT_SECRETS_URL, headers={"Authorization": f"Bearer {key}"},
                          json={"expires_after": {"seconds": 300}}, timeout=15, allow_redirects=False)
    except requests.RequestException as exc:
        return jsonify({"error": "live", "message": f"Could not reach Grok: {exc}"}), 502
    if r.status_code != 200 or not r.json().get("value"):
        return jsonify({"error": "live", "message": f"Grok refused a live session ({r.status_code})."}), 502
    voice = cfg["voice"].get("live_voice") if cfg["voice"].get("live_voice") in LIVE_VOICES else "Ara"
    tools = [{"type": "function", "name": n, "description": d, "parameters": p} for n, d, p in tool_schemas()]
    return jsonify({
        "token": r.json()["value"], "expires_at": r.json().get("expires_at"),
        "url": f"wss://api.x.ai/v1/realtime?model={LIVE_MODEL}",
        "session": {"voice": voice, "instructions": LIVE_INSTRUCTIONS,
                    "turn_detection": {"type": "server_vad"},
                    "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000}},
                              "output": {"format": {"type": "audio/pcm", "rate": 24000}}},
                    "tools": tools},
    })


@curator_bp.route("/api/curator/tool", methods=["POST"])
def curator_tool():
    """Run one frame tool for Live mode (the browser relays Grok's tool calls here)."""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "")
    args = data.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except ValueError:
            args = {}
    result, ok = run_tool(name, args)
    if ok and name == "now_showing" and result.get("gallery_running") and hold_artwork():
        # Keep the piece on screen while it's talked about, and tell the model so.
        result["slideshow"] = "paused on this piece while you talk about it; it continues when the owner says so"
    return jsonify({"ok": ok, "result": result})


@curator_bp.route("/api/curator/hold", methods=["POST"])
def curator_hold():
    """The owner started talking: keep the artwork on screen right away (auto-resumes later)."""
    return jsonify({"held": hold_artwork()})
