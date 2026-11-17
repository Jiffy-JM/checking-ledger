"""Runs the ledger for ten simulated years of everyday use (paychecks and
card statements entered, skipped, entered late, balances updated) and checks
after every step that nothing drifts, doubles up, or goes missing."""
import json
import pathlib
import random
import re
import shutil
import subprocess
import time
from datetime import date, timedelta
from decimal import Decimal

import pytest

import ledger_core as core
from app import create_app

ROOT = pathlib.Path(__file__).resolve().parent.parent
START = date(2026, 1, 1)


def starting_rows():
    row = core.Row
    return [
        row("bal0", "balance", START, "Starting balance", amount=Decimal("4000.00")),
        row("rent", "recurring", START, "Rent", "bill", Decimal("-1500.00"), "monthly"),
        row("job", "pay", date(2026, 1, 2), "Paycheck", frequency="biweekly", hours=Decimal("40"), rate=Decimal("30.00"), percent=Decimal("80")),
        row("side", "pay", date(2026, 1, 7), "Side job", frequency="weekly", hours=Decimal("10"), rate=Decimal("20.00")),
        row("salary", "pay", date(2026, 1, 31), "Stipend", frequency="monthly", hours=Decimal("5"), rate=Decimal("12.00")),
        row("visa", "card", core.CARD_DATE, "Visa", close_day=28, due_day=24, estimate="average"),
        row("amex", "card", core.CARD_DATE, "Amex", amount=Decimal("300.00"), close_day=31, due_day=30, estimate="average"),
        row("store", "card", core.CARD_DATE, "Store", amount=Decimal("90.00"), close_day=5, due_day=1, estimate="fixed"),
        row("late", "card", core.CARD_DATE, "End of month", amount=Decimal("120.00"), close_day=15, due_day=31, estimate="fixed"),
    ]


def with_estimates(rows, today, months=13):
    base = core.anchor(rows)
    return rows + core.forecast_rows(rows, base.date, core.add_months(max(today, base.date), months))


def check_everything(rows, today):
    base = core.anchor(rows)
    # Nothing that is only an estimate is ever stored, and ids stay unique.
    assert not any(r.estimated or r.what_if or r.id.startswith("est-") for r in rows)
    assert len({r.id for r in rows}) == len(rows)
    horizon = core.add_months(today, 13)
    forecast = core.forecast_rows(rows, base.date, horizon)
    for card in core.cards(rows):
        statements = core.card_statements(rows, card)
        covered = core.covered_dues(statements, card)
        assert len(covered) == len(statements), f"two {card.description} statements count for one due date"
        estimated = [r.date for r in forecast if r.card == card.id]
        dues = core.due_dates(card, base.date, horizon)
        if card.active and core.card_estimate(rows, card):
            # Every due date has exactly one payment: the one recorded, or an estimate.
            assert sorted(estimated + [d for d in dues if d in covered]) == dues, card.description
        else:
            assert estimated == []
    for pay in core.pays(rows):
        checks = core.paychecks(rows, pay)
        covered = core.covered_paydays(checks, pay)
        assert len(covered) == len(checks), f"two {pay.description} paychecks count for one payday"
        estimated = [r.date for r in forecast if r.pay == pay.id]
        days = core.paydays(pay, base.date, horizon)
        if pay.active:
            assert sorted(estimated + [d for d in days if d in covered]) == days, pay.description
        else:
            assert estimated == []
        assert core.pay_estimate(rows, pay).amount > 0
    # The projection adds up: the end balance is the start plus every event.
    planned = with_estimates(rows, today)
    proj = core.project(planned, today, ("months", 12))
    assert proj.end_balance == core.q(proj.origin_balance + core.total(proj.events))
    assert proj.points[-1].balance == proj.end_balance


