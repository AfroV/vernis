"""Per-IP cooldown schedule (no global lockout)."""
import importlib

import pytest


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    import app
    importlib.reload(app)
    monkeypatch.setattr(app, "FAILURES_FILE", tmp_path / "failures.json")
    return app


# Schedule under test:
#   1-6 failures   → 0 s cooldown
#   7-10 failures  → 30 s
#   11-15 failures → 120 s
#   16+ failures   → 3600 s


def test_first_six_no_cooldown(fresh_app):
    for _ in range(6):
        r = fresh_app.record_failure("10.0.0.42")
        assert r["per_ip_cooldown"] == 0


def test_seventh_triggers_30s(fresh_app):
    for _ in range(6):
        fresh_app.record_failure("10.0.0.42")
    r = fresh_app.record_failure("10.0.0.42")
    assert r["per_ip_cooldown"] == 30


def test_tenth_still_30s(fresh_app):
    for _ in range(9):
        fresh_app.record_failure("10.0.0.42")
    r = fresh_app.record_failure("10.0.0.42")
    assert r["per_ip_cooldown"] == 30


def test_eleventh_triggers_120s(fresh_app):
    for _ in range(10):
        fresh_app.record_failure("10.0.0.42")
    r = fresh_app.record_failure("10.0.0.42")
    assert r["per_ip_cooldown"] == 120


def test_sixteenth_caps_3600s(fresh_app):
    for _ in range(15):
        fresh_app.record_failure("10.0.0.42")
    r = fresh_app.record_failure("10.0.0.42")
    assert r["per_ip_cooldown"] == 3600


def test_record_failure_no_longer_returns_hard_locked(fresh_app):
    """Hard-lock concept removed entirely from the API surface."""
    r = fresh_app.record_failure("10.0.0.42")
    assert "hard_locked" not in r


def test_clear_failures_resets_one_ip(fresh_app):
    for _ in range(8):
        fresh_app.record_failure("10.0.0.42")
    fresh_app.record_failure("10.0.0.99")
    fresh_app.clear_failures("10.0.0.42")
    assert fresh_app.cooldown_remaining("10.0.0.42") == 0
    # Other IP unaffected
    assert fresh_app.attempts_count("10.0.0.99") == 1


def test_clear_all_failures_resets_everything(fresh_app):
    for i in range(20):
        fresh_app.record_failure(f"10.0.0.{i}")
    fresh_app.clear_all_failures()
    assert fresh_app.attempts_count("10.0.0.5") == 0


def test_attempts_count(fresh_app):
    for _ in range(4):
        fresh_app.record_failure("10.0.0.42")
    assert fresh_app.attempts_count("10.0.0.42") == 4
    assert fresh_app.attempts_count("10.0.0.99") == 0


def test_next_cooldown_predicts_next_tier(fresh_app):
    """next_cooldown returns the cooldown the NEXT failure would trigger."""
    assert fresh_app.next_cooldown("10.0.0.42") == 0  # 1st failure: still in 1-6 tier
    for _ in range(5):
        fresh_app.record_failure("10.0.0.42")
    # Now 5 failures; the 6th would still be 0 cooldown
    assert fresh_app.next_cooldown("10.0.0.42") == 0
    fresh_app.record_failure("10.0.0.42")
    # 6 failures; the 7th would trigger the 30 s tier
    assert fresh_app.next_cooldown("10.0.0.42") == 30
    for _ in range(4):
        fresh_app.record_failure("10.0.0.42")
    # 10 failures; the 11th would trigger 120 s
    assert fresh_app.next_cooldown("10.0.0.42") == 120


def test_failures_file_drops_legacy_global_fields_on_load(fresh_app):
    """Older devices may have security-failures.json with the old schema
    that included `global` and `hard_locked_at`. Load gracefully."""
    legacy = {
        "by_ip": {"10.0.0.5": [1.0]},
        "global": [1.0, 2.0],
        "hard_locked_at": 999.0,
    }
    fresh_app.FAILURES_FILE.write_text(__import__("json").dumps(legacy))
    data = fresh_app._load_failures()
    assert "global" not in data
    assert "hard_locked_at" not in data
    assert data["by_ip"] == {"10.0.0.5": [1.0]}
