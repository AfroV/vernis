"""Wallet import: original artwork instead of previews, no reliance on the dead
ipfs.io gateway, a clear ask for an OpenSea key, and an IPFS-node warning.

Metadata samples are real SuperRare token metadata (v1 token 1, v2 token 9000)
as served from ipfs.pixura.io.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest
import requests

LAN = {"REMOTE_ADDR": "10.0.0.42"}

SR_V2_VIDEO = {
    "name": "SPRING HOPE/S",
    "image": "https://ipfs.pixura.io/ipfs/Qmd9joEX3fWfk8AZZJBuji4ts6GGjAxgcJffXKWQMc6fvC/bridge0001.00_00_04_18.Still001.jpg",
    "media": {
        "uri": "https://ipfs.pixura.io/ipfs/QmeBKD2RJ5dbG2dZWZPAX8rgaJiid2gLEP24SpwXYEZ4iB/bridge0001_122.mp4",
        "dimensions": "1728x2476", "size": "17726121", "mimeType": "video/mp4",
    },
}
SR_V1_IMAGE = {
    "name": "AI Generated Nude Portrait #1",
    "image": "https://ipfs.pixura.io/ipfs/QmX4ECCmA4HZSPxzsgq8CxwL9abFu7jTBCCersuiC9Pw6d",
}
CID_A = "QmPGU4jqMd1yEYeg6bXwkoLAns9JUXUdTRBuLhCbj5Cd9H"
CID_B = "QmP8o5x3YaVN6TCwUPuhSiQhapj5dP31CAigE2mzt3b3ZB"


@pytest.fixture
def wapp(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "SECURITY_CONFIG_FILE", tmp_path / "security.json")
    monkeypatch.setattr(app, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(app, "FAILURES_FILE", tmp_path / "failures.json")
    monkeypatch.setattr(app, "AUDIT_LOG_PATH", tmp_path / "audit.log")
    monkeypatch.setattr(app, "OPENSEA_KEY_FILE", tmp_path / "opensea-key.json")
    monkeypatch.setattr(app, "OPENSEA_KEY_STATUS_FILE", tmp_path / "opensea-key-status.json")
    monkeypatch.delenv("OPENSEA_API_KEY", raising=False)
    return app


@pytest.fixture
def downloader():
    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    sys.path.insert(0, scripts)
    try:
        import nft_downloader_advanced
        yield importlib.reload(nft_downloader_advanced)
    finally:
        sys.path.remove(scripts)


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


# --- which file is the artwork ------------------------------------------------

PICK_CASES = [
    ("superrare video: original in media.uri, not the still", SR_V2_VIDEO, SR_V2_VIDEO["media"]["uri"]),
    ("plain image", SR_V1_IMAGE, SR_V1_IMAGE["image"]),
    ("video in animation_url", {"image": f"ipfs://{CID_A}", "animation_url": f"ipfs://{CID_B}/art.mp4"},
     f"ipfs://{CID_B}/art.mp4"),
    ("video by animation_details", {"image": f"ipfs://{CID_A}", "animation_url": f"ipfs://{CID_B}",
                                    "animation_details": {"format": "MP4"}}, f"ipfs://{CID_B}"),
    ("html animation keeps the image", {"image": f"ipfs://{CID_A}", "animation_url": f"ipfs://{CID_B}/index.html"},
     f"ipfs://{CID_A}"),
    ("audio animation keeps the image", {"image": f"ipfs://{CID_A}", "animation_url": f"ipfs://{CID_B}/song.mp3"},
     f"ipfs://{CID_A}"),
    ("audio in media keeps the image", {"image": f"ipfs://{CID_A}",
                                        "media": {"uri": f"ipfs://{CID_B}", "mimeType": "audio/mpeg"}},
     f"ipfs://{CID_A}"),
    ("nifty gateway bare hash", {"image": "https://cdn.example/x.png", "image_hash": CID_A}, f"ipfs://{CID_A}"),
]


@pytest.mark.parametrize("label,metadata,expected", PICK_CASES, ids=[c[0] for c in PICK_CASES])
def test_pick_artwork_backend(wapp, label, metadata, expected):
    assert wapp._pick_artwork_uri(metadata) == expected


@pytest.mark.parametrize("label,metadata,expected", PICK_CASES, ids=[c[0] for c in PICK_CASES])
def test_pick_artwork_downloader_agrees(downloader, label, metadata, expected):
    assert downloader.pick_artwork_uri(metadata) == expected


# --- gateways -------------------------------------------------------------------

def test_fetch_urls_local_node_first_and_never_ipfs_io(wapp):
    urls = wapp._ipfs_fetch_urls(f"https://ipfs.pixura.io/ipfs/{CID_A}/metadata.json")
    assert urls[0] == f"http://127.0.0.1:8080/ipfs/{CID_A}/metadata.json"
    assert urls[-1] == f"https://ipfs.pixura.io/ipfs/{CID_A}/metadata.json"
    assert not any("ipfs.io/" in u and "pixura" not in u for u in urls)
    assert wapp._ipfs_fetch_urls(f"ipfs://ipfs/{CID_A}")[0] == f"http://127.0.0.1:8080/ipfs/{CID_A}"
    assert wapp._ipfs_fetch_urls("ar://abc") == ["https://arweave.net/abc"]
    assert wapp._ipfs_fetch_urls("https://api.example/1") == ["https://api.example/1"]


def test_resolve_superrare_with_node_down(wapp, monkeypatch):
    """Node down + pixura metadata: falls through to a public gateway, picks the
    mp4, and tries the dead local node only once for the whole batch."""
    calls = []

    def fake_get(url, timeout=None, headers=None):
        calls.append(url)
        if url.startswith("http://127.0.0.1:8080"):
            raise requests.exceptions.ConnectionError("refused")
        if "pinata" in url:
            return FakeResp(200, SR_V2_VIDEO if CID_A in url else SR_V1_IMAGE)
        return FakeResp(404)

    monkeypatch.setattr(wapp.requests, "get", fake_get)
    nfts = [
        {"image_url": "https://i.seadn.io/still.jpg?w=500",
         "metadata_url": f"https://ipfs.pixura.io/ipfs/{CID_A}/metadata.json"},
        {"image_url": "https://i.seadn.io/other.jpg?w=500",
         "metadata_url": f"https://ipfs.pixura.io/ipfs/{CID_B}"},
    ]
    wapp._resolve_nft_metadata(nfts, max_workers=1)

    assert nfts[0]["image_url"].endswith("bridge0001_122.mp4")
    assert nfts[0]["cid"] == "QmeBKD2RJ5dbG2dZWZPAX8rgaJiid2gLEP24SpwXYEZ4iB/bridge0001_122.mp4"
    assert nfts[1]["cid"] == "QmX4ECCmA4HZSPxzsgq8CxwL9abFu7jTBCCersuiC9Pw6d"
    assert sum(u.startswith("http://127.0.0.1") for u in calls) == 1


def test_resolve_keeps_opensea_url_for_onchain_svg(wapp, monkeypatch):
    monkeypatch.setattr(wapp.requests, "get",
                        lambda url, **kw: FakeResp(200, {"image": "data:image/svg+xml;base64,PHN2Zy8+"}))
    nfts = [{"image_url": "https://i.seadn.io/x.png", "metadata_url": "https://api.example/1"}]
    wapp._resolve_nft_metadata(nfts)
    assert nfts[0]["image_url"] == "https://i.seadn.io/x.png"


# --- OpenSea key ------------------------------------------------------------------

def test_no_builtin_key(wapp):
    assert wapp._get_opensea_key() == ""


@pytest.mark.parametrize("endpoint", ["/api/setup/quick-import", "/api/fetch-wallet-nfts"])
def test_import_without_key_asks_for_one(wapp, monkeypatch, endpoint):
    def no_network(*a, **kw):
        raise AssertionError("must not call OpenSea without a key")
    monkeypatch.setattr(requests, "get", no_network)
    r = wapp.app.test_client().post(endpoint, json={"wallet": "0x" + "1" * 40, "chains": ["ethereum"]},
                                    environ_overrides=LAN)
    body = r.get_json()
    assert r.status_code == 400
    assert body["needs_opensea_key"] is True
    assert "opensea.io/settings/developer" in body["error"]


@pytest.mark.parametrize("endpoint", ["/api/setup/quick-import", "/api/fetch-wallet-nfts"])
def test_rejected_key_is_not_reported_as_empty_wallet(wapp, monkeypatch, endpoint):
    wapp.OPENSEA_KEY_FILE.write_text(json.dumps({"key": "expired"}))
    monkeypatch.setattr(requests, "get", lambda *a, **kw: FakeResp(401, {"errors": ["API key has expired"]}))
    r = wapp.app.test_client().post(endpoint, json={"wallet": "0x" + "1" * 40, "chains": ["ethereum"]},
                                    environ_overrides=LAN)
    body = r.get_json()
    assert r.status_code == 401
    assert body["needs_opensea_key"] is True
    assert "expired" in body["error"]
    assert "No art NFTs" not in json.dumps(body)


# --- IPFS node liveness -------------------------------------------------------------

def test_node_online_means_gateway_answers(wapp, monkeypatch):
    def refused(*a, **kw):
        raise requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(wapp.requests, "get", refused)
    assert wapp._ipfs_node_online() is False
    monkeypatch.setattr(wapp.requests, "get", lambda *a, **kw: FakeResp(200, {}))
    assert wapp._ipfs_node_online() is True


def test_download_progress_warns_when_downloader_had_no_node(wapp, monkeypatch, tmp_path):
    nft_dir = tmp_path / "nfts"
    nft_dir.mkdir()
    monkeypatch.setattr(wapp, "get_active_nft_dir", lambda *a, **kw: nft_dir)
    monkeypatch.setattr(wapp, "_ipfs_node_online", lambda *a, **kw: False)
    progress = {"completed": 1, "total": 2, "downloaded": [], "failed": {}, "local_ipfs": False}
    (nft_dir / "download_progress.json").write_text(json.dumps(progress))
    client = wapp.app.test_client()

    body = client.get("/api/download-progress", environ_overrides=LAN).get_json()
    assert "Restart Node" in body["ipfs_warning"]

    progress["local_ipfs"] = True
    (nft_dir / "download_progress.json").write_text(json.dumps(progress))
    body = client.get("/api/download-progress", environ_overrides=LAN).get_json()
    assert body["ipfs_warning"] is None
