"""Hourly pay: base pay from a rate and usual hours, and paycheck estimates
learned from the paychecks entered."""
import re
from datetime import date
from decimal import Decimal

import pytest

import ledger_core as core
from app import create_app

TODAY = date(2026, 11, 16)
HEAD = "id,type,date,description,category,amount,frequency,status,card,close_day,due_day,estimate,pay,hours,rate,percent\n"
CSV = HEAD + """b1,balance,2026-10-01,Starting balance,,5000.00,,active,,,,,,,,
job,pay,2026-10-02,Paycheck,,,biweekly,active,,,,,,40,25.00,78
c1,onetime,2026-10-02,Paycheck,income,1602.11,,active,,,,,job,80,,
c2,onetime,2026-10-16,Paycheck,income,1811.40,,active,,,,,job,92.5,,
c3,onetime,2026-10-30,Paycheck,income,1489.02,,active,,,,,job,,,
"""


def rows(text=CSV):
    parsed, errors = core.parse_ledger_csv(text)
    assert errors == []
    return parsed


def job(parsed):
    return core.pays(parsed)[0]


# ------------------------------------------------------------------ the math

def test_base_pay_is_hours_times_rate_for_one_pay_period():
    make = lambda freq, hours="40", rate="25.00": core.Row("p", "pay", date(2026, 1, 2), "Job", frequency=freq,
                                                             hours=Decimal(hours), rate=Decimal(rate))
    assert core.base_pay(make("weekly")) == Decimal("1000.00")
    assert core.base_pay(make("biweekly")) == Decimal("2000.00")
    assert core.base_pay(make("monthly")) == Decimal("4333.33")          # 52 weeks / 12 months
    assert core.base_pay(make("biweekly", "37.5", "18.75")) == Decimal("1406.25")
    assert core.period_hours(make("monthly")) == Decimal("173.33")


def test_estimate_is_base_pay_times_the_share_kept_in_recent_paychecks():
    parsed = rows()
    est = core.pay_estimate(parsed, job(parsed))
    # Kept 1602.11 + 1811.40 + 1489.02 of 2000.00 + 2312.50 + 2000.00 earned.
    assert est == core.PayEstimate(Decimal("1553.28"), Decimal("2000.00"), Decimal("80.00"), Decimal("77.7"), 3)


def test_overtime_with_hours_entered_does_not_inflate_later_estimates():
    # A 100-hour paycheck. With hours entered the share kept stays the same, so the estimate stays at base.
    with_hours = rows(HEAD + "b,balance,2026-10-01,,,0,,,,,,,,,,\njob,pay,2026-10-02,Job,,,biweekly,active,,,,,,40,25.00,\n"
                             "c,onetime,2026-10-02,Job,income,2000.00,,active,,,,,job,100,,\n")
    without = rows(HEAD + "b,balance,2026-10-01,,,0,,,,,,,,,,\njob,pay,2026-10-02,Job,,,biweekly,active,,,,,,40,25.00,\n"
                          "c,onetime,2026-10-02,Job,income,2000.00,,active,,,,,job,,,\n")
    assert core.pay_estimate(with_hours, job(with_hours)).amount == Decimal("1600.00")      # 80 hours' worth
    assert core.pay_estimate(without, job(without)).amount == Decimal("2000.00")            # treated as a usual paycheck


def test_without_paychecks_the_starting_percent_is_used():
    parsed = [r for r in rows() if r.type != "onetime"]
    assert core.pay_estimate(parsed, job(parsed)).amount == Decimal("1560.00")              # 78% of 2000
    no_percent = [core.replace(r, percent=Decimal(0)) if r.type == "pay" else r for r in parsed]
    assert core.pay_estimate(no_percent, job(no_percent)).amount == Decimal("2000.00")


