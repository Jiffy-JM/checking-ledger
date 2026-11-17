"""Checking Ledger: Flask web app on top of ledger_core and networth.

Run locally:   flask --app app run --debug
In Docker:     gunicorn "app:create_app()"   (see Dockerfile)

Privacy: this app never contacts anything outside your network. It makes no
outbound requests, loads no outside fonts/scripts/styles, and the
Content-Security-Policy below stops the browser from talking to any other
host either.
"""
from __future__ import annotations

import hmac
import logging
import math
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (Flask, Response, abort, flash, make_response, redirect,
                   render_template, request, session, url_for)

import backup_status
import ledger_core as core
import networth as nw
from themes import DEFAULT_MODE, DEFAULT_THEME, MODES, THEMES

# key: (button label, spoken label, span)
HORIZONS = {
    "2w": ("2W", "2 weeks", ("days", 14)),
    "1m": ("1M", "1 month", ("months", 1)),
    "3m": ("3M", "3 months", ("months", 3)),
    "6m": ("6M", "6 months", ("months", 6)),
    "1y": ("1Y", "1 year", ("months", 12)),
}
DEFAULT_HORIZON = "1y"
MAX_UPLOAD = 5 * 1024 * 1024
log = logging.getLogger("ledger.app")


# ------------------------------------------------------------------ formatting

def money(value, signed: bool = False) -> str:
    if value is None:
        return ""
    value = core.q(value)
    text = f"${abs(value):,.2f}"
    if value < 0:
        return "\u2212" + text
    return "+" + text if signed and value > 0 else text


def money_short(value: float) -> str:
    sign = "\u2212" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:,.2f}".rstrip("0").rstrip(".") + "M"
    if value >= 1000:
        text = f"{value / 1000:,.1f}".rstrip("0").rstrip(".")
        return f"{sign}${text}k"
    return f"{sign}${value:,.0f}"


def ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def fmt_date(day: date, year: bool = True) -> str:
    return f"{day:%b} {day.day}, {day.year}" if year else f"{day:%b} {day.day}"


def parse_money(text: str, allow_negative: bool = False) -> Decimal | None:
    if not (text or "").strip():
        return None
    try:
        value = core.parse_amount_text(text)
    except ValueError:
        return None
    if value < 0 and not allow_negative:
        return None
    return value


def parse_day(text: str) -> date | None:
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


# ----------------------------------------------------------------------- chart

def nice_ticks(lo: float, hi: float, count: int = 4) -> list[float]:
    if hi - lo < 1:
        lo, hi = lo - 50, hi + 50
    raw = (hi - lo) / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start, stop = math.floor(lo / step) * step, math.ceil(hi / step) * step
    ticks, value = [], start
    while value <= stop + step * 1e-9:
        ticks.append(round(value, 2))
        value += step
    return ticks


def build_chart(points, start: date, end: date, mode: str = "step", ghost=None) -> dict:
    """Coordinates for a chart in a 1000x300 SVG box (stretched to fit),
    plus the data the scrubber in app.js needs.

    points: list of (date, value, label). mode "step" holds each value until
    the next change (balances); "line" connects the points (net worth)."""
    values = [float(v) for _, v, _ in points]
    ghost_values = [float(v) for _, v, _ in ghost or []]
    ticks = nice_ticks(min(values + ghost_values), max(values + ghost_values))
    y_min, y_max = ticks[0], ticks[-1]
    span_days = max((end - start).days, 1)

    def x(day):
        return (day - start).days / span_days * 1000

    def y(value):
        return (1 - (float(value) - y_min) / (y_max - y_min)) * 300

    first = points[0]
    if mode == "step":
        line = f"M0,{y(first[1]):.1f}"
        for day, value, _ in points[1:]:
            line += f" H{x(day):.1f} V{y(value):.1f}"
        line += " H1000"
        area = line + " V300 H0 Z"
    else:
        line = f"M{x(first[0]):.1f},{y(first[1]):.1f}"
        for day, value, _ in points[1:]:
            line += f" L{x(day):.1f},{y(value):.1f}"
        last_x = x(points[-1][0])
        area = line + f" V300 H{x(first[0]):.1f} Z"
        if len(points) == 1:
            line += f" H{last_x + 0.1:.1f}"
    ghost_line = None
    if ghost:   # the projection without a what-if, drawn faintly behind the main line
        ghost_line = f"M0,{y(ghost[0][1]):.1f}"
        for day, value, _ in ghost[1:]:
            ghost_line += f" H{x(day):.1f} V{y(value):.1f}"
        ghost_line += " H1000"
    lowest = min(range(len(points)), key=lambda i: (points[i][1], points[i][0]))
    data = [{
        "x": round(x(day) / 10, 3),
        "y": round(y(value) / 3, 3),
        "b": money(value),
        "l": label,
        "d": fmt_date(day, year=False),
        "D": fmt_date(day),
    } for day, value, label in points]
    labels = [start + timedelta(days=round(span_days * i / 4)) for i in range(5)]
    return {
        "line": line,
        "ghost_line": ghost_line,
        "area": area,
        "mode": mode,
        "grid": [round(y(t), 1) for t in ticks],
        "zero": round(y(0), 1) if y_min < 0 < y_max else None,
        "y_labels": [money_short(t) for t in reversed(ticks)],
        "x_labels": [f"{d:%b} '{d:%y}" if span_days > 180 else fmt_date(d, year=False) for d in labels],
        "points": data,
        "low_index": lowest,
        "origin": start.isoformat(),
        "span": span_days,
    }


