"""Net worth tracking, stored in its own CSV (networth.csv).

Two kinds of rows:

* ``account`` -- set up once: a name, ``asset`` or ``debt``, and active/hidden.
* ``value``   -- what one account was worth on one date.

Debts are entered as the amount owed (a positive number) and subtracted.
An account keeps its last recorded value until you record a new one, so you
only need to update the accounts that changed.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from ledger_core import (ZERO, CsvFile, atomic_write, clean_text, lookup, parse_amount_text,
                         parse_date_text, q, read_csv_dicts)

log = logging.getLogger("ledger.networth")

FIELDS = ["type", "date", "account", "kind", "amount", "status"]
KINDS = {"asset": "Asset", "debt": "Debt"}
KIND_ALIASES = {"liability": "debt", "loan": "debt", "assets": "asset", "debts": "debt"}


@dataclass(frozen=True)
class Account:
    name: str
    kind: str
    status: str = "active"

    @property
    def active(self) -> bool:
        return self.status != "hidden"


@dataclass(frozen=True)
class Value:
    date: date
    account: str
    amount: Decimal


@dataclass
class Book:
    accounts: list = field(default_factory=list)
    values: list = field(default_factory=list)

    def find(self, name: str) -> Account | None:
        key = (name or "").strip().lower()
        return next((a for a in self.accounts if a.name.lower() == key), None)


def signed(account: Account, amount: Decimal) -> Decimal:
    return amount if account.kind == "asset" else -amount


# ------------------------------------------------------------------- CSV

def to_csv_text(book: Book) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for a in book.accounts:
        writer.writerow({"type": "account", "date": "", "account": a.name, "kind": a.kind,
                         "amount": "", "status": a.status})
    for v in sorted(book.values, key=lambda v: (v.date, v.account.lower())):
        writer.writerow({"type": "value", "date": v.date.isoformat(), "account": v.account,
                         "kind": "", "amount": str(q(v.amount)), "status": ""})
    return buf.getvalue()


def parse_networth_csv(text: str, strict: bool = True):
    """Returns (book, errors). In strict mode any error rejects the file."""
    book, errors, pending = Book(), [], []
    header = None
    for line_no, raw, header in read_csv_dicts(text):
        try:
            rtype = str(raw.get("type") or "").strip().lower()
            name = clean_text(raw.get("account"))
            if rtype == "account":
                if not name:
                    raise ValueError("the account name is empty")
                kind = lookup(raw.get("kind"), KINDS, KIND_ALIASES)
                if kind is None:
                    raise ValueError(f"kind '{raw.get('kind', '')}' should be asset or debt")
                if book.find(name):
                    raise ValueError(f"'{name}' is listed as an account twice")
                status = "hidden" if str(raw.get("status") or "").strip().lower() == "hidden" else "active"
                book.accounts.append(Account(name, kind, status))
            elif rtype == "value":
                if not name:
                    raise ValueError("the account name is empty")
                pending.append((line_no, name, parse_date_text(raw.get("date")),
                                parse_amount_text(raw.get("amount")), raw.get("kind")))
            else:
                raise ValueError(f"type '{raw.get('type', '')}' should be account or value")
        except ValueError as exc:
            errors.append(f"Row {line_no}: {exc}.")
    if header is None:
        return Book(), ["The file is empty."]
    missing = [c for c in ("type", "account") if c not in header]
    if missing:
        return Book(), [f"The first row needs these column names: {', '.join(missing)}."]

    latest = {}
    for line_no, name, day, amount, kind_text in pending:
        account = book.find(name)
        if account is None:
            kind = lookup(kind_text, KINDS, KIND_ALIASES)
            if kind is None:
                errors.append(f"Row {line_no}: '{name}' isn't set up as an account. Add an account row for it, or fill in its kind (asset or debt).")
                continue
            account = Account(name, kind)
            book.accounts.append(account)
        latest[(day, account.name)] = Value(day, account.name, amount)   # last one for a date wins
    book.values = list(latest.values())
    if not strict:
        errors = []
    return book, errors


class NetWorthStore(CsvFile):
    def load(self) -> Book:
        with self._lock:
            try:
                with open(self.path, newline="", encoding="utf-8-sig") as fh:
                    text = fh.read()
            except FileNotFoundError:
                return Book()
            book, _ = parse_networth_csv(text, strict=False)
            return book

    def save(self, book: Book) -> None:
        with self._lock:
            atomic_write(self.path, to_csv_text(book))

    def update(self, change) -> Book:
        with self._lock:
            book = change(self.load())
            self.save(book)
            return book

    def replace_all(self, book: Book) -> str | None:
        with self._lock:
            saved = self.backup()
            self.save(book)
            return saved


# ----------------------------------------------------------------- math

@dataclass(frozen=True)
class Snapshot:
    date: date
    assets: Decimal
    debts: Decimal

    @property
    def net(self) -> Decimal:
        return q(self.assets - self.debts)


def series(book: Book) -> list[Snapshot]:
    """Net worth on every date anything was recorded. Each account counts at
    its latest value on or before that date."""
    accounts = {a.name: a for a in book.accounts}
    by_date = {}
    for v in book.values:
        by_date.setdefault(v.date, []).append(v)
    current, out = {}, []
    for day in sorted(by_date):
        for v in by_date[day]:
            current[v.account] = v.amount
        assets = sum((amt for name, amt in current.items() if accounts.get(name, Account(name, "asset")).kind == "asset"), ZERO)
        debts = sum((amt for name, amt in current.items() if accounts.get(name, Account(name, "asset")).kind == "debt"), ZERO)
        out.append(Snapshot(day, q(assets), q(debts)))
    return out


def latest_values(book: Book) -> dict:
    """{account name: Value} with each account's most recent value."""
    out = {}
    for v in sorted(book.values, key=lambda v: v.date):
        out[v.account] = v
    return out


def record(book: Book, day: date, entries: dict) -> Book:
    """Set values for ``day``. ``entries`` maps account name -> Decimal."""
    keep = [v for v in book.values if not (v.date == day and v.account in entries)]
    added = [Value(day, name, q(amount)) for name, amount in entries.items()]
    return Book(list(book.accounts), keep + added)


def add_account(book: Book, name: str, kind: str) -> Book:
    name = clean_text(name)
    if not name:
        raise ValueError("Give the account a name, like Savings or Visa.")
    if kind not in KINDS:
        raise ValueError("Choose asset or debt.")
    if book.find(name):
        raise ValueError(f"You already have an account named {name}.")
    return Book(book.accounts + [Account(name, kind)], list(book.values))


def edit_account(book: Book, old_name: str, name: str, kind: str, status: str) -> Book:
    account = book.find(old_name)
    if account is None:
        raise KeyError(old_name)
    name = clean_text(name)
    if not name:
        raise ValueError("Give the account a name.")
    clash = book.find(name)
    if clash and clash is not account:
        raise ValueError(f"You already have an account named {name}.")
    if kind not in KINDS:
        raise ValueError("Choose asset or debt.")
    new = replace(account, name=name, kind=kind, status="hidden" if status == "hidden" else "active")
    accounts = [new if a is account else a for a in book.accounts]
    values = [replace(v, account=name) if v.account == account.name else v for v in book.values]
    return Book(accounts, values)


def delete_account(book: Book, name: str) -> Book:
    account = book.find(name)
    if account is None:
        raise KeyError(name)
    return Book([a for a in book.accounts if a is not account],
                [v for v in book.values if v.account != account.name])


def delete_date(book: Book, day: date) -> Book:
    return Book(list(book.accounts), [v for v in book.values if v.date != day])
