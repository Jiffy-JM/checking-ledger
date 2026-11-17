"""Credit cards: statement and due days, estimated payments, and what-ifs."""
import re
from datetime import date
from decimal import Decimal

import pytest

import ledger_core as core
from app import create_app

TODAY = date(2026, 11, 16)
CSV = """id,type,date,description,category,amount,frequency,status,card,close_day,due_day,estimate
b1,balance,2026-11-10,Starting balance,,5000.00,,active,,,,
p1,recurring,2026-10-02,Paycheck,income,2808.99,biweekly,active,,,,
visa,card,,Visa,,0,,active,,28,24,average
store,card,,Store card,,180.00,,active,,12,7,fixed
s1,onetime,2026-10-24,Visa payment,creditcard,-1349.92,,active,visa,,,
s2,onetime,2026-11-24,Visa payment,creditcard,-1461.05,,active,visa,,,
"""


def rows():
    parsed, errors = core.parse_ledger_csv(CSV)
    assert errors == []
    return parsed


def card(parsed, card_id):
    return next(c for c in core.cards(parsed) if c.id == card_id)


# ------------------------------------------------------------------ the math

def test_cards_survive_a_round_trip_through_the_file():
    text = core.to_csv_text(rows())
    again, errors = core.parse_ledger_csv(text)
    assert errors == [] and core.to_csv_text(again) == text
    visa = card(again, "visa")
    assert (visa.description, visa.close_day, visa.due_day, visa.estimate) == ("Visa", 28, 24, "average")
    assert [r.card for r in again if r.id in ("s1", "s2")] == ["visa", "visa"]


def test_files_from_before_cards_still_load():
    old = "id,type,date,description,category,amount,frequency,status\nb1,balance,2026-10-01,,,100,,\nx,onetime,2026-10-05,X,bill,-5,,active\n"
    parsed, errors = core.parse_ledger_csv(old)
    assert errors == [] and len(parsed) == 2 and core.cards(parsed) == []


def test_bad_card_rows_are_reported_by_row():
    bad = "type,date,amount,description,close_day,due_day,estimate\nbalance,2026-10-01,1,,,,\ncard,,,,40,x,weird\ncard,,,Amex,3,,\n"
    _, errors = core.parse_ledger_csv(bad)
    assert errors == ["Row 3: the card's name (description) is empty.",
                      "Row 4: due_day '' should be a day of the month from 1 to 31."]


def test_due_and_closing_dates_move_to_the_end_of_short_months():
    month_end = core.Row("c", "card", core.CARD_DATE, "Card", close_day=31, due_day=30)
    assert core.due_dates(month_end, date(2027, 1, 31), date(2027, 4, 30)) == [date(2027, 2, 28), date(2027, 3, 30), date(2027, 4, 30)]
    assert core.close_before(month_end, date(2027, 3, 30)) == date(2027, 2, 28)
    assert core.close_before(card(rows(), "visa"), date(2026, 12, 24)) == date(2026, 11, 28)


def test_estimate_is_the_average_of_recent_statements_or_the_set_amount():
    parsed = rows()
    assert core.card_estimate(parsed, card(parsed, "visa")) == core.Estimate(Decimal("1405.49"), "average", 2)
    assert core.card_estimate(parsed, card(parsed, "store")) == core.Estimate(Decimal("180.00"), "fixed")
    no_history = [r for r in parsed if r.card != "visa"]
    assert core.card_estimate(no_history, card(no_history, "visa")) is None      # nothing to go on yet


def test_forecast_fills_only_the_months_without_a_statement():
    parsed = rows()
    forecast = core.forecast_rows(parsed, TODAY, date(2027, 1, 31))
    assert sorted((r.date.isoformat(), r.description, str(r.amount)) for r in forecast) == [
        ("2026-12-07", "Store card payment", "-180.00"), ("2026-12-24", "Visa payment", "-1405.49"),
        ("2027-01-07", "Store card payment", "-180.00"), ("2027-01-24", "Visa payment", "-1405.49")]
    assert all(r.estimated for r in forecast)
    assert "est-" not in core.to_csv_text(parsed)                                  # estimates are never saved


def test_paused_cards_forecast_nothing_and_pending_lists_closed_statements():
    parsed = rows()
    assert [(p.card.id, p.due, p.close) for p in core.pending_statements(parsed, TODAY)] == [("store", date(2026, 12, 7), date(2026, 11, 12))]
    paused = [core.replace(r, status="paused") if r.type == "card" else r for r in parsed]
    assert core.forecast_rows(paused, TODAY, date(2027, 3, 1)) == [] and core.pending_statements(paused, TODAY) == []


def test_estimates_lower_the_projection_but_not_history():
    parsed = rows()
    planned = parsed + core.forecast_rows(parsed, TODAY, core.add_months(TODAY, 13))
    span = ("months", 12)
    assert core.project(planned, TODAY, span).end_balance < core.project(parsed, TODAY, span).end_balance
    assert core.start_of_day(planned, TODAY) == core.start_of_day(parsed, TODAY)


# ----------------------------------------------------------------- the pages

@pytest.fixture
def client(tmp_path):
    (tmp_path / "ledger.csv").write_text(CSV, encoding="utf-8")
    c = create_app(data_dir=str(tmp_path), password="", today=lambda: TODAY).test_client()
    c.token = re.search(r'name="_csrf" value="([^"]+)"', c.get("/cards/new").get_data(as_text=True)).group(1)
    c.ledger = core.Ledger(str(tmp_path / "ledger.csv"))
    return c


