import json
from datetime import date
from decimal import Decimal as D

import pytest

import ledger_core as core
from ledger_core import Row

M1, M3, W2 = ("months", 1), ("months", 3), ("days", 14)


def bal(day, amount):
    return Row(core.new_id(), "balance", date.fromisoformat(day), "Balance", "", D(str(amount)))


def rec(day, amount, freq="monthly", cat="bill", name="Rent", status="active"):
    return Row(core.new_id(), "recurring", date.fromisoformat(day), name, cat, D(str(amount)), freq, status)


def one(day, amount, cat="creditcard", name="Visa"):
    return Row(core.new_id(), "onetime", date.fromisoformat(day), name, cat, D(str(amount)))


# ---- date math

def test_add_months_clamps_without_drift():
    assert core.add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert core.add_months(date(2027, 1, 31), 2) == date(2027, 3, 31)
    assert core.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_biweekly_and_annual_occurrences():
    r = rec("2026-09-19", 100, "biweekly")
    assert core.occurrences(r, date(2026, 9, 19), date(2026, 10, 18)) == [
        date(2026, 9, 19), date(2026, 10, 3), date(2026, 10, 17)]
    old = rec("2024-01-05", 100, "biweekly")
    assert all((d - date(2024, 1, 5)).days % 14 == 0
               for d in core.occurrences(old, date(2026, 9, 1), date(2026, 12, 31)))
    yearly = rec("2025-11-01", -120, "annually")
    assert core.occurrences(yearly, date(2026, 9, 20), date(2027, 9, 20)) == [date(2026, 11, 1)]


# ---- YOUR BUG: transactions dated on the balance date

def test_same_day_transaction_shows_on_chart_and_in_card_spending():
    rows = [bal("2026-10-06", 3200), one("2026-10-06", -412.37, name="Visa payment")]
    proj = core.project(rows, date(2026, 10, 6), M1)
    assert proj.origin_balance == D("3200.00")             # start of day
    assert [e.description for e in proj.events][0] == "Visa payment"
    assert proj.points[1].date == date(2026, 10, 6) and proj.points[1].balance == D("2787.63")
    assert core.end_of_day(rows, date(2026, 10, 6)) == D("2787.63")
    (period,) = core.category_periods(rows, date(2026, 10, 6))
    assert period.spent == D("412.37") and period.count == 1 and period.days == 1
    upcoming, settled = core.split_onetime(rows)
    assert len(upcoming) == 1 and not settled


def test_todays_transactions_are_on_the_chart_when_balance_is_older():
    rows = [bal("2026-10-01", 1000), one("2026-10-06", -100)]
    proj = core.project(rows, date(2026, 10, 6), W2)
    assert proj.origin_balance == D("1000.00")
    assert proj.points[1].date == date(2026, 10, 6) and proj.points[1].balance == D("900.00")


# ---- earlier bugs stay fixed

def test_monthly_cash_flow_is_exact():                       # the $108.33 bug
    rows = [bal("2026-09-19", 1000), rec("2026-09-19", -100)]
    (key, label, yearly, monthly), = core.cash_flow(rows, date(2026, 9, 19))[0]
    assert yearly == D("-1200.00") and monthly == D("-100.00")
    rows = [bal("2026-09-19", 0), rec("2024-01-15", -50)]
    assert core.cash_flow(rows, date(2026, 9, 19))[0][0][2] == D("-600.00")


def test_rent_on_balance_update_day_counts_exactly_once():   # the double-count bug
    rows = [bal("2026-09-01", 2300), rec("2026-09-19", -300)]
    rows, snap = core.take_snapshot(rows, date(2026, 9, 19), date(2026, 9, 19))
    assert snap.amount == D("2300.00")                      # start of 9/19, rent not out yet
    proj = core.project(rows, date(2026, 9, 19), M1)
    assert [e.date for e in proj.events] == [date(2026, 9, 19), date(2026, 10, 19)]
    assert proj.end_balance == D("1700.00")


# ---- projection

def test_two_week_and_one_month_views():
    rows = [bal("2027-01-01", 1000), rec("2027-01-01", 500, "biweekly", "income", "Pay")]
    two = core.project(rows, date(2027, 1, 1), W2)
    assert two.end == date(2027, 1, 15) and two.end_balance == D("2000.00")   # 1/1, 1/15
    month = core.project(rows, date(2027, 1, 1), M1)
    assert month.end == date(2027, 2, 1) and month.end_balance == D("2500.00")   # 1/1, 1/15, 1/29