def simulate(years, seed=11):
    rng, rows, today = random.Random(seed), starting_rows(), START
    recorded = {}                     # balance date -> (amount, gap from expected) as first seen
    money = lambda low, high: Decimal(rng.randint(low, high)) / 100
    for month in range(years * 12):
        today = core.add_months(START, month) + timedelta(days=rng.randint(0, 27))
        # Entries can land a few days off their date, but never before the latest
        # balance: a row dated before a balance is a deliberate edit of history.
        nudge = lambda day, choices: max(day + timedelta(days=rng.choice(choices)), core.anchor(rows).date)
        for pay in core.pays(rows):
            if not pay.active:
                continue
            for payday in core.open_paydays(rows, pay, today):
                if payday <= today and rng.random() < 0.8:
                    est = core.pay_estimate(rows, pay)
                    worked = est.hours * Decimal(rng.choice(["0.8", "1", "1", "1.15"]))
                    amount = core.q(est.base * worked / est.hours * money(70, 82) / Decimal("1.00") / 100 * 100)
                    shifted = nudge(payday, [0, 0, 0, -1, 1, 2])                           # deposits land a day or two off
                    rows.append(core.Row(core.new_id(), "onetime", shifted, pay.description, "income", amount, pay=pay.id,
                                         hours=core.q(worked) if rng.random() < 0.5 else Decimal(0)))
        for card in core.cards(rows):
            if not card.active:
                continue
            for due in core.open_due_dates(rows, card, today):
                if core.close_before(card, due) <= today and rng.random() < 0.7:
                    paid = nudge(due, [0, 0, 0, -3, -1, 2])                                 # paid early or late, across month ends
                    rows.append(core.Row(core.new_id(), "onetime", paid, f"{card.description} payment", "creditcard",
                                         -money(8000, 160000), card=card.id))
        check_everything(rows, today)

        if month % 3 == 2 and today > core.anchor(rows).date:          # a quarterly balance update
            expected = core.start_of_day(with_estimates(rows, today), today)
            actual = None if rng.random() < 0.5 else expected + money(-30000, 30000)
            rows, snap = core.take_snapshot(rows, today, today, actual)
            assert snap.amount == (expected if actual is None else core.q(actual))
            check_everything(rows, today)
        if month % 7 == 3:                                             # pause and resume a card and a pay
            target = rng.choice(["amex", "side"])
            rows = [core.replace(r, status="paused" if r.active else "active") if r.id == target else r for r in rows]
        if month % 5 == 4:                                             # save and reload the file
            again, errors = core.parse_ledger_csv(core.to_csv_text(rows))
            assert errors == [] and core.to_csv_text(again) == core.to_csv_text(rows)
            rows = again
        if month == 40:                                                # a raise
            rows = [core.replace(r, rate=Decimal("33.50")) if r.id == "job" else r for r in rows]

        # History never changes after the fact.
        for info in core.snapshot_history(rows):
            if info.variance is None:
                continue
            seen = recorded.setdefault(info.row.date, (info.row.amount, info.variance))
            assert seen == (info.row.amount, info.variance), f"the {info.row.date} balance update changed later"
    return rows, today, recorded


def test_ten_years_of_use_stays_consistent():
    rows, today, recorded = simulate(years=10)
    assert today.year == 2035 and len(recorded) == 40                 # forty quarterly updates
    assumed = [r for r in rows if r.estimate == core.ASSUMED]
    entered_cards = [r for r in rows if r.card and r.estimate != core.ASSUMED]
    assert assumed and entered_cards                                  # both paths were exercised
    # Skipped statements were saved as estimates when a balance closed the period, and never count toward averages.
    for card in core.cards(rows):
        recent = [r for r in core.card_statements(rows, card) if r.active and r.estimate != core.ASSUMED][-6:]
        est = core.card_estimate(rows, card)
        if card.estimate == "average" and recent:
            assert est.amount == core.q(sum((-r.amount for r in recent), Decimal(0)) / len(recent))
    # Leap day, month ends, and year ends were all crossed.
    late = next(c for c in core.cards(rows) if c.id == "late")
    assert date(2028, 2, 29) in core.due_dates(late, date(2028, 2, 1), date(2028, 2, 29))
    # Still quick with ten years of rows.
    started = time.perf_counter()
    planned = with_estimates(rows, today)
    core.project(planned, today, ("months", 12)); core.cash_flow(planned, today)
    core.pending_statements(rows, today); core.pending_paychecks(rows, today); core.snapshot_history(rows)
    assert time.perf_counter() - started < 3, "the Overview math got slow"
    assert len(rows) < 3500


