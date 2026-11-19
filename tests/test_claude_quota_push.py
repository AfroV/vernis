"""Tests for the Mac helper's reading of `claude -p /usage` output."""
import importlib.util
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_spec = importlib.util.spec_from_file_location(
    "claude_quota_push", Path(__file__).resolve().parent.parent / "scripts" / "claude-quota-push.py")
cqp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cqp)

OSLO = ZoneInfo("Europe/Oslo")

REAL = """You are currently using your subscription to power your Claude Code usage

Current session: 29% used · resets Nov 18 at 5:20am (Europe/Oslo)
Current week (all models): 14% used · resets Nov 24 at 6am (Europe/Oslo)

What's contributing to your usage?
Last 24h · 405 requests · 5 sessions
  86%  Start fresh when you switch tasks · run /clear
"""


def test_reads_session_and_week():
    w = cqp.parse_usage(REAL)
    assert set(w) == {"five_hour", "seven_day"}
    assert w["five_hour"]["utilization"] == 29.0
    assert w["seven_day"]["utilization"] == 14.0


def test_ignores_the_contribution_percentages():
    # "86%  Start fresh…" must not be taken for a quota window
    assert len(cqp.parse_usage(REAL)) == 2


def test_reset_times_in_the_stated_zone():
    now = datetime(2026, 11, 18, 1, 0, tzinfo=OSLO)
    assert cqp.parse_reset("Nov 18 at 5:20am (Europe/Oslo)", now) == "2026-11-18T05:20:00+01:00"
    assert cqp.parse_reset("Nov 24 at 6am (Europe/Oslo)", now) == "2026-11-24T06:00:00+01:00"
    assert cqp.parse_reset("Nov 24 at 6pm (Europe/Oslo)", now) == "2026-11-24T18:00:00+01:00"
    assert cqp.parse_reset("Nov 24 at 12am (Europe/Oslo)", now) == "2026-11-24T00:00:00+01:00"


def test_reset_without_a_date_is_the_next_one():
    now = datetime(2026, 11, 18, 23, 0, tzinfo=OSLO)
    assert cqp.parse_reset("2:00am (Europe/Oslo)", now) == "2026-11-19T02:00:00+01:00"


def test_reset_across_new_year():
    now = datetime(2026, 12, 30, 12, 0, tzinfo=OSLO)
    assert cqp.parse_reset("Jan 2 at 6am (Europe/Oslo)", now) == "2027-01-02T06:00:00+01:00"


@pytest.mark.parametrize("bad", ["soon", "in 3 hours", "Foo 2 at 6am", "Nov 40 at 6am", "25:00"])
def test_unreadable_reset_gives_none(bad):
    assert cqp.parse_reset(bad) is None


def test_model_specific_week_gets_a_valid_frame_name():
    w = cqp.parse_usage("Current week (Sonnet only): 3% used · resets Nov 24 at 6am (Europe/Oslo)")
    assert list(w) == ["seven_day_sonnet"]


def test_missing_reset_is_kept_as_unknown():
    w = cqp.parse_usage("Current session: 5% used")
    assert w["five_hour"] == {"utilization": 5.0, "resets_at": None}


def test_nothing_recognisable():
    assert cqp.parse_usage("You are not logged in. Run claude auth login.") == {}


def test_hook_does_nothing_inside_our_own_claude_run(monkeypatch):
    monkeypatch.setenv(cqp.CHILD_ENV, "1")
    monkeypatch.setattr(cqp, "run", lambda **k: pytest.fail("must not run"))
    assert cqp.hook() == 0


def test_hook_is_debounced(tmp_path, monkeypatch):
    monkeypatch.delenv(cqp.CHILD_ENV, raising=False)
    monkeypatch.setattr(cqp, "DIR", str(tmp_path))
    monkeypatch.setattr(cqp, "STAMP", str(tmp_path / "last-run"))
    monkeypatch.setattr(cqp, "LOCK", str(tmp_path / "run.lock"))
    monkeypatch.setattr(cqp.sys, "stdin", open(__file__))
    calls = []
    monkeypatch.setattr(cqp, "run", lambda **k: calls.append(1))
    cqp.hook()
    monkeypatch.setattr(cqp.sys, "stdin", open(__file__))
    cqp.hook()
    assert calls == [1]
