"""bcrypt PIN/owner-password helpers."""
import importlib

import pytest


@pytest.fixture
def fresh_app():
    import app
    importlib.reload(app)
    return app


def test_hash_pin_returns_bcrypt_hash(fresh_app):
    h = fresh_app.hash_pin("123456")
    assert h.startswith("$2b$") or h.startswith("$2a$")
    assert len(h) >= 60


def test_verify_pin_accepts_correct(fresh_app):
    h = fresh_app.hash_pin("482919")
    assert fresh_app.verify_pin("482919", h) is True


def test_verify_pin_rejects_wrong(fresh_app):
    h = fresh_app.hash_pin("482919")
    assert fresh_app.verify_pin("000000", h) is False


def test_verify_pin_rejects_empty(fresh_app):
    h = fresh_app.hash_pin("482919")
    assert fresh_app.verify_pin("", h) is False
    assert fresh_app.verify_pin(None, h) is False


def test_hash_pin_rejects_bad_shape(fresh_app):
    with pytest.raises(ValueError):
        fresh_app.hash_pin("abc")
    with pytest.raises(ValueError):
        fresh_app.hash_pin("12345")


def test_owner_password_roundtrip(fresh_app):
    h = fresh_app.hash_owner_password("test-password")
    assert fresh_app.verify_owner_password("test-password", h) is True
    assert fresh_app.verify_owner_password("wrong", h) is False
