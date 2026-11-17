"""Core ledger logic: CSV storage and the projection engine.

No web framework imports here, so everything can be unit tested directly.

The whole ledger is one CSV file. Every row has a ``type``:

* ``balance``   -- the real account balance at the start of a date. The most
                   recent one is the starting point for every projection.
* ``recurring`` -- repeats weekly / biweekly / monthly / annually from ``date``.
* ``onetime``   -- happens once on ``date``.
* ``card``      -- a credit card: its name, the day its statement closes, and
                   the day payment is due. Future due dates get a payment in
                   every projection (see "credit cards" below).
* ``pay``       -- hourly pay: a rate, the hours in a usual week, and how often
                   it is paid. Future paydays get an estimated paycheck (see
                   "hourly pay" below).

Amounts are signed: negative is money out, positive is money in. Money is
handled as ``Decimal`` throughout so cents never drift.

Convention used everywhere: a balance row is the balance at the *start* of
its date, before anything dated that day. Transactions dated on a balance
date are counted on top of it, so they show on the chart and in spending.
"""
from __future__ import annotations

import calendar
import csv
import io
import itertools
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

log = logging.getLogger("ledger")

FIELDS = ["id", "type", "date", "description", "category", "amount", "frequency", "status",
          "card", "close_day", "due_day", "estimate", "pay", "hours", "rate", "percent"]
TYPES = ("balance", "recurring", "onetime", "card", "pay")
PAY_FREQUENCIES = ("weekly", "biweekly", "monthly")
# Weeks in one pay period, as a fraction (monthly is 52/12).
PAY_WEEKS = {"weekly": (1, 1), "biweekly": (2, 1), "monthly": (52, 12)}
PAY_SPAN = {"weekly": 7, "biweekly": 14, "monthly": 31}   # days in one pay period, at most
ASSUMED = "assumed"   # a one-time row that was an estimate when its balance period closed
ESTIMATES = {"average": "Recent statements", "fixed": "A set amount"}
CARD_DATE = date(2000, 1, 1)   # card rows have no date of their own; this keeps sorting simple
CATEGORIES = {
    "income": "Income",
    "bill": "Bill",
    "creditcard": "Credit card",
    "transfer": "Transfer",
    "investment": "Investment",
}
FREQUENCIES = {
    "weekly": "Weekly",
    "biweekly": "Every 2 weeks",
    "monthly": "Monthly",
    "annually": "Yearly",
}
TYPE_ALIASES = {"balance": "balance", "recurring": "recurring", "onetime": "onetime",
                "one-time": "onetime", "one time": "onetime", "card": "card", "credit card": "card",
                "pay": "pay", "hourly pay": "pay"}
FREQ_ALIASES = {"bi-weekly": "biweekly", "every two weeks": "biweekly", "annual": "annually",
                "yearly": "annually"}
CENT = Decimal("0.01")
ZERO = Decimal("0")
DAYS_PER_MONTH = Decimal("30.4375")  # 365.25 / 12
MAX_BACKUPS = 20


def q(value) -> Decimal:
    """Round to cents."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def clean_text(text) -> str:
    """Collapse whitespace, cap length, and drop leading characters that
    Excel/Numbers would treat as the start of a formula (=, +, -, @)."""
    text = " ".join(str(text or "").split())[:80]
    return text.lstrip("=+-@").strip()


clean_description = clean_text


# ------------------------------------------------------------ tolerant parsing
# Files edited in Excel or Numbers come back with dates like 10/6/2026 and
# amounts like $1,450.00 or (25.00). Accept those as well as our own format.

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y")


def parse_date_text(text) -> date:
    text = str(text or "").strip()
    if not text:
        raise ValueError("the date is empty")
    for fmt in _DATE_FORMATS:
        try:
            day = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if 1900 <= day.year <= 2200:
            return day
    raise ValueError(f"'{text}' isn't a date like 2026-10-06 or 10/6/2026")


def parse_amount_text(text) -> Decimal:
    raw = str(text or "").strip()
    cleaned = raw.replace("\u2212", "-").replace("$", "").replace(",", "").replace(" ", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    if not cleaned:
        raise ValueError("the amount is empty")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"'{raw}' isn't an amount like -120.50") from None
    if not value.is_finite() or abs(value) >= Decimal("1000000000"):
        raise ValueError(f"'{raw}' isn't an amount like -120.50")
    return q(-value if negative else value)


def lookup(text, mapping: dict, aliases: dict | None = None) -> str | None:
    """Match a key or its label, ignoring case: 'Credit card' -> 'creditcard'."""
    key = str(text or "").strip().lower()
    if key in mapping:
        return key
    for k, label in mapping.items():
        if key == label.lower():
            return k
    return (aliases or {}).get(key)


def decode_upload(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def read_csv_dicts(text: str):
    """Yield (line_number, dict) with lower-cased, trimmed header names.
    Blank lines are skipped."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return
    for line_no, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue
        yield line_no, dict(zip(header, values)), header