def test_only_the_last_six_entered_paychecks_count():
    lines = "".join(f"c{i},onetime,2026-{m:02d}-{d:02d},Job,income,{amt},,active,,,,,job,,,\n"
                    for i, (m, d, amt) in enumerate([(7, 10, "100.00"), (7, 24, "100.00"), (8, 7, "1500.00"), (8, 21, "1500.00"),
                                                     (9, 4, "1500.00"), (9, 18, "1500.00"), (10, 2, "1500.00"), (10, 16, "1500.00")]))
    parsed = rows(HEAD + "b,balance,2026-07-01,,,0,,,,,,,,,,\njob,pay,2026-07-10,Job,,,biweekly,active,,,,,,40,25.00,\n" + lines)
    est = core.pay_estimate(parsed, job(parsed))
    assert (est.amount, est.count) == (Decimal("1500.00"), 6)


def test_every_payday_since_the_balance_gets_one_paycheck_entered_or_estimated():
    parsed = rows()
    forecast = [r for r in core.forecast_rows(parsed, date(2026, 10, 1), date(2026, 12, 31)) if r.pay == "job"]
    assert [r.date.isoformat() for r in forecast] == ["2026-11-13", "2026-11-27", "2026-12-11", "2026-12-25"]
    assert all(r.amount == Decimal("1553.28") and r.estimated and r.category == "income" for r in forecast)
    assert core.open_paydays(parsed, job(parsed), TODAY) == [date(2026, 11, 13), date(2026, 11, 27)]
    assert [(p.pay.id, p.payday) for p in core.pending_paychecks(parsed, TODAY)] == [("job", date(2026, 11, 13))]


@pytest.mark.parametrize("offset", [-6, -2, 0, 3, 6])
def test_a_paycheck_dated_a_few_days_off_still_replaces_its_own_estimate(offset):
    day = date(2026, 11, 13).toordinal() + offset
    parsed = rows(CSV + f"late,onetime,{date.fromordinal(day).isoformat()},Paycheck,income,1500.00,,active,,,,,job,,,\n")
    paid = [r.date.isoformat() for r in core.forecast_rows(parsed, date(2026, 10, 1), date(2026, 12, 15)) if r.pay == "job"]
    assert paid == ["2026-11-27", "2026-12-11"]                # Nov 13 is covered; nothing else is suppressed


def test_weekly_and_monthly_pay_schedules():
    weekly = rows(HEAD + "b,balance,2026-11-01,,,0,,,,,,,,,,\nw,pay,2026-11-06,Shift,,,weekly,active,,,,,,20,15.00,\n")
    assert [r.date.day for r in core.forecast_rows(weekly, date(2026, 11, 1), date(2026, 11, 30))] == [6, 13, 20, 27]
    monthly = rows(HEAD + "b,balance,2026-11-01,,,0,,,,,,,,,,\nm,pay,2026-01-31,Salary,,,monthly,active,,,,,,40,30.00,\n")
    assert [r.date.isoformat() for r in core.forecast_rows(monthly, date(2027, 1, 1), date(2027, 3, 31))] == ["2027-01-31", "2027-02-28", "2027-03-31"]


def test_pay_rows_survive_the_file_and_bad_ones_are_reported():
    text = core.to_csv_text(rows())
    again, errors = core.parse_ledger_csv(text)
    assert errors == [] and core.to_csv_text(again) == text
    pay = job(again)
    assert (pay.hours, pay.rate, pay.percent, pay.frequency, pay.date) == (Decimal("40.00"), Decimal("25.00"), Decimal("78.00"), "biweekly", date(2026, 10, 2))
    assert [r.hours for r in again if r.id in ("c1", "c2", "c3")] == [Decimal("80.00"), Decimal("92.50"), Decimal("0")]
    bad = "type,date,amount,description,frequency,hours,rate,percent\nbalance,2026-10-01,1,,,,,\npay,2026-10-02,,Job,annually,40,25,\npay,2026-10-02,,Job,weekly,400,25,\npay,2026-10-02,,Job,weekly,40,0,\npay,2026-10-02,,Job,weekly,40,25,150\n"
    assert core.parse_ledger_csv(bad)[1] == [
        "Row 3: frequency 'annually' should be weekly, biweekly, or monthly.",
        "Row 4: hours '400' should be the hours in a usual week, like 40.",
        "Row 5: rate '0' should be an hourly rate, like 25.00.",
        "Row 6: percent '150' should be between 1 and 100."]


# ----------------------------------------------------------------- the pages