def test_projection_low_point_and_paused_rows():
    rows = [bal("2027-01-01", 100), one("2027-01-05", -300), one("2027-01-20", 1000, "income", "Bonus"),
            rec("2027-01-02", -50, status="paused")]
    proj = core.project(rows, date(2027, 1, 1), M3)
    assert proj.low.balance == D("-200.00") and proj.low.date == date(2027, 1, 5)
    assert proj.end_balance == D("800.00")


def test_cents_never_drift():
    rows = [bal("2027-01-01", "0.10")] + [one("2027-01-02", "0.10", "income", f"x{i}") for i in range(30)]
    assert core.end_of_day(rows, date(2027, 1, 2)) == D("3.10")


# ---- balance updates

def test_balance_update_validation_variance_and_undo():
    rows = [bal("2027-01-01", 1000), one("2027-01-10", -100)]
    with pytest.raises(ValueError):
        core.take_snapshot(rows, date(2027, 1, 1), date(2027, 2, 1))
    with pytest.raises(ValueError):
        core.take_snapshot(rows, date(2027, 2, 2), date(2027, 2, 1))
    rows, snap = core.take_snapshot(rows, date(2027, 2, 1), date(2027, 2, 1), D("850"))
    latest = core.snapshot_history(rows)[0]
    assert latest.expected == D("900.00") and latest.variance == D("-50.00")
    assert core.split_onetime(rows)[1][0].description == "Visa"
    rows = core.undo_snapshot(rows)
    assert core.anchor(rows).date == date(2027, 1, 1)
    with pytest.raises(ValueError):
        core.undo_snapshot(rows)


def test_credit_card_periods_by_quarter():
    rows = [
        bal("2026-01-01", 0), bal("2026-04-01", 0), bal("2026-07-01", 0),
        one("2026-01-01", -10),                                     # on the balance date: counts
        one("2026-02-10", -200), one("2026-03-31", -100), one("2026-04-01", -300),
        one("2026-08-05", -150), one("2026-09-20", -90), one("2026-10-01", -75),
        rec("2026-01-20", -25, cat="creditcard", name="Card autopay"),
        one("2026-02-11", -999, cat="bill", name="Not a card"),
    ]
    open_, q2, q1 = core.category_periods(rows, date(2026, 9, 20))
    assert (q1.start, q1.end, q1.days) == (date(2026, 1, 1), date(2026, 3, 31), 90)
    assert q1.spent == D("385.00")       # 10 + 200 + 100 + 3 x 25
    assert (q2.start, q2.end) == (date(2026, 4, 1), date(2026, 6, 30))
    assert q2.spent == D("375.00")       # 300 + 3 x 25
    assert open_.open and open_.end == date(2026, 9, 20) and open_.spent == D("315.00")
    assert core.average_monthly([open_, q2, q1]) == core.q(D("760") / 181 * core.DAYS_PER_MONTH)


# ---- CSV storage and uploads

def test_csv_round_trip_and_bad_rows_skipped_on_load(tmp_path):
    ledger = core.Ledger(str(tmp_path / "ledger.csv"))
    rows = [bal("2027-01-01", "1234.56"), rec("2027-01-03", "-99.99", "weekly"), one("2027-02-01", -5)]
    ledger.save(rows)
    assert sorted(ledger.load(), key=lambda r: r.id) == sorted(rows, key=lambda r: r.id)
    with open(ledger.path, "a", encoding="utf-8") as fh:
        fh.write("bad,onetime,not-a-date,x,bill,1,,active\r\n")
    assert len(ledger.load()) == 3


def test_upload_accepts_excel_and_numbers_formats():
    text = ("Type,Date,Description,Category,Amount,Frequency,Status\r\n"
            "Balance,10/6/2026,Start,,\"$3,200.00\",,\r\n"
            "One-time,10/12/26,Visa payment,Credit card,(412.37),,\r\n"
            "recurring,2026-11-01,Rent,bill,-1450,Every 2 weeks,paused\r\n"
            ",,,,,,\r\n")
    rows, errors = core.parse_ledger_csv(text)
    assert errors == []
    by = {r.description: r for r in rows}
    assert by["Start"].amount == D("3200.00") and by["Start"].date == date(2026, 10, 6)
    assert by["Visa payment"].amount == D("-412.37") and by["Visa payment"].category == "creditcard"
    assert by["Visa payment"].date == date(2026, 10, 12)
    assert by["Rent"].frequency == "biweekly" and by["Rent"].status == "paused"
    assert all(r.id for r in rows)