# --------------------------------------------------------------------------- rows

@dataclass(frozen=True)
class Row:
    id: str
    type: str
    date: date
    description: str = ""
    category: str = ""
    amount: Decimal = ZERO
    frequency: str = ""
    status: str = "active"
    card: str = ""          # one-time rows: the id of the card this statement belongs to
    close_day: int = 0      # card rows: day of the month the statement closes
    due_day: int = 0        # card rows: day of the month payment is due
    estimate: str = ""      # card rows: "average" or "fixed"; one-time rows: "assumed" or blank
    pay: str = ""           # one-time rows: the id of the hourly pay this paycheck belongs to
    hours: Decimal = ZERO   # pay rows: hours in a usual week; paycheck rows: hours worked, if entered
    rate: Decimal = ZERO    # pay rows: hourly rate
    percent: Decimal = ZERO  # pay rows: starting take-home percent, used until a paycheck is entered
    estimated: bool = False  # never saved: a forecast card payment
    what_if: bool = False    # never saved: a what-if being tried on Overview

    @property
    def active(self) -> bool:
        return self.status != "paused"

    def to_csv(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "date": "" if self.type == "card" else self.date.isoformat(),
            "description": self.description,
            "category": self.category,
            "amount": str(q(self.amount)),
            "frequency": self.frequency,
            "status": self.status,
            "card": self.card,
            "close_day": str(self.close_day) if self.close_day else "",
            "due_day": str(self.due_day) if self.due_day else "",
            "estimate": self.estimate,
            "pay": self.pay,
            "hours": plain(self.hours) if self.hours else "",
            "rate": str(q(self.rate)) if self.rate else "",
            "percent": plain(self.percent) if self.percent else "",
        }


def plain(value: Decimal) -> str:
    """12.50 -> '12.5', 40.00 -> '40'."""
    text = str(q(value))
    return text.rstrip("0").rstrip(".") if "." in text else text


def clean_id(text) -> str:
    text = str(text or "").strip()
    return text if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", text) else ""


def number_in(text, column: str, low, high, example: str) -> Decimal:
    """A plain number for the hours, rate, and percent columns."""
    try:
        value = parse_amount_text(text)
    except ValueError:
        value = None
    if value is None or not Decimal(low) < value <= Decimal(high):
        raise ValueError(f"{column} '{str(text or '').strip()}' should be {example}")
    return value


