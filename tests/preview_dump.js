// Dump what the JS engine computes for the sample data on a given day.
const E = require("../preview/engine.js");
const fs = require("fs");
// node preview_dump.js DATE OUTDIR [ledger.csv]   (a ledger file replaces the built-in sample)
const [todayIso, outDir, ledgerFile] = process.argv.slice(2);
const today = E.parseISO(todayIso);
const s = E.sampleData(today);
if (ledgerFile) {
  const given = E.parseLedgerCsv(fs.readFileSync(ledgerFile, "utf8"));
  if (given.errors.length) throw new Error("ledger did not parse: " + given.errors.join(" "));
  s.rows = given.rows;
}
fs.writeFileSync(outDir + "/ledger.csv", E.toCsvText(s.rows));
fs.writeFileSync(outDir + "/networth.csv", E.networthCsvText(s.book));
// Re-read through the strict parser so both sides start from the same file.
const rows = E.parseLedgerCsv(E.toCsvText(s.rows));
const book = E.parseNetworthCsv(E.networthCsvText(s.book));
if (rows.errors.length || book.errors.length) throw new Error("sample did not parse: " + rows.errors.concat(book.errors).join(" "));
const R = rows.rows, B = book.book, out = { horizons: {} };
// Overview projects the ledger plus estimated card payments.
const origin = Math.max(today, E.anchor(R).date);
const planned = R.concat(E.forecastRows(R, E.anchor(R).date, E.addMonths(origin, 13)));
const c = (cents) => (cents === null ? null : (cents < 0 ? "-" : "") + E.fixed2(cents));
for (const key of Object.keys(E.HORIZONS)) {
  const p = E.project(planned, today, E.HORIZONS[key][2]);
  const pts = p.points.map((q) => ({ date: q.date, cents: q.balance, label: q.events.map((e) => e.description).join(", ").slice(0, 70) }));
  const ch = E.buildChart(pts, p.origin, p.end, "step");
  out.horizons[key] = {
    origin: E.iso(p.origin), end: E.iso(p.end), origin_balance: c(p.originBalance), end_balance: c(p.endBalance),
    low: [E.iso(p.low.date), c(p.low.balance)],
    points: p.points.map((q) => [E.iso(q.date), c(q.balance), q.events.map((e) => [e.description, e.category, c(e.amount), e.recurring, e.estimated])]),
    chart: { line: ch.line, area: ch.area, grid: ch.grid, zero: ch.zero, y_labels: ch.yLabels, x_labels: ch.xLabels, points: ch.points, low_index: ch.lowIndex, origin: ch.origin, span: ch.span },
  };
}
const f = E.cashFlow(planned, today);
out.flow = [f.lines.map((l) => [l.key, l.label, c(l.yearly), c(l.monthly)]), c(f.net), c(E.divRound(f.net, 12))];
const ref = Math.max(today, E.anchor(R).date);
out.today = [c(E.startOfDay(planned, ref)), c(E.endOfDay(planned, ref))];
out.cards = E.cards(R).map((card) => {
  const n = E.nextPayment(R, card, today);
  return [card.id, card.description, card.closeDay, card.dueDay, card.estimate, c(card.amount), E.iso(n.due), E.iso(n.close),
          n.entered ? c(n.entered.amount) : null, n.estimate ? [c(n.estimate.cents), n.estimate.basis, n.estimate.count] : null,
          E.openDueDates(R, card, today).map(E.iso)];
});
out.pending = E.pendingStatements(R, today).map((p) => [p.card.id, E.iso(p.due), E.iso(p.close)]);
out.pays = E.pays(R).map((pay) => {
  const est = E.payEstimate(R, pay), n = E.nextPaycheck(R, pay, today);
  return [pay.id, pay.description, E.iso(pay.date), pay.frequency, E.plain(pay.hours), c(pay.rate), E.plain(pay.percent),
          c(est.cents), c(est.base), E.plain(est.hours), est.kept, est.count,
          n ? [E.iso(n.payday), n.entered ? c(n.entered.amount) : null] : null, E.openPaydays(R, pay, today).map(E.iso)];
});
out.pending_pay = E.pendingPaychecks(R, today).map((p) => [p.pay.id, E.iso(p.payday)]);
// Updating the balance today saves the estimates dated before it.
if (today > E.anchor(R).date) {
  const snap = E.takeSnapshot(R, today, today, null);
  out.snapshot = [c(snap.row.amount), snap.rows.filter((r) => r.estimate === E.ASSUMED)
    .map((r) => [E.iso(r.date), r.description, c(r.amount), r.card, r.pay]).sort()];
}
// A what-if: 9,000 out, 20 days from now, on the 3-month chart.
const trial = E.Row("whatif", "onetime", origin + 20, "What-if", "bill", -900000); trial.whatIf = true;
const wp = E.project(planned.concat([trial]), today, E.HORIZONS["3m"][2]), pp = E.project(planned, today, E.HORIZONS["3m"][2]);
const wch = E.buildChart(wp.points.map((q) => ({ date: q.date, cents: q.balance, label: "" })), wp.origin, wp.end, "step",
                         pp.points.map((q) => ({ date: q.date, cents: q.balance, label: "" })));
out.what_if = { low: [E.iso(wp.low.date), c(wp.low.balance)], plain_low: [E.iso(pp.low.date), c(pp.low.balance)],
                line: wch.line, ghost_line: wch.ghostLine, grid: wch.grid, y_labels: wch.yLabels };
out.snapshots = E.snapshotHistory(R).map((x) => [E.iso(x.row.date), c(x.row.amount), c(x.change), c(x.expected), c(x.variance)]);
const periods = E.categoryPeriods(R, today, "creditcard");
out.periods = periods.map((p) => [E.iso(p.start), E.iso(p.end), p.days, p.count, c(p.spent), c(p.monthly), p.open]);
out.card_average = c(E.averageMonthly(periods));
const sp = E.splitOnetime(R);
out.upcoming = sp.upcoming.map((r) => r.id); out.settled = sp.settled.map((r) => r.id);
out.nexts = {}; R.filter((r) => r.type === "recurring").forEach((r) => { const n = E.nextOccurrence(r, today); out.nexts[r.id] = n === null ? null : E.iso(n); });
out.ledger_csv = E.toCsvText(R);
const snaps = E.series(B);
out.series = snaps.map((x) => [E.iso(x.date), c(x.assets), c(x.debts), c(x.net)]);
const lv = E.latestValues(B); out.latest = {}; Object.keys(lv).sort().forEach((k) => { out.latest[k] = [E.iso(lv[k].date), c(lv[k].amount)]; });
const npts = snaps.map((x, i) => ({ date: x.date, cents: x.net, label: i === 0 ? "" : E.money(x.net - snaps[i - 1].net, true) + " from previous" }));
const nch = E.buildChart(npts, snaps[0].date, Math.max(snaps[snaps.length - 1].date, snaps[0].date + 1), "line");
out.nw_chart = { line: nch.line, area: nch.area, grid: nch.grid, zero: nch.zero, y_labels: nch.yLabels, x_labels: nch.xLabels, points: nch.points, low_index: nch.lowIndex, origin: nch.origin, span: nch.span };
out.networth_csv = E.networthCsvText(B);
out.themes = E.THEMES; out.modes = E.MODES;
fs.writeFileSync(outDir + "/js.json", JSON.stringify(out));
