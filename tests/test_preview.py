"""Keeps the browser preview (preview/) honest: same styles, no outside
connections, and the same numbers as the Python code."""
import json
import pathlib
import re
import shutil
import subprocess
from datetime import date, timedelta

import pytest

import app as webapp
import themes
import ledger_core as core
import networth as nw

ROOT = pathlib.Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "preview"
TEXT_FILES = ["index.html", "engine.js", "ui.js", "help.js", "app.css", "preview.css"]


def test_styles_and_font_are_the_apps_own():
    assert (PREVIEW / "app.css").read_bytes() == (ROOT / "static" / "app.css").read_bytes()
    assert (PREVIEW / "fonts" / "public-sans.woff2").read_bytes() == (ROOT / "static" / "fonts" / "public-sans.woff2").read_bytes()
    for icon in ("icon-180.png", "favicon-32.png"):
        assert (PREVIEW / icon).read_bytes() == (ROOT / "static" / icon).read_bytes(), icon


def test_help_text_is_the_apps_own():
    """preview/help.js is made from templates/_help_body.html by preview/sync.py."""
    namespace = {"__file__": str(PREVIEW / "sync.py"), "__name__": "sync"}
    exec(compile((PREVIEW / "sync.py").read_text(encoding="utf-8"), "sync.py", "exec"), namespace)
    assert (PREVIEW / "help.js").read_text(encoding="utf-8") == namespace["help_js"](), "run: python3 preview/sync.py"
    body = (ROOT / "templates" / "_help_body.html").read_text(encoding="utf-8")
    assert "{{" not in body and "{%" not in body        # plain HTML, so both versions show the same text


def test_preview_loads_nothing_from_outside():
    found = {}
    for name in TEXT_FILES:
        text = (PREVIEW / name).read_text(encoding="utf-8")
        if name.endswith(".css"):
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)   # license comments can't be fetched
        hits = re.findall(r"(?:https?:|wss?:)?//[a-z0-9.-]+\.[a-z]{2,}", text, re.I)
        if hits:
            found[name] = hits
    assert found == {}


def test_preview_scripts_have_no_way_to_send_or_keep_data():
    for name in ("engine.js", "ui.js", "help.js"):
        text = (PREVIEW / name).read_text(encoding="utf-8")
        for needle in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "import(",
                       "eval(", "new Function", "localStorage", "sessionStorage", "indexedDB",
                       "document.cookie", "postMessage", "window.open", ".src =", "createElement(\"script"):
            assert needle not in text, f"{needle} in preview/{name}"


