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
