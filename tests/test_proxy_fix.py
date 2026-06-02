"""ProxyFix: Flask must read real client IP from X-Forwarded-For."""
import importlib


def test_proxy_fix_reads_forwarded_for():
    import app
    importlib.reload(app)
    client = app.app.test_client()
    captured = {}

    @app.app.route("/__test_remote_pf")
    def _capture():
        from flask import request
        captured["remote"] = request.remote_addr
        return "ok"

    client.get(
        "/__test_remote_pf",
        headers={"X-Forwarded-For": "10.0.0.99"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert captured["remote"] == "10.0.0.99"


def test_proxy_fix_only_trusts_one_hop():
    import app
    importlib.reload(app)
    client = app.app.test_client()
    captured = {}

    @app.app.route("/__test_remote_pf2")
    def _capture():
        from flask import request
        captured["remote"] = request.remote_addr
        return "ok"

    client.get(
        "/__test_remote_pf2",
        headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.99"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert captured["remote"] == "10.0.0.99"