def test_preview_page_has_no_inline_code_and_headers_lock_it_down():
    page = (PREVIEW / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", page) and "<style" not in page
    assert not re.search(r"\son[a-z]+=", page)
    headers = (PREVIEW / "_headers").read_text(encoding="utf-8")
    for rule in ("default-src 'none'", "script-src 'self'", "connect-src 'none'", "form-action 'none'"):
        assert rule in headers


def python_side(today, rows, book):
    c = lambda v: None if v is None else str(core.q(v))
    out = {"horizons": {}}
    origin = max(today, core.anchor(rows).date)
    planned = rows + core.forecast_rows(rows, core.anchor(rows).date, core.add_months(origin, 13))
    for key, (_, _, span) in webapp.HORIZONS.items():
        p = core.project(planned, today, span)
        pts = [(q.date, q.balance, ", ".join(e.description + (" (estimate)" if e.estimated else "") for e in q.events)[:70]) for q in p.points]
        out["horizons"][key] = {
            "origin": p.origin.isoformat(), "end": p.end.isoformat(), "origin_balance": c(p.origin_balance),
            "end_balance": c(p.end_balance), "low": [p.low.date.isoformat(), c(p.low.balance)],
            "points": [[q.date.isoformat(), c(q.balance), [[e.description, e.category, c(e.amount), e.recurring, e.estimated] for e in q.events]] for q in p.points],
            "chart": {k: v for k, v in webapp.build_chart(pts, p.origin, p.end, "step").items() if k not in ("mode", "ghost_line")},
        }
    flow, net = core.cash_flow(planned, today)
    out["flow"] = [[[k, l, c(y), c(m)] for k, l, y, m in flow], c(net), c(net / 12)]
    ref = max(today, core.anchor(rows).date)
    out["today"] = [c(core.start_of_day(planned, ref)), c(core.end_of_day(planned, ref))]
    out["cards"] = []
    for card in core.cards(rows):
        n = core.next_payment(rows, card, today)
        out["cards"].append([card.id, card.description, card.close_day, card.due_day, card.estimate, c(card.amount),
                             n.due.isoformat(), n.close.isoformat(), c(n.entered.amount) if n.entered else None,
                             [c(n.estimate.amount), n.estimate.basis, n.estimate.count] if n.estimate else None,
                             [d.isoformat() for d in core.open_due_dates(rows, card, today)]])
    out["pending"] = [[p.card.id, p.due.isoformat(), p.close.isoformat()] for p in core.pending_statements(rows, today)]
    out["pays"] = []
    for pay in core.pays(rows):
        est, n = core.pay_estimate(rows, pay), core.next_paycheck(rows, pay, today)
        out["pays"].append([pay.id, pay.description, pay.date.isoformat(), pay.frequency, core.plain(pay.hours), c(pay.rate),
                            core.plain(pay.percent), c(est.amount), c(est.base), core.plain(est.hours), float(est.kept), est.count,
                            [n.payday.isoformat(), c(n.entered.amount) if n.entered else None] if n else None,
                            [d.isoformat() for d in core.open_paydays(rows, pay, today)]])
    out["pending_pay"] = [[p.pay.id, p.payday.isoformat()] for p in core.pending_paychecks(rows, today)]
    if today > core.anchor(rows).date:
        after, snap = core.take_snapshot(rows, today, today)
        out["snapshot"] = [c(snap.amount), sorted([r.date.isoformat(), r.description, c(r.amount), r.card, r.pay]
                                                   for r in after if r.estimate == core.ASSUMED)]
    trial = core.Row("whatif", "onetime", origin + timedelta(days=20), "What-if", "bill", core.Decimal("-9000.00"), what_if=True)
    span = webapp.HORIZONS["3m"][2]
    wp, pp = core.project(planned + [trial], today, span), core.project(planned, today, span)
    chart = webapp.build_chart([(q.date, q.balance, "") for q in wp.points], wp.origin, wp.end, "step",
                               [(q.date, q.balance, "") for q in pp.points])
    out["what_if"] = {"low": [wp.low.date.isoformat(), c(wp.low.balance)], "plain_low": [pp.low.date.isoformat(), c(pp.low.balance)],
                      "line": chart["line"], "ghost_line": chart["ghost_line"], "grid": chart["grid"], "y_labels": chart["y_labels"]}
    out["snapshots"] = [[s.row.date.isoformat(), c(s.row.amount), c(s.change), c(s.expected), c(s.variance)] for s in core.snapshot_history(rows)]
    periods = core.category_periods(rows, today, "creditcard")
    out["periods"] = [[p.start.isoformat(), p.end.isoformat(), p.days, p.count, c(p.spent), c(p.monthly), p.open] for p in periods]
    out["card_average"] = c(core.average_monthly(periods))
    up, settled = core.split_onetime(rows)
    out["upcoming"], out["settled"] = [r.id for r in up], [r.id for r in settled]
    out["nexts"] = {r.id: (lambda n: n.isoformat() if n else None)(core.next_occurrence(r, today)) for r in rows if r.type == "recurring"}
    out["ledger_csv"] = core.to_csv_text(rows)
    snaps = nw.series(book)
    out["series"] = [[s.date.isoformat(), c(s.assets), c(s.debts), c(s.net)] for s in snaps]
    out["latest"] = {k: [v.date.isoformat(), c(v.amount)] for k, v in sorted(nw.latest_values(book).items())}
    pts = [(s.date, s.net, "" if i == 0 else f"{webapp.money(s.net - snaps[i - 1].net, signed=True)} from previous") for i, s in enumerate(snaps)]
    end = max(snaps[-1].date, snaps[0].date + timedelta(days=1))
    out["nw_chart"] = {k: v for k, v in webapp.build_chart(pts, snaps[0].date, end, "line").items() if k not in ("mode", "ghost_line")}
    out["networth_csv"] = nw.to_csv_text(book)
    out["themes"] = [[key, name, desc] for key, (name, desc, _, _) in themes.THEMES.items()]
    out["modes"] = themes.MODES
    return out


def differences(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b)) for d in differences(a.get(k, "<missing>"), b.get(k, "<missing>"), f"{path}.{k}")]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in differences(x, y, f"{path}[{i}]")]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        # Dot positions are rounded to 3 places; the two languages may break a tie differently.
        return [] if abs(a - b) <= 0.0011 else [(path, a, b)]
    return [] if a == b else [(path, a, b)]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node isn't installed")
@pytest.mark.parametrize("day", ["2026-11-15", "2026-01-03", "2026-07-01", "2026-10-20", "2027-02-28",
                                 "2028-02-29", "2026-12-31", "2027-05-17", "2026-03-31"])
def test_preview_math_matches_python(day, tmp_path):
    """The preview builds its sample ledger for `day`; both sides then work
    from the same two CSV files and must agree on every number shown."""
    subprocess.run(["node", str(ROOT / "tests" / "preview_dump.js"), day, str(tmp_path)], check=True, timeout=60)
    rows, errors = core.parse_ledger_csv((tmp_path / "ledger.csv").read_text(encoding="utf-8"))
    book, errors2 = nw.parse_networth_csv((tmp_path / "networth.csv").read_text(encoding="utf-8"))
    assert errors == [] and errors2 == []
    js = json.loads((tmp_path / "js.json").read_text(encoding="utf-8"))
    assert differences(js, python_side(date.fromisoformat(day), rows, book)) == []