def text(response):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.get_data(as_text=True)))


def test_overview_shows_estimates_and_the_statement_reminder(client):
    page = client.get("/").get_data(as_text=True)
    assert "Store card statement closed Nov 12." in page
    assert '<span class="tag">estimate</span>' in page


def test_transactions_lists_each_card_with_its_next_payment(client):
    page = text(client.get("/transactions"))
    assert "Closes the 28th, due the 24th" in page and "Nov 24, entered" in page
    assert "Closes the 12th, due the 7th" in page and "Dec 7, estimate" in page


def test_entering_a_statement_replaces_the_estimate(client):
    r = client.post("/cards/store/statement", data={"_csrf": client.token, "due": "2026-12-07", "amount": "212.40"})
    assert r.status_code == 302
    saved = [x for x in client.ledger.load() if x.card == "store"]
    assert [(x.date, x.amount, x.category) for x in saved] == [(date(2026, 12, 7), Decimal("-212.40"), "creditcard")]
    assert "Dec 7, entered" in text(client.get("/transactions"))
    assert "Store card statement closed" not in client.get("/").get_data(as_text=True)


def test_statement_needs_an_amount_and_an_open_due_date(client):
    for data in ({"due": "2026-12-07", "amount": ""}, {"due": "2026-12-07", "amount": "-5"},
                 {"due": "2031-01-07", "amount": "50"}, {"due": "nonsense", "amount": "50"}):
        r = client.post("/cards/store/statement", data={"_csrf": client.token, **data})
        assert "Enter the statement balance" in r.get_data(as_text=True), data
    assert [x for x in client.ledger.load() if x.card == "store"] == []


def test_adding_editing_pausing_and_deleting_a_card(client):
    bad = client.post("/cards/new", data={"_csrf": client.token, "name": "", "close_day": "40", "due_day": "",
                                          "estimate": "fixed", "fixed": ""})
    assert bad.get_data(as_text=True).count('class="field-error"') == 4
    client.post("/cards/new", data={"_csrf": client.token, "name": "=Travel", "close_day": "31", "due_day": "15",
                                    "estimate": "fixed", "fixed": "600"})
    travel = next(c for c in core.cards(client.ledger.load()) if c.description == "Travel")     # formula character stripped
    assert (travel.close_day, travel.due_day, travel.estimate, travel.amount) == (31, 15, "fixed", Decimal("600.00"))
    client.post(f"/cards/{travel.id}", data={"_csrf": client.token, "name": "Travel card", "close_day": "5",
                                             "due_day": "1", "estimate": "average", "fixed": ""})
    client.post(f"/cards/{travel.id}/pause", data={"_csrf": client.token})
    edited = next(c for c in core.cards(client.ledger.load()) if c.id == travel.id)
    assert (edited.description, edited.close_day, edited.status) == ("Travel card", 5, "paused")
    client.post("/cards/visa/delete", data={"_csrf": client.token})
    after = client.ledger.load()
    assert "visa" not in [c.id for c in core.cards(after)]
    assert [(r.id, r.card) for r in after if r.id in ("s1", "s2")] == [("s1", ""), ("s2", "")]   # statements kept, unlinked
    assert client.get("/cards/visa").status_code == 404


def test_card_changes_need_the_form_token(client):
    assert client.post("/cards/store/delete", data={}).status_code == 400
    assert client.post("/cards/store/statement", data={"due": "2026-12-07", "amount": "5"}).status_code == 400


def test_what_if_changes_the_chart_but_saves_nothing(client):
    before = client.ledger.load()
    response = client.get("/?wi_amount=9000&wi_date=2026-12-20&wi_dir=out")
    page = text(response)
    assert "Trying −$9,000.00 on Dec 20, 2026." in page and "Nothing has been saved." in page
    assert 'stroke-dasharray="5 5"' in response.get_data(as_text=True)
    assert client.ledger.load() == before
    assert "Trying" not in text(client.get("/"))


def test_what_if_rejects_bad_input(client):
    assert "Enter an amount greater than zero" in text(client.get("/?wi_amount=abc&wi_date=2026-12-20"))
    assert "Pick a date." in text(client.get("/?wi_amount=50&wi_date="))
    assert "Pick today or a later date." in text(client.get("/?wi_amount=50&wi_date=2026-01-01"))
    assert "<script>" not in client.get("/?wi_amount=<script>alert(1)</script>&wi_date=x").get_data(as_text=True)


def test_keep_it_opens_the_form_filled_in(client):
    page = client.get("/?wi_amount=9000&wi_date=2026-12-20&wi_dir=out").get_data(as_text=True)
    link = re.search(r'href="(/transactions/new\?[^"]+)"[^>]*>Keep it', page).group(1)
    form = client.get(link.replace("&amp;", "&")).get_data(as_text=True)
    assert 'name="amount" value="9000.00"' in form and 'name="date" value="2026-12-20"' in form


def test_help_page_explains_each_feature(client):
    page = client.get("/help").get_data(as_text=True)
    for anchor in ("help-start", "help-balances", "help-transactions", "help-cards", "help-what-if", "help-history",
                   "help-net-worth", "help-files", "help-backup", "help-updating", "help-themes", "help-privacy"):
        assert f'id="{anchor}"' in page and f'href="#{anchor}"' in page
    assert 'href="/help#help-cards"' in client.get("/transactions").get_data(as_text=True)
