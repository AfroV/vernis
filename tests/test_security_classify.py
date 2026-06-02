"""Endpoint classification."""
import importlib

import pytest


@pytest.fixture
def fresh_app():
    import app
    importlib.reload(app)
    return app


@pytest.mark.parametrize("path,method,expected", [
    ("/api/version", "GET", "read"),
    ("/api/nft-list", "GET", "read"),
    ("/api/qrcode", "GET", "read"),
    ("/api/screen-color", "GET", "read"),
    ("/api/download-progress", "GET", "read"),
    ("/api/security/config", "GET", "security"),
    ("/api/security/login", "POST", "security"),
    ("/api/security/recover", "POST", "security"),
    ("/api/nft-delete", "POST", "delete"),
    ("/api/csv-library/delete", "POST", "delete"),
    ("/api/csv-library/clear-files", "POST", "delete"),
    ("/api/carousels/MyList", "DELETE", "delete"),
    ("/api/backup/delete", "POST", "delete"),
    ("/api/files/delete", "POST", "delete"),
    ("/api/setup/complete", "DELETE", "delete"),
    ("/api/thumbnails/clear", "POST", "delete"),
    ("/api/clear-cache", "POST", "delete"),
    ("/api/ipfs/gc", "POST", "delete"),
    ("/api/burner/cache", "DELETE", "delete"),
    ("/api/hue/disconnect", "POST", "delete"),
    ("/api/storage/external/migrate", "POST", "delete"),
    ("/api/https", "DELETE", "delete"),
    ("/api/security/pin", "DELETE", "delete"),
    ("/api/setup/change-password", "POST", "delete"),
    ("/api/theme", "POST", "control"),
    ("/api/display-config", "POST", "control"),
    ("/api/hue/set-color", "POST", "control"),
    ("/api/csv-library/install", "POST", "control"),
    ("/api/carousels", "POST", "control"),
    ("/api/remote/command", "POST", "control"),
    ("/api/screen/brightness", "POST", "control"),
])
def test_classify(fresh_app, path, method, expected):
    assert fresh_app.classify_endpoint(path, method) == expected


def test_bootstrap_when_no_config_file(fresh_app, tmp_path, monkeypatch):
    monkeypatch.setattr(fresh_app, "SECURITY_CONFIG_FILE", tmp_path / "missing.json")
    assert fresh_app.classify_endpoint("/api/setup/quick-import", "POST") == "bootstrap"


def test_setup_normal_once_config_exists(fresh_app, tmp_path, monkeypatch):
    f = tmp_path / "security.json"
    f.write_text(
        '{"version":1,"mode":"A","pin_hash":null,"owner_pwd_hash":null,'
        '"recovery_logo_enabled":true,"created_at":""}'
    )
    monkeypatch.setattr(fresh_app, "SECURITY_CONFIG_FILE", f)
    assert fresh_app.classify_endpoint("/api/setup/change-password", "POST") == "delete"
    assert fresh_app.classify_endpoint("/api/setup/complete", "DELETE") == "delete"
    assert fresh_app.classify_endpoint("/api/setup/quick-import", "POST") == "control"