def row_from_dict(raw: dict, strict: bool = True) -> Row:
    """Build a Row from one CSV dict. Raises ValueError with a plain-English
    reason. With strict=False an unknown category falls back to Bill."""
    rtype = lookup(raw.get("type"), {t: t for t in TYPES}, TYPE_ALIASES)
    if rtype is None:
        raise ValueError(f"type '{raw.get('type', '')}' should be balance, recurring, onetime, or card")
    if rtype == "card":
        return card_from_dict(raw, strict)
    if rtype == "pay":
        return pay_from_dict(raw, strict)
    day = parse_date_text(raw.get("date"))
    amount = parse_amount_text(raw.get("amount"))
    freq = ""
    if rtype == "recurring":
        freq = lookup(raw.get("frequency"), FREQUENCIES, FREQ_ALIASES)
        if freq is None:
            raise ValueError(f"frequency '{raw.get('frequency', '')}' should be weekly, biweekly, monthly, or annually")
    category = ""
    if rtype != "balance":
        category = lookup(raw.get("category"), CATEGORIES)
        if category is None:
            if strict and str(raw.get("category") or "").strip():
                raise ValueError(f"category '{raw.get('category')}' should be one of: {', '.join(CATEGORIES)}")
            category = "bill"
    status = "paused" if str(raw.get("status") or "").strip().lower() == "paused" else "active"
    # Ids end up in page addresses and back in the CSV, so only plain ones
    # are kept. Anything else (a formula, a path) gets a fresh id.
    rid = str(raw.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", rid):
        rid = new_id()
    description = clean_text(raw.get("description"))
    if rtype != "balance" and not description:
        if strict:
            raise ValueError("the description is empty")
        description = "Untitled"
    if rtype != "onetime":
        return Row(rid, rtype, day, description, category, amount, freq, status)
    hours = ZERO
    if str(raw.get("hours") or "").strip():
        try:
            hours = number_in(raw.get("hours"), "hours", 0, 744, "the hours worked, like 80")
        except ValueError:
            if strict:
                raise
    assumed = ASSUMED if str(raw.get("estimate") or "").strip().lower() == ASSUMED else ""
    return Row(rid, rtype, day, description, category, amount, freq, status,
               card=clean_id(raw.get("card")), pay=clean_id(raw.get("pay")), hours=hours, estimate=assumed)


def day_of_month(text, column: str) -> int:
    text = str(text or "").strip()
    if not re.fullmatch(r"\d{1,2}", text) or not 1 <= int(text) <= 31:
        raise ValueError(f"{column} '{text}' should be a day of the month from 1 to 31")
    return int(text)


def card_from_dict(raw: dict, strict: bool = True) -> Row:
    """A credit card row: description is the card's name, amount is the set
    amount to estimate with (0 for none)."""
    name = clean_text(raw.get("description"))
    if not name:
        if strict:
            raise ValueError("the card's name (description) is empty")
        name = "Card"
    close_day = day_of_month(raw.get("close_day"), "close_day")
    due_day = day_of_month(raw.get("due_day"), "due_day")
    estimate = lookup(raw.get("estimate"), ESTIMATES)
    if estimate is None:
        if strict and str(raw.get("estimate") or "").strip():
            raise ValueError(f"estimate '{raw.get('estimate')}' should be average or fixed")
        estimate = "average"
    amount = abs(parse_amount_text(raw.get("amount"))) if str(raw.get("amount") or "").strip() else ZERO
    status = "paused" if str(raw.get("status") or "").strip().lower() == "paused" else "active"
    rid = str(raw.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", rid):
        rid = new_id()
    return Row(rid, "card", CARD_DATE, name, "", amount, "", status,
               close_day=close_day, due_day=due_day, estimate=estimate)


def pay_from_dict(raw: dict, strict: bool = True) -> Row:
    """An hourly pay row: description is its name, date is any payday,
    frequency is how often it is paid."""
    name = clean_text(raw.get("description"))
    if not name:
        if strict:
            raise ValueError("the pay's name (description) is empty")
        name = "Paycheck"
    payday = parse_date_text(raw.get("date"))
    freq = lookup(raw.get("frequency"), FREQUENCIES, FREQ_ALIASES)
    if freq not in PAY_FREQUENCIES:
        raise ValueError(f"frequency '{raw.get('frequency', '')}' should be weekly, biweekly, or monthly")
    hours = number_in(raw.get("hours"), "hours", 0, 168, "the hours in a usual week, like 40")
    rate = number_in(raw.get("rate"), "rate", 0, 100000, "an hourly rate, like 25.00")
    percent = ZERO
    if str(raw.get("percent") or "").strip():
        percent = number_in(raw.get("percent"), "percent", 0, 100, "between 1 and 100")
    status = "paused" if str(raw.get("status") or "").strip().lower() == "paused" else "active"
    return Row(clean_id(raw.get("id")) or new_id(), "pay", payday, name, "", ZERO, freq, status,
               hours=hours, rate=rate, percent=percent)


def parse_row(raw: dict) -> Row | None:
    try:
        return row_from_dict(raw, strict=False)
    except (ValueError, TypeError, AttributeError):
        return None


def parse_ledger_csv(text: str):
    """Strict parse for uploads: returns (rows, errors). Any error means the
    upload should be rejected as a whole."""
    rows, errors, seen = [], [], set()
    header = None
    for line_no, raw, header in read_csv_dicts(text):
        try:
            row = row_from_dict(raw, strict=True)
        except ValueError as exc:
            errors.append(f"Row {line_no}: {exc}.")
            continue
        if row.id in seen:
            row = replace(row, id=new_id())
        seen.add(row.id)
        rows.append(row)
    if header is None:
        return [], ["The file is empty."]
    missing = [c for c in ("type", "date", "amount") if c not in header]
    if missing:
        return [], [f"The first row needs these column names: {', '.join(missing)}."]
    if not errors and not any(r.type == "balance" for r in rows):
        errors.append("The file needs at least one balance row so projections have a starting point.")
    return rows, errors


_TYPE_ORDER = {t: i for i, t in enumerate(TYPES)}


def to_csv_text(rows) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for r in sorted(rows, key=lambda r: (_TYPE_ORDER[r.type], r.date, r.description.lower(), r.id)):
        writer.writerow(r.to_csv())
    return buf.getvalue()


# ----------------------------------------------------------------------- storage

def atomic_write(path: str, text: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".csv")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class CsvFile:
    """One CSV on disk. Writes are atomic (temp file + rename) and serialized
    with a lock, so a crash mid-write can't leave a half-written file."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()

    def exists(self) -> bool:
        return os.path.exists(self.path)

    def backup(self) -> str | None:
        """Copy the current file into backups/ and keep the newest few."""
        with self._lock:
            if not self.exists():
                return None
            folder = os.path.join(os.path.dirname(os.path.abspath(self.path)), "backups")
            os.makedirs(folder, exist_ok=True)
            stem = os.path.splitext(os.path.basename(self.path))[0]
            name = f"{stem}-{datetime.now():%Y%m%d-%H%M%S-%f}.csv"
            shutil.copy2(self.path, os.path.join(folder, name))
            old = sorted(f for f in os.listdir(folder) if f.startswith(stem + "-") and f.endswith(".csv"))
            for extra in old[:-MAX_BACKUPS]:
                os.unlink(os.path.join(folder, extra))
            return f"backups/{name}"


class Ledger(CsvFile):
    def load(self) -> list[Row]:
        with self._lock:
            try:
                with open(self.path, newline="", encoding="utf-8-sig") as fh:
                    text = fh.read()
            except FileNotFoundError:
                return []
            rows, seen = [], set()
            for line_no, raw, _ in read_csv_dicts(text):
                row = parse_row(raw)
                if row is None:
                    log.warning("Skipping unreadable row %d in %s", line_no, self.path)
                    continue
                if row.id in seen:
                    row = replace(row, id=new_id())
                seen.add(row.id)
                rows.append(row)
            return rows

    def save(self, rows) -> None:
        with self._lock:
            atomic_write(self.path, to_csv_text(rows))

    def update(self, change):
        """Load, apply ``change(rows) -> rows``, save. If ``change`` raises,
        nothing is written."""
        with self._lock:
            rows = change(self.load())
            self.save(rows)
            return rows

    def replace_all(self, rows) -> str | None:
        """Swap in a whole new set of rows, backing up the current file."""
        with self._lock:
            saved = self.backup()
            self.save(rows)
            return saved


# --------------------------------------------------------------------- date math

def add_months(day: date, months: int) -> date:
    """Same day-of-month N months later, clamped to the month's last day."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def occurrences(row: Row, start: date, end: date) -> list[date]:
    """Dates a recurring row lands on within [start, end], inclusive.
    Monthly/yearly dates are always computed from the original date, so a
    row on the 31st lands on Feb 28 and then back on Mar 31 (no drift)."""
    if end < start:
        return []
    anchor = row.date
    if row.frequency in ("weekly", "biweekly"):
        step = 7 if row.frequency == "weekly" else 14
        first = anchor
        if anchor < start:
            first = anchor + timedelta(days=-(-(start - anchor).days // step) * step)
        out, day = [], first
        while day <= end:
            out.append(day)
            day += timedelta(days=step)
        return out

    stride = 12 if row.frequency == "annually" else 1
    n = 0
    if anchor < start:
        months_apart = (start.year - anchor.year) * 12 + (start.month - anchor.month)
        n = max(0, months_apart // stride - 1)
        while add_months(anchor, n * stride) < start:
            n += 1
    out = []
    while (day := add_months(anchor, n * stride)) <= end:
        out.append(day)
        n += 1
    return out


def next_occurrence(row: Row, from_day: date) -> date | None:
    """First date on or after ``from_day``."""
    hits = occurrences(row, from_day, add_months(from_day, 13))
    return hits[0] if hits else None


# ------------------------------------------------------------------------ events

@dataclass(frozen=True)
class Event:
    date: date
    description: str
    category: str
    amount: Decimal
    row_id: str
    recurring: bool
    estimated: bool = False
    what_if: bool = False


def events_in(rows, start: date, end: date) -> list[Event]:
    """Active transactions dated from ``start`` through ``end``, inclusive."""
    if end < start:
        return []
    out = []
    for r in rows:
        if not r.active:
            continue
        if r.type == "recurring":
            for day in occurrences(r, start, end):
                out.append(Event(day, r.description, r.category, r.amount, r.id, True))
        elif r.type == "onetime" and start <= r.date <= end:
            out.append(Event(r.date, r.description, r.category, r.amount, r.id, False, r.estimated, r.what_if))
    out.sort(key=lambda e: (e.date, e.amount < 0, e.description.lower()))
    return out


def total(events) -> Decimal:
    return q(sum((e.amount for e in events), ZERO))


# ------------------------------------------------------------------ credit cards
# A card has a statement closing day and a payment due day. Every due date
# from the latest balance onward gets a payment: the amount you entered for
# that statement if there is one, otherwise an estimate.
#
# Estimates are never written to the file while they are estimates. When you
# update your balance, the estimates dated before it are saved as ordinary
# one-time rows marked "assumed", so that history never changes afterwards.

def cards(rows) -> list[Row]:
    return [r for r in rows if r.type == "card"]


def _clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def due_dates(card: Row, start: date, end: date) -> list[date]:
    """The card's payment due dates within [start, end]."""
    out, year, month = [], start.year, start.month
    while (day := _clamp_day(year, month, card.due_day)) <= end:
        if day >= start:
            out.append(day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def close_before(card: Row, due: date) -> date:
    """The statement closing date that leads to this due date."""
    close = _clamp_day(due.year, due.month, card.close_day)
    if close >= due:
        prev = add_months(date(due.year, due.month, 1), -1)
        close = _clamp_day(prev.year, prev.month, card.close_day)
    return close


def card_statements(rows, card: Row) -> list[Row]:
    """The payments recorded for a card (entered or assumed), oldest first."""
    return sorted((r for r in rows if r.type == "onetime" and r.card == card.id and not r.estimated),
                  key=lambda r: r.date)


def _nearest(day: date, candidates) -> date | None:
    """The candidate date closest to ``day`` (the earlier one on a tie)."""
    return min(candidates, key=lambda d: (abs((d - day).days), d), default=None)


def covered_dues(statements, card: Row) -> dict:
    """{due date: the statement recorded for it}. Each statement counts for
    the due date nearest to it, so one paid a few days early or late, even
    across a month end, still replaces the right estimate and no other."""
    out = {}
    for r in statements:
        due = _nearest(r.date, due_dates(card, r.date - timedelta(days=31), r.date + timedelta(days=31)))
        if due is not None:
            out.setdefault(due, r)
    return out


def statement_for(rows, card: Row, due: date) -> Row | None:
    return covered_dues(card_statements(rows, card), card).get(due)


@dataclass(frozen=True)
class Estimate:
    amount: Decimal
    basis: str       # "average" or "fixed"
    count: int = 0   # statements averaged


def card_estimate(rows, card: Row) -> Estimate | None:
    """What to assume for a statement that hasn't been entered: the set
    amount, or the average of the last six statements you entered."""
    fixed = Estimate(q(card.amount), "fixed") if card.amount > 0 else None
    if card.estimate == "fixed":
        return fixed
    recent = [r for r in card_statements(rows, card) if r.active and r.estimate != ASSUMED][-6:]
    if not recent:
        return fixed
    return Estimate(q(sum((-r.amount for r in recent), ZERO) / len(recent)), "average", len(recent))


def card_forecast(rows, start: date, end: date) -> list[Row]:
    out = []
    for card in cards(rows):
        if not card.active:
            continue
        est = card_estimate(rows, card)
        if est is None:
            continue
        taken = covered_dues(card_statements(rows, card), card)
        for due in due_dates(card, start, end):
            if due not in taken:
                out.append(Row(f"est-{card.id}-{due.isoformat()}", "onetime", due, f"{card.description} payment",
                               "creditcard", -est.amount, card=card.id, estimated=True))
    return out


@dataclass(frozen=True)
class NextPayment:
    due: date
    close: date
    entered: Row | None
    estimate: Estimate | None


def next_payment(rows, card: Row, today: date) -> NextPayment:
    due = due_dates(card, today, add_months(today, 2))[0]
    return NextPayment(due, close_before(card, due), statement_for(rows, card, due), card_estimate(rows, card))


def _since(rows, today: date) -> date:
    """Estimates count from the latest balance onward."""
    base = anchor(rows)
    return min(base.date, today) if base else today


def open_due_dates(rows, card: Row, today: date, limit: int = 4) -> list[date]:
    """Due dates since the latest balance that have no statement entered,
    through the next three months."""
    taken = covered_dues(card_statements(rows, card), card)
    dues = due_dates(card, _since(rows, today), add_months(today, 3))
    return [d for d in dues if d not in taken][:limit]


@dataclass(frozen=True)
class PendingStatement:
    card: Row
    due: date
    close: date


def pending_statements(rows, today: date) -> list[PendingStatement]:
    """For each card, the earliest statement that has closed but whose
    amount isn't entered yet."""
    out = []
    for card in cards(rows):
        if not card.active:
            continue
        for due in open_due_dates(rows, card, today):
            close = close_before(card, due)
            if close <= today:
                out.append(PendingStatement(card, due, close))
            break
    return out


# -------------------------------------------------------------------- hourly pay
# For paychecks that vary. You give a rate, the hours in a usual week, and how
# often you are paid. That is the base: hours x rate for one pay period. Each
# paycheck you enter (take-home, and optionally the hours you worked) teaches
# the ledger what share of your pay you actually keep after taxes and
# deductions. Future paydays are estimated as base pay x that share.

def pays(rows) -> list[Row]:
    return [r for r in rows if r.type == "pay"]


def paydays(pay: Row, start: date, end: date) -> list[date]:
    return occurrences(pay, start, end)


def paychecks(rows, pay: Row) -> list[Row]:
    """The paychecks recorded for this pay (entered or assumed), oldest first."""
    return sorted((r for r in rows if r.type == "onetime" and r.pay == pay.id and not r.estimated),
                  key=lambda r: r.date)


def covered_paydays(checks, pay: Row) -> dict:
    """{payday: the paycheck recorded for it}. Each paycheck counts for the
    payday nearest to it, so one that lands a day or two off still replaces
    the right estimate and no other."""
    span, out = timedelta(days=PAY_SPAN[pay.frequency]), {}
    for r in checks:
        payday = _nearest(r.date, paydays(pay, r.date - span, r.date + span))
        if payday is not None:
            out.setdefault(payday, r)
    return out


def period_hours(pay: Row) -> Decimal:
    top, bottom = PAY_WEEKS[pay.frequency]
    return q(pay.hours * top / bottom)


def base_pay(pay: Row) -> Decimal:
    """Pay before taxes for one pay period at the usual hours."""
    top, bottom = PAY_WEEKS[pay.frequency]
    return q(pay.hours * top * pay.rate / bottom)


@dataclass(frozen=True)
class PayEstimate:
    amount: Decimal    # the take-home to expect
    base: Decimal      # base pay for one period, before taxes
    hours: Decimal     # usual hours in one period
    kept: Decimal      # percent of pay kept, to one decimal place
    count: int         # paychecks it was learned from (0 = the starting percent)


def pay_estimate(rows, pay: Row) -> PayEstimate:
    base = base_pay(pay)
    recent = [r for r in paychecks(rows, pay) if r.active and r.estimate != ASSUMED and r.amount > 0][-6:]
    if recent:
        kept = sum((q(r.amount) for r in recent), ZERO)
        earned = sum((q(r.hours * pay.rate) if r.hours > 0 else base for r in recent), ZERO)
    else:
        kept, earned = (pay.percent if pay.percent > 0 else Decimal(100)), Decimal(100)
    if earned <= 0:
        return PayEstimate(base, base, period_hours(pay), Decimal("100.0"), 0)
    share = (kept * 1000 / earned).quantize(Decimal(1), rounding=ROUND_HALF_UP) / 10
    return PayEstimate(q(base * kept / earned), base, period_hours(pay), share, len(recent))


def pay_forecast(rows, start: date, end: date) -> list[Row]:
    out = []
    for pay in pays(rows):
        if not pay.active:
            continue
        est, taken = pay_estimate(rows, pay), covered_paydays(paychecks(rows, pay), pay)
        if est.amount <= 0:
            continue
        for payday in paydays(pay, start, end):
            if payday not in taken:
                out.append(Row(f"est-{pay.id}-{payday.isoformat()}", "onetime", payday, pay.description,
                               "income", est.amount, pay=pay.id, estimated=True))
    return out


@dataclass(frozen=True)
class NextPaycheck:
    payday: date
    entered: Row | None
    estimate: PayEstimate


def next_paycheck(rows, pay: Row, today: date) -> NextPaycheck | None:
    upcoming = paydays(pay, today, add_months(today, 2))
    if not upcoming:
        return None
    return NextPaycheck(upcoming[0], covered_paydays(paychecks(rows, pay), pay).get(upcoming[0]), pay_estimate(rows, pay))


def open_paydays(rows, pay: Row, today: date, limit: int = 4) -> list[date]:
    """Paydays since the latest balance that have no paycheck entered, up to
    and including the next one. The most recent ones if there are many."""
    taken = covered_paydays(paychecks(rows, pay), pay)
    upcoming = paydays(pay, today + timedelta(days=1), add_months(today, 2))[:1]
    days = paydays(pay, _since(rows, today), today) + upcoming
    return [d for d in days if d not in taken][-limit:]


@dataclass(frozen=True)
class PendingPaycheck:
    pay: Row
    payday: date


def pending_paychecks(rows, today: date) -> list[PendingPaycheck]:
    """For each pay, the earliest payday that has arrived with no paycheck entered."""
    out = []
    for pay in pays(rows):
        if pay.active:
            due = [d for d in open_paydays(rows, pay, today) if d <= today]
            if due:
                out.append(PendingPaycheck(pay, due[0]))
    return out


# --------------------------------------------------------------------- forecasts

def forecast_rows(rows, start: date, end: date) -> list[Row]:
    """Estimated card payments and paychecks dated within [start, end] that
    have nothing entered. These rows are for projections; they are only
    saved when a balance update closes the period they fall in."""
    return card_forecast(rows, start, end) + pay_forecast(rows, start, end)


# ---------------------------------------------------------------------- balances

def balances(rows) -> list[Row]:
    return sorted((r for r in rows if r.type == "balance"), key=lambda r: r.date)


def anchor(rows) -> Row | None:
    found = balances(rows)
    return found[-1] if found else None


def start_of_day(rows, day: date) -> Decimal | None:
    """Balance at the start of ``day``, before anything dated that day.
    None if there's no balance row that early."""
    base = None
    for b in balances(rows):
        if b.date <= day:
            base = b
    if base is None:
        return None
    return q(base.amount + total(events_in(rows, base.date, day - timedelta(days=1))))


def end_of_day(rows, day: date) -> Decimal | None:
    start = start_of_day(rows, day)
    return None if start is None else q(start + total(events_in(rows, day, day)))


def horizon_end(origin: date, span) -> date:
    """span is ('days', n) or ('months', n)."""
    kind, n = span
    return origin + timedelta(days=n) if kind == "days" else add_months(origin, n)


@dataclass(frozen=True)
class Point:
    date: date
    balance: Decimal
    events: tuple


@dataclass(frozen=True)
class Projection:
    origin: date
    end: date
    origin_balance: Decimal   # start of the origin day
    end_balance: Decimal      # end of the last day
    low: Point
    points: tuple
    events: tuple


def project(rows, today: date, span) -> Projection | None:
    """Day-by-day balance from today (or the latest balance date, if that's
    later) through the end of the span. Includes everything dated today."""
    base = anchor(rows)
    if base is None:
        return None
    origin = max(today, base.date)
    origin_balance = start_of_day(rows, origin)
    end = horizon_end(origin, span)
    events = events_in(rows, origin, end)
    points = [Point(origin, origin_balance, ())]
    running = origin_balance
    for day, group in itertools.groupby(events, key=lambda e: e.date):
        group = tuple(group)
        running = q(running + total(group))
        points.append(Point(day, running, group))
    low = min(points, key=lambda p: (p.balance, p.date))
    return Projection(origin, end, origin_balance, running, low, tuple(points), tuple(events))


def cash_flow(rows, today: date):
    """Totals by category over the next 12 months, with monthly averages."""
    base = anchor(rows)
    if base is None:
        return [], ZERO
    origin = max(today, base.date)
    sums = {}
    for e in events_in(rows, origin, add_months(origin, 12) - timedelta(days=1)):
        sums[e.category] = sums.get(e.category, ZERO) + e.amount
    lines = [(key, label, q(sums[key]), q(sums[key] / 12))
             for key, label in CATEGORIES.items() if sums.get(key)]
    return lines, q(sum((line[2] for line in lines), ZERO))


# --------------------------------------------------------------------- snapshots

def take_snapshot(rows, as_of: date, today: date, actual: Decimal | None = None):
    """Record the balance at the start of ``as_of``. Uses ``actual`` if given
    (what the bank says), otherwise the calculated start-of-day balance."""
    base = anchor(rows)
    if base is None:
        raise ValueError("Set a starting balance first.")
    if as_of <= base.date:
        raise ValueError(f"Pick a date after your last balance update ({base.date:%b} {base.date.day}, {base.date.year}).")
    if as_of > today:
        raise ValueError("A balance update can't be in the future.")
    # Estimates dated before the new balance become part of history: they are
    # saved as they stood, so later changes to an average can't rewrite the past.
    assumed = [replace(r, id=new_id(), estimated=False, estimate=ASSUMED)
               for r in forecast_rows(rows, base.date, as_of - timedelta(days=1))]
    settled = list(rows) + assumed
    amount = q(actual) if actual is not None else start_of_day(settled, as_of)
    row = Row(new_id(), "balance", as_of, "Balance update", "", amount, "", "active")
    return settled + [row], row


def undo_snapshot(rows):
    found = balances(rows)
    if len(found) < 2:
        raise ValueError("There's no balance update to undo.")
    last = found[-1]
    return [r for r in rows if r.id != last.id]


@dataclass(frozen=True)
class SnapshotInfo:
    row: Row
    change: Decimal | None     # vs the previous balance row
    expected: Decimal | None   # what the ledger predicted for this date
    variance: Decimal | None   # actual minus expected (untracked spending/income)


def snapshot_history(rows) -> list[SnapshotInfo]:
    found = balances(rows)
    out = []
    for i, b in enumerate(found):
        if i == 0:
            out.append(SnapshotInfo(b, None, None, None))
            continue
        prev = found[i - 1]
        expected = q(prev.amount + total(events_in(rows, prev.date, b.date - timedelta(days=1))))
        out.append(SnapshotInfo(b, q(b.amount - prev.amount), expected, q(b.amount - expected)))
    return list(reversed(out))


@dataclass(frozen=True)
class Period:
    start: date     # first day, inclusive
    end: date       # last day, inclusive
    days: int
    count: int
    spent: Decimal
    monthly: Decimal
    open: bool


def category_periods(rows, today: date, category: str = "creditcard") -> list[Period]:
    """Spending in one category between consecutive balance updates, plus the
    period in progress (through today). Includes recurring and one-time rows."""
    found = balances(rows)
    spans = [(a.date, b.date - timedelta(days=1), False) for a, b in zip(found, found[1:])]
    if found and today >= found[-1].date:
        spans.append((found[-1].date, today, True))
    out = []
    for start, end, is_open in spans:
        hits = [e for e in events_in(rows, start, end) if e.category == category]
        spent = q(sum((-e.amount for e in hits), ZERO))
        days = (end - start).days + 1
        monthly = q(spent / days * DAYS_PER_MONTH)
        out.append(Period(start, end, days, len(hits), spent, monthly, is_open))
    return list(reversed(out))


def average_monthly(periods) -> Decimal | None:
    closed = [p for p in periods if not p.open]
    days = sum(p.days for p in closed)
    if not days:
        return None
    return q(sum((p.spent for p in closed), ZERO) / days * DAYS_PER_MONTH)


def split_onetime(rows):
    """(upcoming, settled): one-time rows on/after vs before the latest
    balance date. Settled rows are already part of that balance."""
    base = anchor(rows)
    cut = base.date if base else date.min
    onetime = [r for r in rows if r.type == "onetime"]
    upcoming = sorted((r for r in onetime if r.date >= cut), key=lambda r: r.date)
    settled = sorted((r for r in onetime if r.date < cut), key=lambda r: r.date, reverse=True)
    return upcoming, settled


# --------------------------------------------------------------------- migration

def rows_from_state_json(text: str) -> list[Row]:
    """Convert the old app's state.json into ledger rows. The old app stored
    end-of-day balances, which equal the start of the following day."""
    data = json.loads(text)
    if not isinstance(data, dict):
        return []
    rows: list[Row] = []

    def add(raw):
        row = parse_row(raw)
        if row:
            rows.append(row)

    def next_day(text_day):
        try:
            return (date.fromisoformat(str(text_day)) + timedelta(days=1)).isoformat()
        except ValueError:
            return None

    settings = data.get("settings") or {}
    snapshots = [s for s in (data.get("snapshots") or []) if isinstance(s, dict)]
    found = {}
    if snapshots:
        first = min(snapshots, key=lambda s: str(s.get("asOfDate") or ""))
        found[first.get("priorStartingDate")] = first.get("priorBalance")
    for s in snapshots:
        found[s.get("asOfDate")] = s.get("newBalance")
    if settings.get("startingDate") and settings.get("startingBalance") is not None:
        found[settings["startingDate"]] = settings["startingBalance"]
    for day, amount in found.items():
        if day and amount is not None and next_day(day):
            add({"type": "balance", "date": next_day(day), "description": "Imported balance", "amount": str(amount)})

    earliest = min((r.date for r in rows), default=None)
    pay, pay_date = settings.get("paycheckAmount"), settings.get("nextPayDate")
    if pay and pay_date:
        try:
            start = date.fromisoformat(pay_date)
            while earliest and start > earliest:   # walk back so past paychecks exist
                start -= timedelta(days=14)
            add({"type": "recurring", "date": start.isoformat(), "description": "Paycheck",
                 "category": "income", "amount": str(abs(Decimal(str(pay)))), "frequency": "biweekly"})
        except (ValueError, InvalidOperation):
            pass

    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        once = item.get("freq") == "once"
        add({"type": "onetime" if once else "recurring", "date": item.get("date"),
             "description": item.get("name"), "category": item.get("category"),
             "amount": str(item.get("amount")), "frequency": "" if once else item.get("freq"),
             "status": "paused" if item.get("active") is False else "active"})
    for item in list(data.get("onetime") or []) + list(data.get("archive") or []):
        if not isinstance(item, dict):
            continue
        add({"type": "onetime", "date": item.get("date"), "description": item.get("name"),
             "category": item.get("category"), "amount": str(item.get("amount")),
             "status": "paused" if item.get("active") is False else "active"})
    return rows


def migrate_if_needed(ledger: Ledger, state_path: str) -> int:
    """One-time import of the previous app's data/state.json. Only runs when
    there's no ledger.csv yet; state.json itself is left untouched."""
    if ledger.exists() or not os.path.exists(state_path):
        return 0
    try:
        with open(state_path, encoding="utf-8") as fh:
            rows = rows_from_state_json(fh.read())
    except (OSError, ValueError) as exc:
        log.warning("Couldn't import %s: %s", state_path, exc)
        return 0
    if rows:
        ledger.save(rows)
        log.info("Imported %d rows from %s", len(rows), state_path)
    return len(rows)
