import html as htmllib
import io
import re
from datetime import date

import pytest

from app import create_app
import ledger_core as core

TODAY = date(2026, 9, 20)


@pytest.fixture
def make(tmp_path):
    def _make(password=""):
        app = create_app(data_dir=str(tmp_path), password=password, today=lambda: TODAY)
        app.config["TESTING"] = True
        return app, app.test_client(), core.Ledger(str(tmp_path / "ledger.csv"))
    return _make


def token(client, path="/setup"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def setup_ledger(client):
    t = token(client)
    return client.post("/setup", data={"_csrf": t, "balance": "3,200.00", "date": "2026-09-20",
                                       "pay": "2808.99", "pay_date": "2026-09-25"})


def test_fresh_install_goes_to_setup(make):
    _, c, _ = make()
    assert c.get("/").headers["Location"].endswith("/setup")


def test_post_without_csrf_is_rejected(make):
    _, c, ledger = make()
    r = c.post("/setup", data={"balance": "1", "date": "2026-09-20"})
    assert r.status_code == 400 and not ledger.exists()


def test_setup_then_overview(make):
    _, c, ledger = make()
    assert setup_ledger(c).status_code == 302
    rows = ledger.load()
    assert {r.type for r in rows} == {"balance", "recurring"}
    page = c.get("/")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "data-chart" in html and "Next 12 months" in html and "Paycheck" in html
    assert "default-src 'self'" in page.headers["Content-Security-Policy"]


def test_setup_validation(make):
    _, c, ledger = make()
    t = token(c)
    r = c.post("/setup", data={"_csrf": t, "balance": "abc", "date": "2027-01-01"})
    html = htmllib.unescape(r.get_data(as_text=True))
    assert r.status_code == 200 and "Enter your current balance" in html and "can't be in the future" in html
    assert not ledger.exists()


def test_add_edit_pause_delete(make):
    _, c, ledger = make()
    setup_ledger(c)
    t = token(c, "/transactions/new?type=recurring")
    r = c.post("/transactions/new?type=recurring", data={
        "_csrf": t, "description": "Rent", "direction": "out", "amount": "1,450",
        "category": "bill", "date": "2026-10-01", "frequency": "monthly"})
    assert r.status_code == 302
    rent = next(x for x in ledger.load() if x.description == "Rent")
    assert rent.amount == core.q(-1450) and rent.frequency == "monthly"

    c.post(f"/transactions/{rent.id}", data={
        "_csrf": t, "description": "Rent", "direction": "out", "amount": "1500",
        "category": "bill", "date": "2026-10-01", "frequency": "monthly"})
    assert next(x for x in ledger.load() if x.id == rent.id).amount == core.q(-1500)

    c.post(f"/transactions/{rent.id}/pause", data={"_csrf": t})
    assert next(x for x in ledger.load() if x.id == rent.id).status == "paused"
    c.post(f"/transactions/{rent.id}/pause", data={"_csrf": t})
    assert next(x for x in ledger.load() if x.id == rent.id).status == "active"

    c.post(f"/transactions/{rent.id}/delete", data={"_csrf": t})
    assert all(x.id != rent.id for x in ledger.load())
    assert c.get(f"/transactions/{rent.id}").status_code == 404


def test_invalid_transaction_shows_errors(make):
    _, c, ledger = make()
    setup_ledger(c)
    before = len(ledger.load())
    t = token(c, "/transactions/new")
    r = c.post("/transactions/new", data={"_csrf": t, "description": "", "direction": "out",
                                          "amount": "-5", "category": "bill", "date": ""})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Add a short name" in html and "greater than zero" in html
    assert len(ledger.load()) == before


def test_balance_rows_cannot_be_edited_as_transactions(make):
    _, c, ledger = make()
    setup_ledger(c)
    balance = core.anchor(ledger.load())
    assert c.get(f"/transactions/{balance.id}").status_code == 404


def test_balance_update_and_undo(make, tmp_path):
    _, c, ledger = make()
    t = token(c)
    c.post("/setup", data={"_csrf": t, "balance": "1000", "date": "2026-09-01"})
    t = token(c, "/transactions/new")
    c.post("/transactions/new", data={"_csrf": t, "description": "Visa", "direction": "out",
                                      "amount": "100", "category": "creditcard", "date": "2026-09-10"})
    r = c.post("/balance", data={"_csrf": t, "date": "2026-09-20", "balance": ""})
    assert r.status_code == 302
    assert core.anchor(ledger.load()).amount == core.q(900)
    hist = c.get("/history").get_data(as_text=True)
    assert "Visa" in hist and "$900.00" in hist

    # same day again is refused with a message, nothing written
    r = c.post("/balance", data={"_csrf": t, "date": "2026-09-20", "balance": "5"}, follow_redirects=True)
    assert "Pick a date after your last balance update" in r.get_data(as_text=True)
    assert len(core.balances(ledger.load())) == 2

    c.post("/balance/undo", data={"_csrf": t})
    assert core.anchor(ledger.load()).amount == core.q(1000)


def test_download_csv(make):
    _, c, _ = make()
    setup_ledger(c)
    r = c.get("/download")
    body = r.get_data(as_text=True)
    assert r.mimetype == "text/csv"
    assert "attachment" in r.headers["Content-Disposition"]
    assert body.startswith("\ufeffid,type,date,description,category,amount,frequency,status")
    assert "Paycheck" in body and "2808.99" in body


def test_all_five_views_and_choice_is_remembered(make):
    _, c, _ = make()
    setup_ledger(c)
    for key, end in (("2w", "Oct 4, 2026"), ("1m", "Oct 20, 2026"), ("3m", "Dec 20, 2026"),
                     ("6m", "Mar 20, 2027"), ("1y", "Sep 20, 2027")):
        assert f"Balance on {end}" in c.get(f"/?h={key}").get_data(as_text=True), key
    c.get("/?h=2w")
    assert "Balance on Oct 4, 2026" in c.get("/").get_data(as_text=True)
    assert "Balance on Sep 20, 2027" in c.get("/?h=nonsense").get_data(as_text=True)


def test_same_day_card_payment_counts_everywhere(make):
    _, c, ledger = make()
    t = token(c)
    c.post("/setup", data={"_csrf": t, "balance": "3200", "date": "2026-09-20"})
    t = token(c, "/transactions/new")
    c.post("/transactions/new", data={"_csrf": t, "description": "Visa payment", "direction": "out",
                                      "amount": "412.37", "category": "creditcard", "date": "2026-09-20"})
    overview = c.get("/?h=2w").get_data(as_text=True)
    assert "Visa payment" in overview and "$2,787.63" in overview
    assert "Visa payment" in c.get("/transactions").get_data(as_text=True)
    assert "$412.37" in c.get("/history").get_data(as_text=True)


def test_upload_replaces_ledger_and_keeps_a_backup(make, tmp_path):
    _, c, ledger = make()
    setup_ledger(c)
    t = token(c, "/history")
    csv_text = ("type,date,description,category,amount,frequency,status\n"
                "balance,9/1/2026,Start,,\"$5,000.00\",,\n"
                "onetime,9/25/2026,New laptop,bill,(1200),,\n")
    r = c.post("/upload", data={"_csrf": t, "file": (io.BytesIO(csv_text.encode()), "ledger.csv")},
               content_type="multipart/form-data")
    assert r.status_code == 302
    rows = ledger.load()
    assert len(rows) == 2 and core.anchor(rows).amount == core.q(5000)
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1 and "Paycheck" in backups[0].read_text()


def test_bad_upload_changes_nothing_and_lists_problems(make):
    _, c, ledger = make()
    setup_ledger(c)
    before = open(ledger.path).read()
    t = token(c, "/history")
    bad = "type,date,description,amount\nbalance,2026-09-01,Start,100\nonetime,soon,Visa,-5\n"
    r = c.post("/upload", data={"_csrf": t, "file": (io.BytesIO(bad.encode()), "ledger.csv")},
               content_type="multipart/form-data")
    html = htmllib.unescape(r.get_data(as_text=True))
    assert r.status_code == 400 and "Nothing was changed" in html and "Row 3:" in html
    r = c.post("/upload", data={"_csrf": t, "file": (io.BytesIO(b"x"), "ledger.xlsx")},
               content_type="multipart/form-data")
    assert r.status_code == 400 and "isn't a .csv" in htmllib.unescape(r.get_data(as_text=True))
    assert open(ledger.path).read() == before


def test_net_worth_flow(make, tmp_path):
    _, c, _ = make()
    setup_ledger(c)
    t = token(c, "/networth")
    assert "Track your net worth" in c.get("/networth").get_data(as_text=True)
    for name, kind in (("Savings", "asset"), ("Roth IRA", "asset"), ("Visa", "debt")):
        assert c.post("/networth/accounts", data={"_csrf": t, "name": name, "kind": kind}).status_code == 302
    assert c.post("/networth/accounts", data={"_csrf": t, "name": "savings", "kind": "asset"}).status_code == 400
    c.post("/networth/record", data={"_csrf": t, "date": "2026-07-01",
                                     "account": ["Savings", "Roth IRA", "Visa"],
                                     "amount": ["10,000", "25000", "1500"]})
    c.post("/networth/record", data={"_csrf": t, "date": "2026-09-20",
                                     "account": ["Savings", "Roth IRA", "Visa"],
                                     "amount": ["12000", "", "500"]})
    html = htmllib.unescape(c.get("/networth").get_data(as_text=True))
    assert "$36,500.00" in html and "+$3,000.00 since Jul 1, 2026" in html and "data-chart" in html
    r = c.post("/networth/record", data={"_csrf": t, "date": "2027-01-01", "account": ["Savings"], "amount": ["1"]},
               follow_redirects=True)
    assert "future" in r.get_data(as_text=True)

    c.post("/networth/accounts/Roth IRA", data={"_csrf": t, "name": "Roth", "kind": "asset", "status": "active"})
    assert "Roth" in c.get("/networth/download").get_data(as_text=True)

    exported = c.get("/networth/download").get_data()
    c.post("/networth/dates/2026-09-20/delete", data={"_csrf": t})
    assert "$33,500.00" in c.get("/networth").get_data(as_text=True)
    r = c.post("/networth/upload", data={"_csrf": t, "file": (io.BytesIO(exported), "nw.csv")},
               content_type="multipart/form-data")
    assert r.status_code == 302 and "$36,500.00" in c.get("/networth").get_data(as_text=True)
    assert any(p.name.startswith("networth-") for p in (tmp_path / "backups").iterdir())


def test_password_protection(make):
    _, c, _ = make(password="hunter2")
    assert "/login" in c.get("/").headers["Location"]
    assert "/login" in c.get("/download").headers["Location"]
    t = token(c, "/login")
    assert "isn't right" in htmllib.unescape(c.post("/login", data={"_csrf": t, "password": "nope"}).get_data(as_text=True))
    t = token(c, "/login")
    r = c.post("/login?next=//evil.example", data={"_csrf": t, "password": "hunter2"})
    assert r.headers["Location"] == "/"
    assert c.get("/").headers["Location"].endswith("/setup")   # in, and on to setup


def test_health_and_static(make):
    _, c, _ = make()
    assert c.get("/healthz").get_data(as_text=True) == "ok"
    for path in ("/static/app.css", "/static/app.js", "/static/fonts/public-sans.woff2",
                 "/static/icon-180.png", "/static/manifest.webmanifest"):
        assert c.get(path).status_code == 200, path
