"""Checks added after the security review."""
import io
import re
from datetime import date

from app import create_app
import ledger_core as core

TODAY = date(2026, 9, 20)


def token(client, path="/setup"):
    return re.search(r'name="_csrf" value="([^"]+)"', client.get(path).get_data(as_text=True)).group(1)


def sign_in(client, password):
    return client.post("/login", data={"_csrf": token(client, "/login"), "password": password})


def test_changing_the_password_signs_out_existing_sessions(tmp_path):
    old = create_app(data_dir=str(tmp_path), password="first", today=lambda: TODAY).test_client()
    sign_in(old, "first")
    assert old.get("/setup").status_code == 200
    cookie = old.get_cookie("session").value

    same = create_app(data_dir=str(tmp_path), password="first", today=lambda: TODAY).test_client()
    same.set_cookie("session", cookie)
    assert same.get("/setup").status_code == 200           # a restart keeps you signed in

    changed = create_app(data_dir=str(tmp_path), password="second", today=lambda: TODAY).test_client()
    changed.set_cookie("session", cookie)
    assert "/login" in changed.get("/setup").headers["Location"]


def test_a_session_from_before_this_check_is_not_accepted(tmp_path):
    app = create_app(data_dir=str(tmp_path), password="pw", today=lambda: TODAY)
    c = app.test_client()
    with c.session_transaction() as s:
        s["auth"] = True
    assert "/login" in c.get("/setup").headers["Location"]


def test_login_never_redirects_to_another_site(tmp_path):
    app = create_app(data_dir=str(tmp_path), password="pw", today=lambda: TODAY)
    for target in ("//evil.example", "/\\evil.example", "https://evil.example", "/\tevil.example"):
        c = app.test_client()
        t = token(c, "/login")
        where = c.post("/login", query_string={"next": target}, data={"_csrf": t, "password": "pw"}).headers["Location"]
        assert where.startswith("/") and not where.startswith(("//", "/\\")), (target, where)


def test_allowed_hosts_refuses_other_addresses(tmp_path):
    app = create_app(data_dir=str(tmp_path), password="", today=lambda: TODAY, allowed_hosts="192.168.1.50, Ledger.local")
    c = app.test_client()
    assert c.get("/setup", headers={"Host": "192.168.1.50:3000"}).status_code == 200
    assert c.get("/setup", headers={"Host": "ledger.local"}).status_code == 200
    for path in ("/setup", "/download", "/static/app.js"):
        r = c.get(path, headers={"Host": "attacker.example:3000"})
        assert r.status_code == 400, path
        assert b"type,date" not in r.get_data()
    assert c.get("/healthz", headers={"Host": "127.0.0.1:3000"}).status_code == 200   # Docker's health check


def test_without_allowed_hosts_any_address_works(tmp_path):
    c = create_app(data_dir=str(tmp_path), password="", today=lambda: TODAY).test_client()
    assert c.get("/setup", headers={"Host": "anything.example"}).status_code == 200


def test_uploaded_ids_are_replaced_unless_plain():
    text = ('id,type,date,description,category,amount\n'
            '"=HYPERLINK(""http://x"",""a"")",balance,2026-09-01,,,100\n'
            '../../etc/passwd,onetime,2026-09-20,Thing,bill,-5\n'
            'keep-me_01,onetime,2026-09-21,Other,bill,-5\n')
    rows, errors = core.parse_ledger_csv(text)
    assert errors == []
    assert [bool(re.fullmatch(r"[A-Za-z0-9_-]{1,40}", r.id)) for r in rows] == [True, True, True]
    assert rows[2].id == "keep-me_01"
    assert "HYPERLINK" not in core.to_csv_text(rows) and "passwd" not in core.to_csv_text(rows)


def test_names_cannot_start_a_spreadsheet_formula():
    for bad in ('=HYPERLINK("http://x")', "+1+1", "-2+3", "@SUM(A1)", "  =cmd"):
        assert core.clean_text(bad)[:1] not in ("=", "+", "-", "@")


def test_settings_from_env_never_reach_a_page_header_cookie_or_data_file(tmp_path, monkeypatch):
    """Every page is fetched with marker values for the settings in .env.
    None of them may appear in a response, a header, the session cookie, or
    anything written to the data folder."""
    import base64
    import os
    import re
    import zlib
    from app import create_app
    markers = {"APP_PASSWORD": "Pw-CANARY-7f3a9c1e55", "SECRET_KEY": "Sk-CANARY-91be07aa42",
               "ALLOWED_HOSTS": "canary-host.test,localhost", "HOST_IP": "10.99.88.77", "LEDGER_IMAGE": "ghcr.io/canary/img"}
    for key, value in markers.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app()
    c, host, seen = app.test_client(), {"Host": "localhost"}, []

    def grab(response):
        seen.append(response.get_data(as_text=True) + "\n".join(f"{k}: {v}" for k, v in response.headers))
        return response

    for path in ("/", "/login", "/healthz", "/nope", "/history"):
        grab(c.get(path, headers=host))
    assert grab(c.get("/", headers={"Host": "evil.example"})).status_code == 400
    token = re.search(r'name="_csrf" value="([^"]+)"', c.get("/login", headers=host).get_data(as_text=True)).group(1)
    grab(c.post("/login", data={"_csrf": token, "password": "wrong-guess"}, headers=host))
    assert grab(c.post("/login", data={"_csrf": token, "password": markers["APP_PASSWORD"]}, headers=host)).status_code == 302
    token = re.search(r'name="_csrf" value="([^"]+)"', c.get("/setup", headers=host).get_data(as_text=True)).group(1)
    grab(c.post("/setup", data={"_csrf": token, "balance": "1000", "date": "2026-11-16"}, headers=host, follow_redirects=True))
    assert (tmp_path / "ledger.csv").exists()
    pages = sorted({str(r) for r in app.url_map.iter_rules() if "GET" in r.methods and "<" not in str(r)})
    assert len(pages) >= 10
    for path in pages + ["/cards/x", "/pay/x", "/?h=bad&wi_amount=abc&wi_date=zz"]:
        grab(c.get(path, headers=host))
    cookie = c.get_cookie("session").value
    part = cookie.lstrip(".").split(".")[0]
    raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    seen.append(cookie + (zlib.decompress(raw) if cookie.startswith(".") else raw).decode("utf-8", "replace"))
    for folder, _, files in os.walk(tmp_path):
        seen.extend(open(os.path.join(folder, name), "rb").read().decode("utf-8", "replace") for name in files)
    everything = "\n".join(seen)
    for value in ("Pw-CANARY-7f3a9c1e55", "Sk-CANARY-91be07aa42", "canary-host.test", "10.99.88.77", "ghcr.io/canary/img"):
        assert value not in everything