# ------------------------------------------------------------------------- app

def _persistent_secret(data_dir: str) -> str:
    path = os.path.join(data_dir, ".secret_key")
    try:
        with open(path, encoding="utf-8") as fh:
            value = fh.read().strip()
            if len(value) >= 32:
                return value
    except FileNotFoundError:
        pass
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return value


def create_app(data_dir: str | None = None, password: str | None = None, today=None,
               allowed_hosts: str | None = None, backup_status_file: str | None = None,
               now=None) -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Flask(__name__)
    data_dir = data_dir or os.environ.get("DATA_DIR", "./data")
    os.makedirs(data_dir, exist_ok=True)
    if not os.access(data_dir, os.W_OK):
        raise SystemExit(
            f"Can't write to the data folder ({data_dir}). Make sure PUID and PGID in .env "
            "match the owner of the data folder on the host (run `id -u` and `id -g`).")

    app.secret_key = os.environ.get("SECRET_KEY") or _persistent_secret(data_dir)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=MAX_UPLOAD,
    )
    password = os.environ.get("APP_PASSWORD", "") if password is None else password
    if not password:
        log.warning("APP_PASSWORD isn't set. Anyone who can reach this server can open the ledger.")
    # A signed-in session carries this stamp instead of a plain "yes". It is
    # derived from the password, so changing APP_PASSWORD signs everyone out.
    auth_stamp = hmac.new(app.secret_key.encode(), password.encode(), "sha256").hexdigest()

    # Optional list of the addresses this app may be opened at, like
    # "192.168.1.50,ledger.local". Requests that name any other host are
    # refused, which stops a web page elsewhere from pointing its own domain
    # name at this server (DNS rebinding) to read pages through your browser.
    if allowed_hosts is None:
        allowed_hosts = os.environ.get("ALLOWED_HOSTS", "")
    allowed = {h.strip().lower() for h in allowed_hosts.split(",") if h.strip()}
    try:
        tz = ZoneInfo(os.environ.get("TZ") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("Unknown TZ %r, using UTC", os.environ.get("TZ"))
        tz = ZoneInfo("UTC")
    today_fn = today or (lambda: datetime.now(tz).date())
    now_fn = now or (lambda: datetime.now(timezone.utc))

    # The optional backup container writes this file; the app only reads it.
    if backup_status_file is None:
        backup_status_file = os.environ.get("BACKUP_STATUS_FILE", "/backup-status/status.json")

    def fmt_moment(moment) -> str:
        local = moment.astimezone(tz)
        clock = local.strftime("%I:%M %p").lstrip("0")
        return f"{fmt_date(local.date())} at {clock}"

    def backup_info():
        return backup_status.read_status(backup_status_file, now_fn())

    # The look every browser starts with; each browser can then pick its own
    # on the Theme page (kept in two cookies).
    start_theme = os.environ.get("THEME", "").strip().lower()
    start_theme = start_theme if start_theme in THEMES else DEFAULT_THEME
    start_mode = os.environ.get("THEME_MODE", "").strip().lower()
    start_mode = start_mode if start_mode in MODES else DEFAULT_MODE

    def current_look():
        theme, mode = request.cookies.get("theme"), request.cookies.get("mode")
        return (theme if theme in THEMES else start_theme, mode if mode in MODES else start_mode)

    ledger = core.Ledger(os.path.join(data_dir, "ledger.csv"))
    worth = nw.NetWorthStore(os.path.join(data_dir, "networth.csv"))
    core.migrate_if_needed(ledger, os.path.join(data_dir, "state.json"))
    asset_version = str(int(time.time()))

    # ------------------------------------------------------------- guards

    def csrf_token() -> str:
        token = session.get("_csrf")
        if not token:
            token = session["_csrf"] = secrets.token_urlsafe(32)
        return token

    @app.before_request
    def guard():
        if request.endpoint == "healthz":
            return None
        if allowed:
            host = request.host.lower()
            if host not in allowed and re.sub(r":\d+$", "", host) not in allowed:
                abort(400, "This server isn't set up to be opened at that address. "
                           "Add it to ALLOWED_HOSTS in the .env file.")
        if request.endpoint == "static":
            return None
        if request.method == "POST":
            sent = request.form.get("_csrf", "").encode()
            expected = session.get("_csrf", "").encode()
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400, "This form expired. Go back, reload the page, and try again.")
        signed_in = hmac.compare_digest(str(session.get("auth") or ""), auth_stamp)
        if password and not signed_in and request.endpoint != "login":
            return redirect(url_for("login", next=request.path))
        return None

    @app.after_request
    def headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.context_processor
    def helpers():
        theme, mode = current_look()
        return {
            "theme": theme, "mode": mode, "THEMES": THEMES, "MODES": MODES,
            "theme_light": THEMES[theme][2], "theme_dark": THEMES[theme][3],
            "csrf_token": csrf_token, "money": money, "fmt_date": fmt_date,
            "CATEGORIES": core.CATEGORIES, "FREQUENCIES": core.FREQUENCIES, "KINDS": nw.KINDS,
            "auth_enabled": bool(password), "asset_v": asset_version, "fmt_moment": fmt_moment,
            "ESTIMATES": core.ESTIMATES, "ordinal": ordinal, "plain": core.plain,
        }

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def error_page(err):
        return render_template("error.html", error=err), err.code

    def read_upload():
        """Return (text, error) for the uploaded CSV in the 'file' field."""
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return None, "Choose a CSV file to upload."
        if not upload.filename.lower().endswith(".csv"):
            return None, "That file isn't a .csv. In Numbers or Excel, export as CSV first."
        return core.decode_upload(upload.read()), None

    # ------------------------------------------------------------- pages

    @app.get("/healthz")
    def healthz():
        return "ok"

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not password:
            return redirect(url_for("overview"))
        error = None
        if request.method == "POST":
            if hmac.compare_digest(request.form.get("password", "").encode(), password.encode()):
                session.clear()
                session.permanent = True
                session["auth"] = auth_stamp
                target = request.args.get("next", "")
                if not target.startswith("/") or target.startswith("//"):
                    target = url_for("overview")
                return redirect(target)
            time.sleep(1)
            error = "That password isn't right."
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/appearance", methods=["GET", "POST"])
    def appearance():
        if request.method == "POST":
            theme, mode = request.form.get("theme", ""), request.form.get("mode", "")
            if theme not in THEMES or mode not in MODES:
                flash("Pick a theme and light, dark, or match device.", "error")
                return redirect(url_for("appearance"))
            resp = redirect(url_for("appearance"))
            for name, value in (("theme", theme), ("mode", mode)):
                resp.set_cookie(name, value, max_age=60 * 60 * 24 * 365, samesite="Lax", httponly=True,
                                secure=app.config["SESSION_COOKIE_SECURE"])
            flash(f"Theme set to {THEMES[theme][0]}, {MODES[mode].lower()}.", "ok")
            return resp
        return render_template("appearance.html", start_theme=THEMES[start_theme][0])

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        rows = ledger.load()
        if core.anchor(rows):
            return redirect(url_for("overview"))
        today = today_fn()
        form = {"balance": "", "date": today.isoformat(), "pay": "", "pay_date": ""}
        errors = {}
        if request.method == "POST":
            form = {k: request.form.get(k, "").strip() for k in form}
            balance = parse_money(form["balance"], allow_negative=True)
            day = parse_day(form["date"])
            pay = parse_money(form["pay"]) if form["pay"] else None
            pay_day = parse_day(form["pay_date"]) if form["pay_date"] else None
            if balance is None:
                errors["balance"] = "Enter your current balance, like 3200.00."
            if day is None:
                errors["date"] = "Pick the date that balance is from."
            elif day > today:
                errors["date"] = "The balance date can't be in the future."
            if form["pay"] and (pay is None or pay <= 0):
                errors["pay"] = "Enter your take-home pay, like 2808.99."
            if pay and pay_day is None:
                errors["pay_date"] = "Pick your next payday."
            if not errors:
                new = [core.Row(core.new_id(), "balance", day, "Starting balance", "", balance)]
                if pay:
                    new.append(core.Row(core.new_id(), "recurring", pay_day, "Paycheck",
                                        "income", pay, "biweekly"))
                ledger.update(lambda current: current + new)
                flash("You're set up. Add your bills and card payments next.", "ok")
                return redirect(url_for("overview"))
        return render_template("setup.html", form=form, errors=errors, active="overview")

    @app.get("/")
    def overview():
        rows = ledger.load()
        base = core.anchor(rows)
        if base is None:
            return redirect(url_for("setup"))
        horizon = request.args.get("h") or request.cookies.get("h")
        if horizon not in HORIZONS:
            horizon = DEFAULT_HORIZON
        today = today_fn()
        origin = max(today, base.date)
        # Card payments and hourly paychecks from the latest balance onward:
        # what was entered, or an estimate where nothing has been.
        planned = rows + core.forecast_rows(rows, base.date, core.add_months(origin, 13))
        trial, wi_form, wi_error = read_what_if(origin)
        shown = planned + [trial] if trial else planned
        proj = core.project(shown, today, HORIZONS[horizon][2])
        plain = core.project(planned, today, HORIZONS[horizon][2]) if trial else None
        points = [(p.date, p.balance, ", ".join(e.description for e in p.events)[:70])
                  for p in proj.points]
        ghost = [(p.date, p.balance, "") for p in plain.points] if plain else None
        flow, net = core.cash_flow(planned, today)
        soon = [p for p in proj.points[1:] if p.date < proj.origin + timedelta(days=30)]
        wi_args = ({"wi_dir": wi_form["direction"], "wi_amount": wi_form["amount"], "wi_date": wi_form["date"]}
                   if trial else {})
        resp = make_response(render_template(
            "overview.html", active="overview", proj=proj, plain=plain, trial=trial,
            wi_form=wi_form, wi_error=wi_error, wi_args=wi_args, origin=origin,
            pending=core.pending_statements(rows, today), pending_pay=core.pending_paychecks(rows, today),
            chart=build_chart(points, proj.origin, proj.end, "step", ghost),
            horizon=horizon, horizons=HORIZONS, flow=flow, net=net, soon=soon,
            base=base, today=today, can_update=today > base.date,
            min_date=base.date + timedelta(days=1),
            backup=backup_info(),
            today_end=core.end_of_day(shown, max(today, base.date)),
            today_start=core.start_of_day(planned, max(today, base.date))))
        if request.args.get("h") in HORIZONS:
            resp.set_cookie("h", horizon, max_age=60 * 60 * 24 * 365, samesite="Lax", httponly=True)
        return resp

    @app.get("/transactions")
    def transactions():
        rows = ledger.load()
        if core.anchor(rows) is None:
            return redirect(url_for("setup"))
        today = today_fn()
        upcoming, _ = core.split_onetime(rows)
        recurring = sorted((r for r in rows if r.type == "recurring"),
                           key=lambda r: (not r.active, r.amount > 0, r.description.lower()))
        nexts = {r.id: core.next_occurrence(r, today) for r in recurring}
        by_name = lambda r: (not r.active, r.description.lower(), r.id)
        return render_template("transactions.html", active="transactions",
                               upcoming=upcoming, recurring=recurring, nexts=nexts,
                               cards=[(c, core.next_payment(rows, c, today)) for c in sorted(core.cards(rows), key=by_name)],
                               pays=[(p, core.next_paycheck(rows, p, today)) for p in sorted(core.pays(rows), key=by_name)])

    @app.get("/history")
    def history():
        rows = ledger.load()
        if core.anchor(rows) is None:
            return redirect(url_for("setup"))
        today = today_fn()
        periods = core.category_periods(rows, today, "creditcard")
        _, settled = core.split_onetime(rows)
        return render_template("history.html", active="history",
                               snapshots=core.snapshot_history(rows), periods=periods,
                               card_average=core.average_monthly(periods), settled=settled,
                               upload_errors=None, backup=backup_info())

    # ------------------------------------------------------------ what-if

    def read_what_if(origin: date):
        """A what-if lives only in the page address (?wi_amount=...&wi_date=...),
        so trying one never changes the ledger. Returns (row, form, error)."""
        form = {"direction": request.args.get("wi_dir", "out"), "amount": request.args.get("wi_amount", "").strip(),
                "date": request.args.get("wi_date", "").strip()}
        if form["direction"] not in ("in", "out"):
            form["direction"] = "out"
        if "wi_amount" not in request.args:
            form["date"] = (origin + timedelta(days=14)).isoformat()
            return None, form, None
        amount, day = parse_money(form["amount"]), parse_day(form["date"])
        if amount is None or amount <= 0:
            return None, form, "Enter an amount greater than zero, like 1500.00."
        if day is None:
            return None, form, "Pick a date."
        if day < origin:
            return None, form, "Pick today or a later date."
        money_in = form["direction"] == "in"
        form["amount"] = f"{amount:.2f}"
        return core.Row("whatif", "onetime", day, "What-if", "income" if money_in else "bill",
                        amount if money_in else -amount, what_if=True), form, None

    # ------------------------------------------------------- credit cards

    def find_card(rows, card_id):
        for r in core.cards(rows):
            if r.id == card_id:
                return r
        abort(404)

    def read_card_form():
        form = {k: request.form.get(k, "").strip() for k in ("name", "close_day", "due_day", "estimate", "fixed")}
        errors = {}

        def day(text):
            return int(text) if re.fullmatch(r"\d{1,2}", text) and 1 <= int(text) <= 31 else None

        name, close, due = core.clean_text(form["name"]), day(form["close_day"]), day(form["due_day"])
        fixed = parse_money(form["fixed"]) if form["fixed"] else Decimal("0")
        if form["estimate"] not in core.ESTIMATES:
            form["estimate"] = "average"
        if not name:
            errors["name"] = "Give the card a name, like Visa."
        if close is None:
            errors["close_day"] = "Enter a day from 1 to 31."
        if due is None:
            errors["due_day"] = "Enter a day from 1 to 31."
        if fixed is None:
            errors["fixed"] = "Enter an amount like 1500.00, or leave it blank."
        elif form["estimate"] == "fixed" and not fixed:
            errors["fixed"] = "Enter the amount to use, like 1500.00."
        if errors:
            return None, errors, form
        return {"description": name, "close_day": close, "due_day": due, "estimate": form["estimate"],
                "amount": fixed}, {}, form

    def card_page(card, form=None, errors=None, statement_amount="", status=200):
        rows, today = ledger.load(), today_fn()
        if card is not None:
            card = find_card(rows, card.id)
        if form is None:
            form = ({"name": card.description, "close_day": str(card.close_day), "due_day": str(card.due_day),
                     "estimate": card.estimate, "fixed": f"{card.amount:.2f}" if card.amount else ""}
                    if card else {"name": "", "close_day": "", "due_day": "", "estimate": "average", "fixed": ""})
        context = {"active": "transactions", "card": card, "form": form, "errors": errors or {},
                   "statement_amount": statement_amount, "today": today}
        if card:
            context.update(
                est=core.card_estimate(rows, card),
                open_dues=[(d, core.close_before(card, d)) for d in core.open_due_dates(rows, card, today)],
                past=list(reversed(core.card_statements(rows, card)[-6:])), ASSUMED=core.ASSUMED)
        return render_template("card_form.html", **context), status

    @app.route("/cards/new", methods=["GET", "POST"])
    def new_card():
        if core.anchor(ledger.load()) is None:
            return redirect(url_for("setup"))
        if request.method == "POST":
            values, errors, form = read_card_form()
            if not values:
                return card_page(None, form, errors)
            row = core.Row(core.new_id(), "card", core.CARD_DATE, **values)
            ledger.update(lambda rows: rows + [row])
            flash(f"Added {row.description}.", "ok")
            return redirect(url_for("transactions"))
        return card_page(None)

    @app.route("/cards/<card_id>", methods=["GET", "POST"])
    def edit_card(card_id):
        card = find_card(ledger.load(), card_id)
        if request.method == "POST":
            values, errors, form = read_card_form()
            if not values:
                return card_page(card, form, errors)

            def change(rows):
                target = find_card(rows, card_id)
                return [core.replace(r, **values) if r is target else r for r in rows]
            ledger.update(change)
            flash(f"Saved {values['description']}.", "ok")
            return redirect(url_for("transactions"))
        return card_page(card)

    @app.post("/cards/<card_id>/statement")
    def card_statement(card_id):
        rows, today = ledger.load(), today_fn()
        card = find_card(rows, card_id)
        due, text = parse_day(request.form.get("due", "")), request.form.get("amount", "").strip()
        amount = parse_money(text)
        if amount is None or amount <= 0 or due not in core.open_due_dates(rows, card, today):
            return card_page(card, errors={"statement": "Enter the statement balance, like 1461.05."},
                             statement_amount=text)
        row = core.Row(core.new_id(), "onetime", due, f"{card.description} payment", "creditcard", -amount,
                       card=card.id)
        ledger.update(lambda current: current + [row])
        flash(f"Saved the {card.description} statement: {money(amount)} due {fmt_date(due)}.", "ok")
        return redirect(url_for("transactions"))

    @app.post("/cards/<card_id>/pause")
    def toggle_card(card_id):
        def change(rows):
            target = find_card(rows, card_id)
            status = "active" if target.status == "paused" else "paused"
            return [core.replace(r, status=status) if r is target else r for r in rows]
        card = find_card(ledger.update(change), card_id)
        flash(f"{card.description} is {'paused' if card.status == 'paused' else 'back on'}.", "ok")
        return redirect(url_for("transactions"))

    @app.post("/cards/<card_id>/delete")
    def delete_card(card_id):
        removed = {}

        def change(rows):
            removed["card"] = find_card(rows, card_id)
            # Statements already entered stay as ordinary one-time transactions.
            return [core.replace(r, card="") if r.card == card_id else r for r in rows if r.id != card_id]
        ledger.update(change)
        flash(f"Deleted {removed['card'].description}.", "ok")
        return redirect(url_for("transactions"))

    # --------------------------------------------------------- hourly pay

    def find_pay(rows, pay_id):
        for r in core.pays(rows):
            if r.id == pay_id:
                return r
        abort(404)

    def read_number(text, low, high):
        """A plain number above ``low`` and up to ``high``, or None."""
        value = parse_money(text)
        return value if value is not None and low < value <= high else None

    def read_pay_form():
        form = {k: request.form.get(k, "").strip() for k in ("name", "rate", "hours", "frequency", "payday", "percent")}
        errors = {}
        name, rate, hours = core.clean_text(form["name"]), read_number(form["rate"], 0, 100000), read_number(form["hours"], 0, 168)
        payday = parse_day(form["payday"])
        percent = read_number(form["percent"], 0, 100) if form["percent"] else Decimal("0")
        if not name:
            errors["name"] = "Give it a name, like Paycheck."
        if rate is None:
            errors["rate"] = "Enter your hourly rate, like 25.00."
        if hours is None:
            errors["hours"] = "Enter the hours in a usual week, like 40."
        if form["frequency"] not in core.PAY_FREQUENCIES:
            errors["frequency"] = "Pick how often you are paid."
        if payday is None:
            errors["payday"] = "Pick any payday."
        if percent is None:
            errors["percent"] = "Enter a percent from 1 to 100, or leave it blank."
        if errors:
            return None, errors, form
        return {"description": name, "rate": rate, "hours": hours, "frequency": form["frequency"], "date": payday,
                "percent": percent}, {}, form

    def pay_page(pay, form=None, errors=None, check=None):
        rows, today = ledger.load(), today_fn()
        if pay is not None:
            pay = find_pay(rows, pay.id)
        if form is None:
            form = ({"name": pay.description, "rate": f"{pay.rate:.2f}", "hours": core.plain(pay.hours),
                     "frequency": pay.frequency, "payday": pay.date.isoformat(),
                     "percent": core.plain(pay.percent) if pay.percent else ""}
                    if pay else {"name": "Paycheck", "rate": "", "hours": "40", "frequency": "biweekly",
                                 "payday": "", "percent": ""})
        context = {"active": "transactions", "pay": pay, "form": form, "errors": errors or {}, "today": today,
                   "check": check or {"amount": "", "hours": ""}, "PAY_FREQUENCIES": core.PAY_FREQUENCIES,
                   "ASSUMED": core.ASSUMED, "plain": core.plain}
        if pay:
            opens = core.open_paydays(rows, pay, today)
            arrived = [d for d in opens if d <= today]
            context.update(est=core.pay_estimate(rows, pay), open_paydays=opens,
                           chosen=(arrived[-1] if arrived else opens[0]) if opens else None,
                           past=list(reversed(core.paychecks(rows, pay)[-6:])))
        return render_template("pay_form.html", **context)

    @app.route("/pay/new", methods=["GET", "POST"])
    def new_pay():
        if core.anchor(ledger.load()) is None:
            return redirect(url_for("setup"))
        if request.method == "POST":
            values, errors, form = read_pay_form()
            if not values:
                return pay_page(None, form, errors)
            row = core.Row(core.new_id(), "pay", **values)
            ledger.update(lambda rows: rows + [row])
            flash(f"Added {row.description}.", "ok")
            return redirect(url_for("transactions"))
        return pay_page(None)

    @app.route("/pay/<pay_id>", methods=["GET", "POST"])
    def edit_pay(pay_id):
        pay = find_pay(ledger.load(), pay_id)
        if request.method == "POST":
            values, errors, form = read_pay_form()
            if not values:
                return pay_page(pay, form, errors)

            def change(rows):
                target = find_pay(rows, pay_id)
                return [core.replace(r, **values) if r is target else r for r in rows]
            ledger.update(change)
            flash(f"Saved {values['description']}.", "ok")
            return redirect(url_for("transactions"))
        return pay_page(pay)

    @app.post("/pay/<pay_id>/paycheck")
    def pay_check(pay_id):
        rows, today = ledger.load(), today_fn()
        pay = find_pay(rows, pay_id)
        check = {"amount": request.form.get("amount", "").strip(), "hours": request.form.get("hours", "").strip()}
        payday, amount = parse_day(request.form.get("payday", "")), parse_money(check["amount"])
        hours = read_number(check["hours"], 0, 744) if check["hours"] else Decimal("0")
        errors = {}
        if amount is None or amount <= 0 or payday not in core.open_paydays(rows, pay, today):
            errors["paycheck"] = "Enter your take-home pay, like 1602.11."
        if hours is None:
            errors["worked"] = "Enter the hours you worked, like 80, or leave it blank."
        if errors:
            return pay_page(pay, errors=errors, check=check)
        row = core.Row(core.new_id(), "onetime", payday, pay.description, "income", amount, pay=pay.id, hours=hours)
        ledger.update(lambda current: current + [row])
        flash(f"Saved the {fmt_date(payday)} paycheck: {money(amount)}.", "ok")
        return redirect(url_for("transactions"))

    @app.post("/pay/<pay_id>/pause")
    def toggle_pay(pay_id):
        def change(rows):
            target = find_pay(rows, pay_id)
            status = "active" if target.status == "paused" else "paused"
            return [core.replace(r, status=status) if r is target else r for r in rows]
        pay = find_pay(ledger.update(change), pay_id)
        flash(f"{pay.description} is {'paused' if pay.status == 'paused' else 'back on'}.", "ok")
        return redirect(url_for("transactions"))

    @app.post("/pay/<pay_id>/delete")
    def delete_pay(pay_id):
        removed = {}

        def change(rows):
            removed["pay"] = find_pay(rows, pay_id)
            # Paychecks already entered stay as ordinary one-time transactions.
            return [core.replace(r, pay="") if r.pay == pay_id else r for r in rows if r.id != pay_id]
        ledger.update(change)
        flash(f"Deleted {removed['pay'].description}.", "ok")
        return redirect(url_for("transactions"))

    # --------------------------------------------------------------- help

    @app.get("/help")
    def help_page():
        return render_template("help.html")

    # ------------------------------------------------------- transactions

    def read_tx_form(kind: str):
        form = {k: request.form.get(k, "").strip() for k in
                ("description", "direction", "amount", "category", "date", "frequency")}
        errors = {}
        description = core.clean_text(form["description"])
        amount = parse_money(form["amount"])
        day = parse_day(form["date"])
        if not description:
            errors["description"] = "Add a short name, like Rent or Visa payment."
        if amount is None or amount <= 0:
            errors["amount"] = "Enter an amount greater than zero, like 120.00."
        if day is None:
            errors["date"] = "Pick a date."
        if form["category"] not in core.CATEGORIES:
            errors["category"] = "Pick a category."
        if kind == "recurring" and form["frequency"] not in core.FREQUENCIES:
            errors["frequency"] = "Pick how often it repeats."
        if form["direction"] not in ("in", "out"):
            errors["direction"] = "Choose money in or money out."
        if errors:
            return None, errors, form
        values = {
            "description": description,
            "category": form["category"],
            "date": day,
            "amount": amount if form["direction"] == "in" else -amount,
            "frequency": form["frequency"] if kind == "recurring" else "",
        }
        return values, {}, form

    def find_row(rows, row_id):
        for r in rows:
            if r.id == row_id and r.type in ("recurring", "onetime"):
                return r
        abort(404)

    @app.route("/transactions/new", methods=["GET", "POST"])
    def new_transaction():
        kind = request.args.get("type", "onetime")
        if kind not in ("onetime", "recurring"):
            kind = "onetime"
        today = today_fn()
        form = {"description": "", "direction": "out", "amount": "",
                "category": "creditcard" if kind == "onetime" else "bill",
                "date": today.isoformat(), "frequency": "monthly"}
        if request.method == "GET":
            # "Keep it" on a what-if arrives here with the amount and date filled in.
            amount, day = parse_money(request.args.get("amount", "")), parse_day(request.args.get("date", ""))
            if request.args.get("direction") in ("in", "out"):
                form["direction"] = request.args["direction"]
            if amount:
                form["amount"] = f"{amount:.2f}"
            if day:
                form["date"] = day.isoformat()
            if request.args.get("category") in core.CATEGORIES:
                form["category"] = request.args["category"]
        errors = {}
        if request.method == "POST":
            values, errors, form = read_tx_form(kind)
            if values:
                row = core.Row(core.new_id(), kind, values["date"], values["description"],
                               values["category"], values["amount"], values["frequency"])
                ledger.update(lambda rows: rows + [row])
                flash(f"Added {row.description}.", "ok")
                return redirect(url_for("transactions"))
        return render_template("tx_form.html", active="transactions", kind=kind,
                               form=form, errors=errors, row=None)

    @app.route("/transactions/<row_id>", methods=["GET", "POST"])
    def edit_transaction(row_id):
        row = find_row(ledger.load(), row_id)
        form = {
            "description": row.description, "direction": "in" if row.amount > 0 else "out",
            "amount": f"{abs(row.amount):.2f}", "category": row.category,
            "date": row.date.isoformat(), "frequency": row.frequency or "monthly",
        }
        errors = {}
        if request.method == "POST":
            values, errors, form = read_tx_form(row.type)
            if values:
                def change(rows):
                    target = find_row(rows, row_id)
                    # Saving an assumed estimate means you've corrected it: it's now a real entry.
                    return [core.replace(r, **values, estimate="") if r is target else r for r in rows]
                ledger.update(change)
                flash(f"Saved {values['description']}.", "ok")
                return redirect(url_for("transactions"))
        return render_template("tx_form.html", active="transactions", kind=row.type,
                               form=form, errors=errors, row=row)

    @app.post("/transactions/<row_id>/pause")
    def toggle_transaction(row_id):
        def change(rows):
            target = find_row(rows, row_id)
            status = "active" if target.status == "paused" else "paused"
            return [core.replace(r, status=status) if r is target else r for r in rows]
        row = find_row(ledger.update(change), row_id)
        flash(f"{row.description} is {'paused' if row.status == 'paused' else 'back on'}.", "ok")
        return redirect(url_for("transactions"))

    @app.post("/transactions/<row_id>/delete")
    def delete_transaction(row_id):
        removed = {}

        def change(rows):
            removed["row"] = find_row(rows, row_id)
            return [r for r in rows if r.id != row_id]
        ledger.update(change)
        flash(f"Deleted {removed['row'].description}.", "ok")
        return redirect(url_for("transactions"))

    # ------------------------------------------------------------ balance

    @app.post("/balance")
    def update_balance():
        today = today_fn()
        day = parse_day(request.form.get("date", ""))
        actual_text = request.form.get("balance", "").strip()
        actual = parse_money(actual_text, allow_negative=True) if actual_text else None
        if day is None:
            flash("Pick the date for this balance.", "error")
        elif actual_text and actual is None:
            flash("Enter the balance as a number, like 3200.00.", "error")
        else:
            try:
                saved = {}

                def change(rows):
                    new_rows, saved["row"] = core.take_snapshot(rows, day, today, actual)
                    return new_rows
                ledger.update(change)
                row = saved["row"]
                flash(f"Balance updated to {money(row.amount)} as of {fmt_date(row.date)}.", "ok")
            except ValueError as exc:
                flash(str(exc), "error")
        return redirect(url_for("overview"))

    @app.post("/balance/undo")
    def undo_balance():
        try:
            ledger.update(core.undo_snapshot)
            flash("Removed the latest balance update.", "ok")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("history"))

    # ------------------------------------------------------- ledger files

    def csv_download(text: str, stem: str):
        name = f"{stem}-{today_fn():%Y-%m-%d}.csv"
        # The byte-order mark makes Excel open the file as UTF-8.
        return Response("\ufeff" + text, mimetype="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/download")
    def download():
        return csv_download(core.to_csv_text(ledger.load()), "checking-ledger")

    @app.post("/upload")
    def upload():
        text, error = read_upload()
        errors = [error] if error else []
        rows = []
        if text is not None:
            rows, errors = core.parse_ledger_csv(text)
        if errors:
            current = ledger.load()
            today = today_fn()
            periods = core.category_periods(current, today, "creditcard") if core.anchor(current) else []
            _, settled = core.split_onetime(current)
            return render_template("history.html", active="history",
                                   snapshots=core.snapshot_history(current), periods=periods,
                                   card_average=core.average_monthly(periods), settled=settled,
                                   upload_errors=errors[:20], more_errors=max(0, len(errors) - 20),
                                   backup=backup_info()), 400
        saved = ledger.replace_all(rows)
        note = f" Your previous file is saved in data/{saved}." if saved else ""
        flash(f"Replaced your ledger with {len(rows)} rows from the upload.{note}", "ok")
        return redirect(url_for("history"))

    # ---------------------------------------------------------- net worth

    def networth_page(status=200, **extra):
        book = worth.load()
        snaps = nw.series(book)
        latest = nw.latest_values(book)
        chart = None
        if snaps:
            points = []
            for i, s in enumerate(snaps):
                change = "" if i == 0 else f"{money(s.net - snaps[i - 1].net, signed=True)} from previous"
                points.append((s.date, s.net, change))
            end = max(snaps[-1].date, snaps[0].date + timedelta(days=1))
            chart = build_chart(points, snaps[0].date, end, "line")
        accounts = sorted(book.accounts, key=lambda a: (not a.active, a.kind != "asset", a.name.lower()))
        context = dict(active="networth", book=book, snaps=list(reversed(snaps)), latest=latest,
                       chart=chart, accounts=accounts, today=today_fn(),
                       account_errors={}, account_form={"name": "", "kind": "asset"},
                       upload_errors=None)
        context.update(extra)
        return render_template("networth.html", **context), status

    @app.get("/networth")
    def networth():
        return networth_page()

    @app.post("/networth/record")
    def networth_record():
        day = parse_day(request.form.get("date", ""))
        names = request.form.getlist("account")
        amounts = request.form.getlist("amount")
        if day is None:
            flash("Pick the date for these balances.", "error")
            return redirect(url_for("networth"))
        if day > today_fn():
            flash("Balances can't be recorded for a future date.", "error")
            return redirect(url_for("networth"))
        entries, bad = {}, []
        book = worth.load()
        for name, text in zip(names, amounts):
            if not text.strip():
                continue
            account = book.find(name)
            value = parse_money(text, allow_negative=True)
            if account is None:
                continue
            if value is None:
                bad.append(account.name)
            else:
                entries[account.name] = value
        if bad:
            flash(f"Enter amounts as numbers, like 1520.00 (check {', '.join(bad)}).", "error")
        elif not entries:
            flash("Fill in at least one account.", "error")
        else:
            worth.update(lambda b: nw.record(b, day, entries))
            flash(f"Saved {len(entries)} balance{'s' if len(entries) != 1 else ''} for {fmt_date(day)}.", "ok")
        return redirect(url_for("networth"))

    @app.post("/networth/accounts")
    def networth_add_account():
        form = {"name": request.form.get("name", "").strip(), "kind": request.form.get("kind", "")}
        try:
            worth.update(lambda b: nw.add_account(b, form["name"], form["kind"]))
        except ValueError as exc:
            return networth_page(400, account_errors={"name": str(exc)}, account_form=form)
        flash(f"Added {nw.clean_text(form['name'])}.", "ok")
        return redirect(url_for("networth"))

    @app.route("/networth/accounts/<path:name>", methods=["GET", "POST"])
    def networth_account(name):
        account = worth.load().find(name)
        if account is None:
            abort(404)
        error = None
        if request.method == "POST":
            new_name = request.form.get("name", "")
            try:
                worth.update(lambda b: nw.edit_account(b, account.name, new_name,
                                                       request.form.get("kind", ""),
                                                       request.form.get("status", "active")))
                flash(f"Saved {nw.clean_text(new_name)}.", "ok")
                return redirect(url_for("networth"))
            except ValueError as exc:
                error = str(exc)
        return render_template("account_form.html", active="networth", account=account, error=error)

    @app.post("/networth/accounts/<path:name>/delete")
    def networth_delete_account(name):
        try:
            worth.update(lambda b: nw.delete_account(b, name))
        except KeyError:
            abort(404)
        flash(f"Deleted {name} and its history.", "ok")
        return redirect(url_for("networth"))

    @app.post("/networth/dates/<day>/delete")
    def networth_delete_date(day):
        target = parse_day(day)
        if target is None:
            abort(404)
        worth.update(lambda b: nw.delete_date(b, target))
        flash(f"Removed the balances from {fmt_date(target)}.", "ok")
        return redirect(url_for("networth"))

    @app.get("/networth/download")
    def networth_download():
        return csv_download(nw.to_csv_text(worth.load()), "net-worth")

    @app.post("/networth/upload")
    def networth_upload():
        text, error = read_upload()
        errors = [error] if error else []
        book = None
        if text is not None:
            book, errors = nw.parse_networth_csv(text)
        if errors:
            return networth_page(400, upload_errors=errors[:20])
        saved = worth.replace_all(book)
        note = f" Your previous file is saved in data/{saved}." if saved else ""
        flash(f"Replaced your net worth file with {len(book.accounts)} accounts and {len(book.values)} balances.{note}", "ok")
        return redirect(url_for("networth"))

    return app
