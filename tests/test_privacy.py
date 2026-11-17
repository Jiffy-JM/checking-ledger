"""Checks that nothing in the app talks to the internet."""
import io
import pathlib
import re
import socket

import pytest

from app import create_app

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt to open a network connection fails the test."""
    def blocked(*args, **kwargs):
        raise AssertionError(f"Network access attempted: {args!r}")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


def test_every_page_and_action_works_with_the_network_blocked(tmp_path, no_network):
    from datetime import date
    app = create_app(data_dir=str(tmp_path), password="pw", today=lambda: date(2026, 9, 20))
    c = app.test_client()

    def tok(path):
        return re.search(r'name="_csrf" value="([^"]+)"', c.get(path).get_data(as_text=True)).group(1)

    c.post("/login", data={"_csrf": tok("/login"), "password": "pw"})
    t = tok("/setup")
    c.post("/setup", data={"_csrf": t, "balance": "3200", "date": "2026-09-01", "pay": "2000", "pay_date": "2026-09-05"})
    c.post("/transactions/new", data={"_csrf": t, "description": "Visa", "direction": "out", "amount": "50",
                                      "category": "creditcard", "date": "2026-09-20"})
    c.post("/balance", data={"_csrf": t, "date": "2026-09-20", "balance": ""})
    c.post("/networth/accounts", data={"_csrf": t, "name": "Savings", "kind": "asset"})
    c.post("/networth/record", data={"_csrf": t, "date": "2026-09-20", "account": ["Savings"], "amount": ["100"]})
    for path in ("/", "/?h=2w", "/transactions", "/transactions/new", "/history", "/networth",
                 "/download", "/networth/download", "/static/app.css", "/static/app.js", "/help", "/appearance",
                 "/cards/new", "/pay/new", "/?wi_amount=250&wi_date=2026-10-01&wi_dir=out"):
        assert c.get(path).status_code == 200, path
    csv_bytes = c.get("/download").get_data()
    assert c.post("/upload", data={"_csrf": t, "file": (io.BytesIO(csv_bytes), "l.csv")},
                  content_type="multipart/form-data").status_code == 302


def test_no_outside_addresses_in_anything_the_browser_loads():
    files = list((ROOT / "templates").glob("*.html")) + [
        ROOT / "static" / "app.js", ROOT / "static" / "app.css", ROOT / "static" / "manifest.webmanifest"]
    found = {}
    for f in files:
        text = f.read_text(encoding="utf-8")
        if f.suffix == ".css":
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)   # license comments can't be fetched
        hits = re.findall(r"(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}", text, re.I)
        if hits:
            found[f.name] = hits
    assert found == {}


def test_no_outbound_code_in_the_server():
    for f in (ROOT / "app.py", ROOT / "ledger_core.py", ROOT / "networth.py",
              ROOT / "themes.py", ROOT / "backup_status.py"):
        text = f.read_text(encoding="utf-8")
        for needle in ("import requests", "urllib.request", "http.client", "smtplib", "socket.", "subprocess",
                       "boto", "restic", "AWS_", "RESTIC_"):
            assert needle not in text, f"{needle} in {f.name}"


def test_browser_is_told_to_only_talk_to_this_server(tmp_path):
    c = create_app(data_dir=str(tmp_path), password="").test_client()
    csp = c.get("/setup").headers["Content-Security-Policy"]
    for rule in ("default-src 'self'", "connect-src 'self'", "script-src 'self'", "form-action 'self'"):
        assert rule in csp