@pytest.fixture
def client(tmp_path):
    (tmp_path / "ledger.csv").write_text(CSV, encoding="utf-8")
    c = create_app(data_dir=str(tmp_path), password="", today=lambda: TODAY).test_client()
    c.token = re.search(r'name="_csrf" value="([^"]+)"', c.get("/pay/new").get_data(as_text=True)).group(1)
    c.ledger = core.Ledger(str(tmp_path / "ledger.csv"))
    return c


def text(response):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.get_data(as_text=True)))


def test_pages_show_the_estimated_paycheck(client):
    assert "Paycheck from Nov 13 isn't entered yet." in text(client.get("/")).replace("&#39;", "'")
    assert "40 hours a week at $25.00, every 2 weeks +$1,553.28 Nov 27, estimate" in text(client.get("/transactions"))
    page = text(client.get("/pay/job"))
    assert "the projection uses $1,553.28. Base pay is 80 hours at $25.00 = $2,000.00, and your last 3 paychecks kept 77.7% of what you earned." in page


def test_entering_a_paycheck_replaces_the_estimate_and_updates_the_next_one(client):
    r = client.post("/pay/job/paycheck", data={"_csrf": client.token, "payday": "2026-11-13", "amount": "1,655.20", "hours": "84"})
    assert r.status_code == 302
    saved = next(x for x in client.ledger.load() if x.pay == "job" and x.date == date(2026, 11, 13))
    assert (saved.amount, saved.hours, saved.category, saved.type) == (Decimal("1655.20"), Decimal("84.00"), "income", "onetime")
    assert "isn't entered yet" not in client.get("/").get_data(as_text=True).replace("&#39;", "'")
    assert "your last 4 paychecks" in text(client.get("/pay/job"))


def test_paycheck_entry_is_checked(client):
    for data, message in (({"payday": "2026-11-13", "amount": ""}, "Enter your take-home pay"),
                          ({"payday": "2026-11-13", "amount": "-20"}, "Enter your take-home pay"),
                          ({"payday": "2026-10-16", "amount": "50"}, "Enter your take-home pay"),      # already entered
                          ({"payday": "2031-01-03", "amount": "50"}, "Enter your take-home pay"),      # not an open payday
                          ({"payday": "2026-11-13", "amount": "50", "hours": "abc"}, "Enter the hours you worked")):
        page = client.post("/pay/job/paycheck", data={"_csrf": client.token, **data}).get_data(as_text=True)
        assert message in page, data
    assert len([x for x in client.ledger.load() if x.pay == "job"]) == 3


def test_adding_editing_pausing_and_deleting_pay(client):
    bad = client.post("/pay/new", data={"_csrf": client.token, "name": "", "rate": "0", "hours": "400", "frequency": "annually",
                                        "payday": "", "percent": "150"})
    assert bad.get_data(as_text=True).count('class="field-error"') == 6
    client.post("/pay/new", data={"_csrf": client.token, "name": "Second job", "rate": "18.50", "hours": "12.5",
                                  "frequency": "weekly", "payday": "2026-11-20", "percent": "85"})
    second = next(p for p in core.pays(client.ledger.load()) if p.description == "Second job")
    assert (second.rate, second.hours, second.frequency, second.percent) == (Decimal("18.50"), Decimal("12.50"), "weekly", Decimal("85.00"))
    assert core.pay_estimate(client.ledger.load(), second).amount == Decimal("196.56")       # 12.5 x 18.50 x 85%
    client.post(f"/pay/{second.id}/pause", data={"_csrf": client.token})
    assert not next(p for p in core.pays(client.ledger.load()) if p.id == second.id).active
    client.post("/pay/job/delete", data={"_csrf": client.token})
    after = client.ledger.load()
    assert [p.id for p in core.pays(after)] == [second.id]
    assert [(r.id, r.pay) for r in after if r.id in ("c1", "c2", "c3")] == [("c1", ""), ("c2", ""), ("c3", "")]   # kept, unlinked
    assert client.get("/pay/job").status_code == 404
    assert client.post(f"/pay/{second.id}/delete", data={}).status_code == 400              # needs the form token
