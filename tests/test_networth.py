from datetime import date
from decimal import Decimal as D

import pytest

import networth as nw


def book_with_history():
    b = nw.Book()
    for name, kind in (("Savings", "asset"), ("401k", "asset"), ("Visa", "debt")):
        b = nw.add_account(b, name, kind)
    b = nw.record(b, date(2026, 1, 1), {"Savings": D("10000"), "401k": D("50000"), "Visa": D("1200")})
    b = nw.record(b, date(2026, 4, 1), {"Savings": D("12000")})        # others carry forward
    b = nw.record(b, date(2026, 7, 1), {"Visa": D("0"), "401k": D("55000")})
    return b


def test_series_carries_values_forward_and_subtracts_debts():
    s = nw.series(book_with_history())
    assert [(x.date, x.net) for x in s] == [
        (date(2026, 1, 1), D("58800.00")),
        (date(2026, 4, 1), D("60800.00")),
        (date(2026, 7, 1), D("67000.00")),
    ]
    assert s[0].assets == D("60000.00") and s[0].debts == D("1200.00")


def test_recording_the_same_date_again_overwrites():
    b = nw.record(book_with_history(), date(2026, 7, 1), {"401k": D("56000")})
    assert nw.series(b)[-1].net == D("68000.00")


def test_rename_moves_history_and_duplicates_are_refused():
    b = nw.edit_account(book_with_history(), "visa", "Chase Visa", "debt", "active")
    assert {v.account for v in b.values} == {"Savings", "401k", "Chase Visa"}
    with pytest.raises(ValueError):
        nw.add_account(b, "savings", "asset")
    with pytest.raises(ValueError):
        nw.edit_account(b, "Savings", "401K", "asset", "active")


def test_delete_account_and_date():
    b = nw.delete_account(book_with_history(), "Visa")
    assert nw.series(b)[0].net == D("60000.00")
    b = nw.delete_date(b, date(2026, 4, 1))
    assert len(nw.series(b)) == 2


def test_csv_round_trip_and_upload_rules():
    b = book_with_history()
    again, errors = nw.parse_networth_csv(nw.to_csv_text(b))
    assert errors == [] and nw.series(again) == nw.series(b)
    text = ("Type,Date,Account,Kind,Amount,Status\n"
            "account,,Savings,Asset,,\n"
            "value,1/15/2026,Savings,,\"$1,000.00\",\n"
            "value,2026-01-15,Brokerage,asset,500,\n"      # new account via kind
            "value,2026-01-15,Car loan,,9000,\n"           # unknown, no kind
            "account,,savings,asset,,\n")                  # duplicate
    book, errors = nw.parse_networth_csv(text)
    assert len(errors) == 2
    assert errors[0].startswith("Row 6:") and "twice" in errors[0]
    assert errors[1].startswith("Row 5:") and "Car loan" in errors[1]