def test_upload_reports_every_problem_with_its_row():
    text = ("type,date,description,category,amount,frequency\n"
            "balance,2026-10-06,Start,,100,\n"
            "onetime,someday,Visa,creditcard,-5,\n"
            "recurring,2026-10-06,Rent,bill,-5,fortnightly\n"
            "onetime,2026-10-06,Gym,hobbies,-5,\n")
    rows, errors = core.parse_ledger_csv(text)
    assert len(errors) == 3
    assert errors[0].startswith("Row 3:") and "someday" in errors[0]
    assert errors[1].startswith("Row 4:") and "fortnightly" in errors[1]
    assert errors[2].startswith("Row 5:") and "hobbies" in errors[2]
    assert core.parse_ledger_csv("type,date,amount\nonetime,2026-10-06,-5\n")[1] == [
        "Row 2: the description is empty."]
    assert "balance row" in core.parse_ledger_csv("type,date,description,amount\nonetime,2026-10-06,x,-5\n")[1][0]
    assert "column names" in core.parse_ledger_csv("when,what\n1,2\n")[1][0]


def test_replace_all_backs_up_first(tmp_path):
    ledger = core.Ledger(str(tmp_path / "ledger.csv"))
    ledger.save([bal("2027-01-01", 1)])
    original = open(ledger.path).read()
    saved = ledger.replace_all([bal("2027-02-01", 2)])
    assert saved.startswith("backups/ledger-")
    assert open(tmp_path / saved).read() == original
    assert core.anchor(ledger.load()).amount == D("2.00")


def test_failed_update_writes_nothing(tmp_path):
    ledger = core.Ledger(str(tmp_path / "ledger.csv"))
    ledger.save([bal("2027-01-01", 1)])
    before = open(ledger.path).read()

    def boom(rows):
        raise ValueError("nope")
    with pytest.raises(ValueError):
        ledger.update(boom)
    assert open(ledger.path).read() == before


def test_formula_characters_are_stripped():
    assert core.clean_text("=HYPERLINK(1)") == "HYPERLINK(1)"
    assert core.clean_text("  +@-Rent   payment ") == "Rent payment"


# ---- migration from the Rust/JS version

def test_migrates_state_json_shifting_to_start_of_day(tmp_path):
    state = {
        "settings": {"startingBalance": 2000, "startingDate": "2026-07-01",
                     "paycheckAmount": 2808.99, "nextPayDate": "2026-07-10"},
        "items": [{"name": "Rent", "amount": -300, "freq": "monthly", "date": "2026-01-19", "category": "bill"},
                  {"name": "Gym", "amount": -40, "freq": "monthly", "date": "2026-01-05", "category": "bill", "active": False}],
        "onetime": [{"name": "Visa", "amount": -150, "date": "2026-08-05", "category": "creditcard"}],
        "archive": [{"name": "Visa", "amount": -200, "date": "2026-02-10", "category": "creditcard"}],
        "snapshots": [{"asOfDate": "2026-04-01", "priorStartingDate": "2026-01-01", "priorBalance": 500, "newBalance": 1200},
                      {"asOfDate": "2026-07-01", "priorStartingDate": "2026-04-01", "priorBalance": 1200, "newBalance": 2000}],
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    ledger = core.Ledger(str(tmp_path / "ledger.csv"))
    assert core.migrate_if_needed(ledger, str(tmp_path / "state.json")) == 8
    rows = ledger.load()
    assert [(b.date.isoformat(), b.amount) for b in core.balances(rows)] == [
        ("2026-01-02", D("500.00")), ("2026-04-02", D("1200.00")), ("2026-07-02", D("2000.00"))]
    pay = next(r for r in rows if r.description == "Paycheck")
    assert pay.date <= date(2026, 1, 2) and (date(2026, 7, 10) - pay.date).days % 14 == 0
    assert core.migrate_if_needed(ledger, str(tmp_path / "state.json")) == 0