def test_different_histories_all_stay_consistent():
    for seed in (1, 2, 3):
        simulate(years=3, seed=seed)


def test_the_app_keeps_working_as_the_months_go_by(tmp_path):
    clock = {"today": START}
    (tmp_path / "ledger.csv").write_text(core.to_csv_text(starting_rows()), encoding="utf-8")
    client = create_app(data_dir=str(tmp_path), password="", today=lambda: clock["today"]).test_client()
    ledger = core.Ledger(str(tmp_path / "ledger.csv"))
    token = re.search(r'name="_csrf" value="([^"]+)"', client.get("/pay/new").get_data(as_text=True)).group(1)
    rng = random.Random(5)
    for month in range(48):
        clock["today"] = today = core.add_months(START, month) + timedelta(days=rng.randint(0, 27))
        rows = ledger.load()
        for pay in core.pays(rows):
            arrived = [d for d in core.open_paydays(rows, pay, today) if d <= today]
            if arrived and rng.random() < 0.8:
                r = client.post(f"/pay/{pay.id}/paycheck", data={"_csrf": token, "payday": arrived[0].isoformat(),
                                                                 "amount": f"{rng.randint(15000, 190000) / 100:.2f}"})
                assert r.status_code == 302, (pay.id, today)
        for card in core.cards(rows):
            due = core.open_due_dates(rows, card, today)[:1]
            if due and rng.random() < 0.7:
                r = client.post(f"/cards/{card.id}/statement", data={"_csrf": token, "due": due[0].isoformat(),
                                                                     "amount": f"{rng.randint(8000, 160000) / 100:.2f}"})
                assert r.status_code == 302, (card.id, today)
        if month % 3 == 2:
            assert client.post("/balance", data={"_csrf": token, "date": today.isoformat(), "balance": ""}).status_code == 302
        for path in ("/", "/?h=2w", "/?wi_amount=500&wi_date=" + (today + timedelta(days=9)).isoformat(), "/transactions", "/history",
                     "/pay/job", "/pay/side", "/cards/visa", "/cards/late", "/download"):
            assert client.get(path).status_code == 200, (path, today)
        check_everything(ledger.load(), today)
    gaps = [info.variance for info in core.snapshot_history(ledger.load()) if info.variance is not None]
    assert len(gaps) == 16 and all(gap == 0 for gap in gaps)           # accepting the calculated balance always matches


@pytest.mark.skipif(shutil.which("node") is None, reason="Node isn't installed")
def test_preview_agrees_with_python_after_ten_years(tmp_path):
    """The browser preview's engine reads the ten-year ledger and must reach
    the same estimates, reminders, and projection as the Python code."""
    from test_preview import differences, python_side
    import networth as nw

    rows, today, _ = simulate(years=10)
    source = tmp_path / "ten-years.csv"
    source.write_text(core.to_csv_text(rows), encoding="utf-8")
    subprocess.run(["node", str(ROOT / "tests" / "preview_dump.js"), today.isoformat(), str(tmp_path), str(source)], check=True, timeout=120)
    assert (tmp_path / "ledger.csv").read_bytes() == source.read_bytes()       # the preview writes the file back unchanged
    parsed, errors = core.parse_ledger_csv((tmp_path / "ledger.csv").read_text(encoding="utf-8"))
    book, _ = nw.parse_networth_csv((tmp_path / "networth.csv").read_text(encoding="utf-8"))
    assert errors == []
    js = json.loads((tmp_path / "js.json").read_text(encoding="utf-8"))
    assert differences(js, python_side(today, parsed, book)) == []
