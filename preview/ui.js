// Preview UI: the app's Jinja templates re-rendered in the browser on top of
// Engine. Markup and class names are the app's own, so its stylesheet applies.
(function () {
  "use strict";
  var E = Engine, C = E.CATEGORIES, F = E.FREQUENCIES, K = E.KINDS;
  var root = document.getElementById("app");
  var TABS = [
    ["overview", "Overview", "M3 13h4l3-8 4 14 3-6h4"],
    ["transactions", "Transactions", "M4 6h16M4 12h16M4 18h10"],
    ["networth", "Net worth", "M5 20V11M12 20V5M19 20v-6M3 20h18"],
    ["history", "History", "M12 7v5l3 2M21 12a9 9 0 1 1-9-9 9 9 0 0 1 9 9Z"]
  ];
  var HASH = { overview: "overview", transactions: "transactions", networth: "net-worth", history: "history" };
  var PASSWORD = "demo";
  var state = { today: E.todayNumber(), rows: [], book: { accounts: [], values: [] }, horizon: "1y",
                authed: true, view: { name: "overview" }, flash: [], whatIf: null,
                // The starting look comes from <html data-theme data-mode> in index.html.
                theme: document.documentElement.getAttribute("data-theme") || "sage",
                mode: document.documentElement.getAttribute("data-mode") || "auto" };
  var chartData = null;

  function loadSample() {
    var s = E.sampleData(state.today);
    state.rows = s.rows; state.book = s.book; state.whatIf = null;
  }

  // ---------------------------------------------------------------- helpers
  function helpLink(anchor, cls) {
    return '<a href="#help-' + anchor + '" data-help="help-' + anchor + '" class="' + (cls || "text-sm font-semibold text-ledger") + '">How it works</a>';
  }
  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function amount(cents) {
    return '<span class="whitespace-nowrap font-semibold ' + (cents > 0 ? "amount-in" : "amount-out") + '">' + E.money(cents, true) + "</span>";
  }
  var DOTS = { income: "bg-gain", bill: "bg-debit", creditcard: "bg-card", transfer: "bg-muted", investment: "bg-amber-500" };
  function dot(cat) {
    return '<span class="inline-block h-2 w-2 shrink-0 rounded-full ' + (DOTS[cat] || "bg-muted") + '" aria-hidden="true"></span>';
  }
  function fieldError(errors, key) {
    return errors && errors[key] ? '<p class="field-error" id="' + key + '-error">' + esc(errors[key]) + "</p>" : "";
  }
  function flash(text, kind) { state.flash.push({ kind: kind || "ok", text: text }); }
  function signedFixed(cents) { return (cents < 0 ? "-" : "") + E.fixed2(cents); }

  function chartBox(chart, aria) {
    chartData = chart;
    var h = '<div class="mt-5 flex gap-2">' +
      '<div class="-my-1.5 flex h-44 shrink-0 flex-col justify-between text-right text-[11px] text-muted sm:h-56" aria-hidden="true">' +
      chart.yLabels.map(function (l) { return "<span>" + l + "</span>"; }).join("") + "</div>" +
      '<div class="min-w-0 flex-1">' +
      '<div class="relative h-44 cursor-crosshair touch-pan-y select-none sm:h-56" data-chart role="img" aria-label="' + esc(aria) + '">' +
      '<svg viewBox="0 0 1000 300" preserveAspectRatio="none" class="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">' +
      chart.grid.map(function (gy) { return '<line x1="0" x2="1000" y1="' + gy + '" y2="' + gy + '" class="stroke-rule" stroke-width="1" vector-effect="non-scaling-stroke"/>'; }).join("") +
      (chart.zero !== null ? '<line x1="0" x2="1000" y1="' + chart.zero + '" y2="' + chart.zero + '" class="stroke-debit" stroke-width="1.5" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"/>' : "") +
      '<path d="' + chart.area + '" class="fill-ledger/10"/>' +
      (chart.ghostLine ? '<path d="' + chart.ghostLine + '" class="fill-none stroke-muted" stroke-width="1.5" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"/>' : "") +
      '<path d="' + chart.line + '" class="fill-none stroke-ledger" stroke-width="2.25" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>' +
      "</svg>";
    if (chart.mode === "line") {
      h += chart.points.map(function (p) {
        return '<div data-mark data-x="' + p.x + '" data-y="' + p.y + '" class="pointer-events-none absolute hidden h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ledger ring-2 ring-paper"></div>';
      }).join("");
    }
    h += '<div data-low-dot class="pointer-events-none absolute hidden h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-debit ring-2 ring-paper"></div>' +
      '<div data-cursor class="pointer-events-none absolute inset-y-0 hidden w-px bg-ink/40"></div>' +
      '<div data-dot class="pointer-events-none absolute hidden h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ledger ring-[3px] ring-paper"></div>' +
      "</div>" +
      '<div class="mt-2 flex justify-between text-[11px] text-muted" aria-hidden="true">' +
      chart.xLabels.map(function (l, i) { return '<span class="' + (i % 2 === 1 ? "hidden sm:inline" : "") + '">' + l + "</span>"; }).join("") +
      "</div></div></div>";
    return h;
  }

  function uploadForm(action, label, errors, more) {
    var h = '<form data-action="' + action + '" class="mt-3 space-y-3" data-confirm="This replaces everything with the file you picked. Your current file is backed up first. Continue?">' +
      '<label class="label" for="upload-' + action + '">' + label + "</label>" +
      '<input class="block w-full text-sm text-muted file:mr-3 file:min-h-[44px] file:rounded-[10px] file:border-0 file:bg-ink file:px-4 file:text-sm file:font-semibold file:text-paper" type="file" id="upload-' + action + '" name="file" accept=".csv,text/csv">' +
      '<button class="btn-quiet w-full sm:w-auto">Upload and replace</button>';
    if (errors && errors.length) {
      h += '<div role="alert" class="rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">' +
        '<p class="font-semibold">Nothing was changed. Fix these in the file and upload it again:</p>' +
        '<ul class="mt-2 list-disc space-y-1 pl-5">' + errors.map(function (e) { return "<li>" + esc(e) + "</li>"; }).join("") + "</ul>" +
        (more ? '<p class="mt-2">And ' + more + " more.</p>" : "") + "</div>";
    }
    return h + "</form>";
  }

  function choice(name, pairs, current, legendClass) {
    return pairs.map(function (p) {
      return '<label class="flex min-h-[48px] cursor-pointer items-center justify-center rounded-[10px] border border-rule bg-surface text-[15px] font-semibold text-muted has-[:checked]:border-transparent has-[:checked]:ring-2 ' +
        (p[2] === "debit" ? "has-[:checked]:text-debit has-[:checked]:ring-debit" : p[2] === "accent" ? "has-[:checked]:text-ledger has-[:checked]:ring-ledger" : "has-[:checked]:text-gain has-[:checked]:ring-gain") +
        ' has-[:focus-visible]:outline has-[:focus-visible]:outline-2">' +
        '<input type="radio" name="' + name + '" value="' + p[0] + '" class="sr-only"' + (current === p[0] ? " checked" : "") + ">" + p[1] + "</label>";
    }).join("");
  }

  // ------------------------------------------------------------------ pages
  function pageLogin(v) {
    return '<div class="mx-auto mt-10 max-w-sm">' +
      '<h1 class="text-2xl font-bold tracking-tight">Unlock your ledger</h1>' +
      '<form data-action="login" class="mt-6 space-y-4"><div>' +
      '<label class="label" for="password">Password</label>' +
      '<input class="field" type="password" id="password" name="password" autocomplete="off"' + (v.error ? ' aria-invalid="true" aria-describedby="pw-error"' : "") + ">" +
      (v.error ? '<p class="field-error" id="pw-error">' + esc(v.error) + "</p>" : "") +
      '</div><button class="btn-primary w-full">Unlock</button></form>' +
      '<p class="hint mt-4">In this preview the password is <b>demo</b>. In the real app it\'s the APP_PASSWORD you set on your server.</p></div>';
  }

  function moneyField(id, name, value, placeholder, extra) {
    return '<div class="relative"><span class="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-muted">$</span>' +
      '<input class="field pl-7 ' + (extra || "") + '" id="' + id + '" name="' + name + '" value="' + esc(value) + '" inputmode="decimal" autocomplete="off" placeholder="' + placeholder + '"></div>';
  }

  function pageSetup(v) {
    var form = v.form || { balance: "", date: E.iso(state.today), pay: "", pay_date: "" }, errors = v.errors || {};
    return '<h1 class="text-3xl font-bold tracking-tight">Start with your checking balance</h1>' +
      '<p class="hint mt-2 text-base">Everything projects forward from this number. You can add bills and card payments right after.</p>' +
      '<form data-action="setup" class="mt-6 space-y-5" novalidate>' +
      '<div class="grid gap-5 sm:grid-cols-2"><div>' +
      '<label class="label" for="balance">Current balance</label>' + moneyField("balance", "balance", form.balance, "3200.00", "text-lg font-semibold") + fieldError(errors, "balance") +
      '</div><div><label class="label" for="date">As of</label>' +
      '<input class="field" type="date" id="date" name="date" value="' + esc(form.date) + '">' + fieldError(errors, "date") + "</div></div>" +
      '<fieldset class="panel space-y-5 p-4"><legend class="sr-only">Paycheck</legend>' +
      '<div><p class="section-title">Paycheck</p><p class="hint">Optional. Repeats every two weeks from your next payday.</p></div>' +
      '<div class="grid gap-5 sm:grid-cols-2"><div>' +
      '<label class="label" for="pay">Take-home pay</label>' + moneyField("pay", "pay", form.pay, "2808.99") + fieldError(errors, "pay") +
      '</div><div><label class="label" for="pay_date">Next payday</label>' +
      '<input class="field" type="date" id="pay_date" name="pay_date" value="' + esc(form.pay_date) + '">' + fieldError(errors, "pay_date") +
      '</div></div></fieldset><button class="btn-primary w-full">Start ledger</button></form>';
  }

  function ordinal(n) { var t = n % 100; return n + (t >= 11 && t <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th"); }

  function pageOverview(v) {
    var real = state.rows, today = state.today, base = E.anchor(real), from = Math.max(today, base.date);
    // Card payments and hourly paychecks
    // from the latest balance onward: what was entered, or an estimate where nothing has been.
    var planned = real.concat(E.forecastRows(real, base.date, E.addMonths(from, 13)));
    var rows = planned, w = state.whatIf;
    if (w) {
      var trial = E.Row("whatif", "onetime", w.date, "What-if", w.cents > 0 ? "income" : "bill", w.cents);
      trial.whatIf = true;
      rows = planned.concat([trial]);
    }
    var H = E.HORIZONS, proj = E.project(rows, today, H[state.horizon][2]);
    var plain = w ? E.project(planned, today, H[state.horizon][2]) : null;
    var points = proj.points.map(function (p) {
      return { date: p.date, cents: p.balance, label: p.events.map(function (e) { return e.description; }).join(", ").slice(0, 70) };
    });
    var ghost = plain ? plain.points.map(function (p) { return { date: p.date, cents: p.balance, label: "" }; }) : null;
    var chart = E.buildChart(points, proj.origin, proj.end, "step", ghost);
    var flow = E.cashFlow(planned, today);
    var soon = proj.points.slice(1).filter(function (p) { return p.date < proj.origin + 30; });
    var ref = Math.max(today, base.date), todayEnd = E.endOfDay(rows, ref), todayStart = E.startOfDay(rows, ref);
    var canUpdate = today > base.date;

    var h = E.pendingPaychecks(real, today).map(function (p) {
      return '<a href="#transactions" data-pay="' + esc(p.pay.id) + '" class="mb-4 block rounded-xl bg-card/10 px-4 py-3 text-sm text-card"><span class="font-semibold">' + esc(p.pay.description) + " from " + E.fmtDate(p.payday, false) +
        " isn\'t entered yet.</span> Enter your take-home to replace the estimate.</a>";
    }).join("") + E.pendingStatements(real, today).map(function (p) {
      return '<a href="#transactions" data-card="' + esc(p.card.id) + '" class="mb-4 block rounded-xl bg-card/10 px-4 py-3 text-sm text-card"><span class="font-semibold">' + esc(p.card.description) + " statement closed " + E.fmtDate(p.close, false) +
        ".</span> Enter the amount due " + E.fmtDate(p.due, false) + " to replace the estimate.</a>";
    }).join("");
    h += '<section data-chart-root>' +
      '<div class="flex flex-col-reverse gap-4 sm:flex-row sm:items-center sm:justify-between sm:gap-3">' +
      '<p class="text-sm font-medium text-muted" data-readout-d>Balance on ' + E.fmtDate(proj.end) + "</p>" +
      '<div class="grid grid-cols-5 rounded-full bg-surface p-0.5 ring-1 ring-rule sm:flex" role="group" aria-label="How far ahead">' +
      Object.keys(H).map(function (key) {
        return '<a href="#overview" data-horizon="' + key + '" class="rounded-full px-2.5 py-1.5 text-center text-[13px] font-semibold sm:px-3 ' +
          (key === state.horizon ? "bg-ink text-paper" : "text-muted") + '"' + (key === state.horizon ? ' aria-current="true"' : "") + ">" +
          H[key][0] + '<span class="sr-only"> ' + H[key][1] + "</span></a>";
      }).join("") + "</div></div>" +
      '<p class="mt-1 text-[44px] font-bold leading-none tracking-[-0.03em] sm:text-6xl ' + (proj.endBalance < 0 ? "text-debit" : "") + '" data-readout-b>' + E.money(proj.endBalance) + "</p>" +
      '<p class="mt-2 min-h-[1.25rem] text-sm text-muted" data-readout-l>' + E.money(proj.endBalance - proj.originBalance, true) + " over " + H[state.horizon][1] + "</p>" +
      chartBox(chart, "Projected balance from " + E.fmtDate(proj.origin) + " to " + E.fmtDate(proj.end) + ", lowest " + E.money(proj.low.balance) + " on " + E.fmtDate(proj.low.date)) +
      '<dl class="mt-5 grid grid-cols-2 divide-x divide-rule rounded-2xl bg-surface ring-1 ring-rule">' +
      '<div class="px-4 py-3"><dt class="text-[13px] text-muted">End of today, estimated</dt><dd class="mt-0.5 text-lg font-semibold">' + E.money(todayEnd) + "</dd></div>" +
      '<div class="px-4 py-3"><dt class="text-[13px] text-muted">Lowest point</dt>' +
      '<dd class="mt-0.5 text-lg font-semibold ' + (proj.low.balance < 0 ? "text-debit" : "") + '">' + E.money(proj.low.balance) + "</dd>" +
      '<dd class="text-[13px] text-muted">' + E.fmtDate(proj.low.date) + "</dd></div></dl>" +
      (proj.low.balance < 0 ? '<p class="mt-3 rounded-xl bg-debit/10 px-4 py-3 text-sm text-debit">Your balance is projected to go below zero on ' + E.fmtDate(proj.low.date) + ". Move a payment date or add a transfer before then.</p>" : "") +
      "</section>";

    h += '<section class="mt-9"><div class="flex items-baseline justify-between"><h2 class="section-title">What if</h2>' + helpLink("what-if") + "</div>";
    if (w) {
      h += '<div class="panel mt-3 p-4"><p class="text-sm"><span class="font-semibold">Trying ' + E.money(w.cents, true) + " on " + E.fmtDate(w.date) + ".</span> " +
        "Your lowest point becomes " + E.money(proj.low.balance) + " on " + E.fmtDate(proj.low.date) + ". Without it: " + E.money(plain.low.balance) + " on " + E.fmtDate(plain.low.date) +
        '.</p><p class="hint mt-1">The dashed line is your projection without it. Nothing has been saved.</p>' +
        '<div class="mt-3 grid grid-cols-2 gap-3"><a href="#overview" data-whatif="keep" class="btn-primary">Keep it</a><a href="#overview" data-whatif="clear" class="btn-quiet">Clear</a></div></div>';
    } else {
      var wf = (v && v.whatIfForm) || { direction: "out", amount: "", date: E.iso(from + 14) };
      h += '<p class="hint mt-1">Try a one-off amount and watch the chart change. Nothing is saved unless you keep it.</p>' +
        '<form data-action="whatif" class="panel mt-3 p-4" novalidate><div class="grid items-end gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">' +
        '<div><label class="label" for="wi-dir">Direction</label><select class="field" id="wi-dir" name="direction"><option value="out"' + (wf.direction === "out" ? " selected" : "") + '>Money out</option><option value="in"' + (wf.direction === "in" ? " selected" : "") + ">Money in</option></select></div>" +
        '<div><label class="label" for="wi-amount">Amount</label>' + moneyField("wi-amount", "amount", wf.amount, "1500.00") + "</div>" +
        '<div><label class="label" for="wi-date">Date</label><input class="field" type="date" id="wi-date" name="date" value="' + esc(wf.date) + '" min="' + E.iso(from) + '"></div>' +
        '<button class="btn-quiet">Try it</button></div>' +
        (v && v.whatIfError ? '<p class="field-error">' + esc(v.whatIfError) + "</p>" : "") + "</form>";
    }
    h += "</section>";

    h += '<section class="mt-9"><div class="mb-3 flex items-baseline justify-between"><h2 class="section-title">Next 30 days</h2>' +
      '<a href="#transactions" data-new="onetime" class="text-sm font-semibold text-ledger">Add transaction</a></div>';
    if (soon.length) {
      h += '<ol class="panel divide-y divide-rule">';
      soon.forEach(function (point) {
        point.events.forEach(function (e, i) {
          var p = E.parts(e.date);
          h += '<li class="flex items-center gap-3 px-4 py-3">' +
            '<div class="w-11 shrink-0 text-center leading-tight"><div class="text-[11px] font-medium text-muted">' + E.MONTHS[p.m - 1] + '</div><div class="text-lg font-semibold">' + p.d + "</div></div>" +
            '<div class="min-w-0 flex-1"><div class="truncate font-medium">' + esc(e.description) + "</div>" +
            '<div class="flex items-center gap-1.5 text-[13px] text-muted">' + dot(e.category) + C[e.category] + (e.recurring ? ", repeats" : "") +
            (e.estimated ? '<span class="tag">estimate</span>' : e.whatIf ? '<span class="tag">what-if</span>' : "") + "</div></div>" +
            '<div class="text-right">' + amount(e.amount) +
            (i === point.events.length - 1 ? '<div class="text-[12px] text-muted">' + E.money(point.balance) + " after</div>" : "") + "</div></li>";
        });
      });
      h += "</ol>";
    } else {
      h += '<p class="panel px-4 py-5 hint">Nothing scheduled in the next 30 days. Add your paycheck, bills, and card payments so the projection has something to work with.</p>';
    }
    h += "</section>";

    h += '<section class="mt-9"><h2 class="section-title">Update your balance</h2>' +
      '<p class="hint mt-1">Record what your bank shows before anything dated that day comes out. Transactions dated that day still count on top of it, and anything dated earlier moves to History.</p>';
    if (canUpdate) {
      h += '<form data-action="balance" class="panel mt-3 grid gap-4 p-4 sm:grid-cols-2">' +
        '<div><label class="label" for="bal-date">Balance date</label>' +
        '<input class="field" type="date" id="bal-date" name="date" value="' + E.iso(today) + '" min="' + E.iso(base.date + 1) + '" max="' + E.iso(today) + '"></div>' +
        '<div><label class="label" for="bal-amount">Balance from your bank</label>' +
        '<input class="field" id="bal-amount" name="balance" inputmode="decimal" autocomplete="off" placeholder="' + signedFixed(todayStart) + '" aria-describedby="bal-help"></div>' +
        '<p id="bal-help" class="hint sm:col-span-2">Leave it blank to use the calculated balance for the start of that day (' + E.money(todayStart) + " today).</p>" +
        '<button class="btn-primary sm:col-span-2">Save balance</button></form>';
    } else {
      h += '<p class="panel mt-3 px-4 py-4 hint">Last updated ' + E.fmtDate(base.date) + " at " + E.money(base.amount) + ". You can record a new balance starting tomorrow.</p>";
    }
    h += "</section>";

    h += '<section class="mt-9"><h2 class="section-title">Next 12 months by category</h2>';
    if (flow.lines.length) {
      h += '<table class="panel mt-3 w-full text-[15px]"><thead class="sr-only"><tr><th>Category</th><th>Per month</th><th>12 months</th></tr></thead><tbody class="divide-y divide-rule">';
      flow.lines.forEach(function (l) {
        h += '<tr><td class="px-4 py-3"><span class="flex items-center gap-2">' + dot(l.key) + l.label + "</span></td>" +
          '<td class="px-2 py-3 text-right">' + amount(l.monthly) + '<span class="text-[13px] text-muted">/mo</span></td>' +
          '<td class="hidden px-4 py-3 text-right text-muted sm:table-cell">' + E.money(l.yearly, true) + "/yr</td></tr>";
      });
      h += '<tr class="bg-paper/60"><td class="px-4 py-3 font-semibold">Net</td>' +
        '<td class="px-2 py-3 text-right">' + amount(E.divRound(flow.net, 12)) + '<span class="text-[13px] text-muted">/mo</span></td>' +
        '<td class="hidden px-4 py-3 text-right font-semibold sm:table-cell">' + E.money(flow.net, true) + "/yr</td></tr></tbody></table>";
    } else {
      h += '<p class="panel mt-3 px-4 py-5 hint">Add recurring transactions to see where your money goes each month.</p>';
    }
    return h + "</section>";
  }

  function pageTransactions() {
    var rows = state.rows, today = state.today;
    var upcoming = E.splitOnetime(rows).upcoming;
    var recurring = rows.filter(function (r) { return r.type === "recurring"; }).sort(function (a, b) {
      var ka = [E.isActive(a) ? 0 : 1, a.amount > 0 ? 1 : 0, a.description.toLowerCase()];
      var kb = [E.isActive(b) ? 0 : 1, b.amount > 0 ? 1 : 0, b.description.toLowerCase()];
      for (var i = 0; i < 3; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
      return 0;
    });
    function item(r, detail) {
      return '<li><a href="#transactions" data-edit="' + esc(r.id) + '" class="row-link ' + (E.isActive(r) ? "" : "opacity-50") + '">' +
        '<div class="min-w-0 flex-1"><div class="truncate font-medium">' + esc(r.description) + "</div>" +
        '<div class="flex items-center gap-1.5 text-[13px] text-muted">' + dot(r.category) + detail + (r.estimate === E.ASSUMED ? '<span class="tag">estimate</span>' : "") + "</div></div>" + amount(r.amount) + "</a></li>";
    }
    var byName = function (a, b) {
      var ka = [E.isActive(a) ? 0 : 1, a.description.toLowerCase(), a.id], kb = [E.isActive(b) ? 0 : 1, b.description.toLowerCase(), b.id];
      for (var i = 0; i < 3; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
      return 0;
    };
    var jobs = E.pays(rows).sort(byName);
    var h = '<section><div class="mb-3 flex items-baseline justify-between"><h1 class="section-title text-lg">Hourly pay</h1>' +
      '<a href="#transactions" data-pay="new" class="text-sm font-semibold text-ledger">Add hourly pay</a></div>' +
      '<p class="hint -mt-2 mb-3">For paychecks that change. Give your rate and usual hours, enter each paycheck when it arrives, and every future payday gets an estimate. ' + helpLink("pay", "font-semibold text-ledger") + "</p>";
    if (jobs.length) {
      h += '<ul class="panel divide-y divide-rule">' + jobs.map(function (pay) {
        var n = E.nextPaycheck(rows, pay, today), paused = !E.isActive(pay);
        var right = !n ? "" : '<div class="text-right">' + (n.entered ? amount(n.entered.amount) + '<div class="text-[12px] text-muted">' + E.fmtDate(n.payday, false) + ", entered</div>"
          : amount(n.estimate.cents) + '<div class="text-[12px] text-muted">' + E.fmtDate(n.payday, false) + ", estimate</div>") + "</div>";
        return '<li><a href="#transactions" data-pay="' + esc(pay.id) + '" class="row-link ' + (paused ? "opacity-50" : "") + '">' +
          '<div class="min-w-0 flex-1"><div class="truncate font-medium">' + esc(pay.description) + "</div>" +
          '<div class="flex items-center gap-1.5 text-[13px] text-muted">' + dot("income") + E.plain(pay.hours) + " hours a week at " + E.money(pay.rate) + ", " + F[pay.frequency].toLowerCase() + (paused ? ", paused" : "") + "</div></div>" +
          right + "</a></li>";
      }).join("") + "</ul>";
    } else {
      h += '<a href="#transactions" data-pay="new" class="panel block px-4 py-5 text-sm text-muted">No hourly pay yet. <span class="font-semibold text-ledger">Add it if your paychecks vary</span></a>';
    }
    h += '</section><section class="mt-9"><div class="mb-3 flex items-baseline justify-between"><h2 class="section-title text-lg">Credit cards</h2>' +
      '<a href="#transactions" data-card="new" class="text-sm font-semibold text-ledger">Add card</a></div>' +
      '<p class="hint -mt-2 mb-3">Set each card\'s closing day and due day once. Every future due date then gets a payment in your projection: an estimate until you enter the statement amount. ' + helpLink("cards", "font-semibold text-ledger") + "</p>";
    var cards = E.cards(rows).sort(byName);
    if (cards.length) {
      h += '<ul class="panel divide-y divide-rule">' + cards.map(function (card) {
        var n = E.nextPayment(rows, card, today), paused = !E.isActive(card);
        var right = n.entered ? amount(n.entered.amount) + '<div class="text-[12px] text-muted">' + E.fmtDate(n.due, false) + ", entered</div>"
          : n.estimate ? amount(-n.estimate.cents) + '<div class="text-[12px] text-muted">' + E.fmtDate(n.due, false) + ", estimate</div>"
          : '<span class="text-[13px] text-muted">No estimate yet</span>';
        return '<li><a href="#transactions" data-card="' + esc(card.id) + '" class="row-link ' + (paused ? "opacity-50" : "") + '">' +
          '<div class="min-w-0 flex-1"><div class="truncate font-medium">' + esc(card.description) + "</div>" +
          '<div class="flex items-center gap-1.5 text-[13px] text-muted">' + dot("creditcard") + "Closes the " + ordinal(card.closeDay) + ", due the " + ordinal(card.dueDay) + (paused ? ", paused" : "") + "</div></div>" +
          '<div class="text-right">' + right + "</div></a></li>";
      }).join("") + "</ul>";
    } else {
      h += '<a href="#transactions" data-card="new" class="panel block px-4 py-5 text-sm text-muted">No cards yet. <span class="font-semibold text-ledger">Add a card to forecast its payments</span></a>';
    }
    h += '</section><section class="mt-9"><div class="mb-3 flex items-baseline justify-between"><h2 class="section-title text-lg">One-time</h2>' +
      '<a href="#transactions" data-new="onetime" class="text-sm font-semibold text-ledger">Add one-time</a></div>' +
      '<p class="hint -mt-2 mb-3">Single payments on a set date, like a credit card payment. Past ones move to History when you update your balance.</p>';
    if (upcoming.length) {
      h += '<ul class="panel divide-y divide-rule">' + upcoming.map(function (r) {
        return item(r, C[r.category] + ", " + E.fmtDate(r.date) + (E.isActive(r) ? "" : ", paused"));
      }).join("") + "</ul>";
    } else {
      h += '<a href="#transactions" data-new="onetime" class="panel block px-4 py-5 text-sm text-muted">No upcoming one-time transactions. <span class="font-semibold text-ledger">Add your next card payment</span></a>';
    }
    h += '</section><section class="mt-9"><div class="mb-3 flex items-baseline justify-between"><h2 class="section-title text-lg">Recurring</h2>' +
      '<a href="#transactions" data-new="recurring" class="text-sm font-semibold text-ledger">Add recurring</a></div>' +
      '<p class="hint -mt-2 mb-3">Paychecks, rent, subscriptions, and automatic transfers.</p>';
    if (recurring.length) {
      h += '<ul class="panel divide-y divide-rule">' + recurring.map(function (r) {
        var next = E.nextOccurrence(r, today);
        return item(r, F[r.frequency] + (!E.isActive(r) ? ", paused" : next !== null ? ", next " + E.fmtDate(next, false) : ""));
      }).join("") + "</ul>";
    } else {
      h += '<a href="#transactions" data-new="recurring" class="panel block px-4 py-5 text-sm text-muted">No recurring transactions yet. <span class="font-semibold text-ledger">Add your rent or a subscription</span></a>';
    }
    h += '</section><div class="h-16 sm:hidden" aria-hidden="true"></div>' +
      '<a href="#transactions" data-new="onetime" class="fixed bottom-[calc(5.5rem+env(safe-area-inset-bottom))] right-4 z-20 flex h-14 w-14 items-center justify-center rounded-full bg-ledger text-onaccent shadow-lg shadow-ink/20 sm:hidden" aria-label="Add transaction">' +
      '<svg viewBox="0 0 24 24" class="h-7 w-7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></a>';
    return h;
  }

  function findRow(id) {
    for (var i = 0; i < state.rows.length; i++) {
      var r = state.rows[i];
      if (r.id === id && (r.type === "recurring" || r.type === "onetime")) return r;
    }
    return null;
  }
  function defaultTxForm(kind) {
    return { description: "", direction: "out", amount: "", category: kind === "onetime" ? "creditcard" : "bill",
             date: E.iso(state.today), frequency: "monthly" };
  }
  function rowTxForm(row) {
    return { description: row.description, direction: row.amount > 0 ? "in" : "out", amount: E.fixed2(row.amount),
             category: row.category, date: E.iso(row.date), frequency: row.frequency || "monthly" };
  }

  function pageTxForm(v) {
    var row = v.rowId ? findRow(v.rowId) : null;
    var kind = row ? row.type : v.kind;
    var form = v.form || (row ? rowTxForm(row) : defaultTxForm(kind)), errors = v.errors || {};
    function invalid(key) { return errors[key] ? ' aria-invalid="true" aria-describedby="' + key + '-error"' : ""; }
    function options(map, current) {
      return Object.keys(map).map(function (k) { return '<option value="' + k + '"' + (current === k ? " selected" : "") + ">" + map[k] + "</option>"; }).join("");
    }
    var h = '<a href="#transactions" data-go="transactions" class="text-sm font-semibold text-ledger">Back to transactions</a>' +
      '<h1 class="mt-3 text-2xl font-bold tracking-tight">' + (row ? "Edit " + esc(row.description) : "Add transaction") + "</h1>";
    if (!row) {
      h += '<div class="mt-4 grid grid-cols-2 rounded-xl bg-surface p-1 ring-1 ring-rule" role="group" aria-label="Transaction type">' +
        [["onetime", "One-time"], ["recurring", "Recurring"]].map(function (p) {
          return '<a href="#transactions" data-new="' + p[0] + '" class="rounded-[9px] py-2.5 text-center text-sm font-semibold ' +
            (kind === p[0] ? "bg-ink text-paper" : "text-muted") + '"' + (kind === p[0] ? ' aria-current="true"' : "") + ">" + p[1] + "</a>";
        }).join("") + "</div>";
    }
    h += '<form data-action="tx" class="mt-5 space-y-5" novalidate>' +
      '<div><label class="label" for="description">Name</label>' +
      '<input class="field" id="description" name="description" value="' + esc(form.description) + '" maxlength="80" autocomplete="off" placeholder="' + (kind === "onetime" ? "Visa payment" : "Rent") + '"' + invalid("description") + ">" +
      fieldError(errors, "description") + "</div>" +
      '<fieldset><legend class="label">Direction</legend><div class="grid grid-cols-2 gap-2">' +
      choice("direction", [["out", "Money out", "debit"], ["in", "Money in", "gain"]], form.direction) + "</div>" + fieldError(errors, "direction") + "</fieldset>" +
      '<div><label class="label" for="amount">Amount</label><div class="relative">' +
      '<span class="pointer-events-none absolute inset-y-0 left-3.5 flex items-center text-muted">$</span>' +
      '<input class="field pl-7 text-lg font-semibold" id="amount" name="amount" value="' + esc(form.amount) + '" inputmode="decimal" autocomplete="off" placeholder="0.00"' + invalid("amount") + "></div>" +
      fieldError(errors, "amount") + "</div>" +
      '<div class="grid gap-5 sm:grid-cols-2"><div><label class="label" for="category">Category</label>' +
      '<select class="field" id="category" name="category">' + options(C, form.category) + "</select>" + fieldError(errors, "category") + "</div>" +
      '<div><label class="label" for="date">' + (kind === "recurring" ? "First date" : "Date") + "</label>" +
      '<input class="field" type="date" id="date" name="date" value="' + esc(form.date) + '"' + invalid("date") + ">" + fieldError(errors, "date") + "</div></div>";
    if (kind === "recurring") {
      h += '<div><label class="label" for="frequency">Repeats</label><select class="field" id="frequency" name="frequency">' +
        options(F, form.frequency) + "</select>" + fieldError(errors, "frequency") + "</div>";
    }
    h += '<button class="btn-primary w-full">' + (row ? "Save changes" : "Add transaction") + "</button></form>";
    if (row) {
      h += '<div class="mt-8 grid grid-cols-2 gap-3 border-t border-rule pt-6">' +
        '<form data-action="tx-pause"><button class="btn-quiet w-full">' + (row.status === "paused" ? "Resume" : "Pause") + "</button></form>" +
        '<form data-action="tx-delete" data-confirm="Delete ' + esc(row.description) + '? This can\'t be undone."><button class="btn-danger w-full">Delete</button></form></div>' +
        '<p class="hint mt-3">Pausing keeps it in your ledger but leaves it out of every projection.</p>';
    }
    return h;
  }

  function findCard(id) { return E.cards(state.rows).filter(function (c) { return c.id === id; })[0] || null; }

  function pageCard(v) {
    var card = v.cardId === "new" ? null : findCard(v.cardId), rows = state.rows, today = state.today, errors = v.errors || {};
    var form = v.form || (card ? { name: card.description, closeDay: String(card.closeDay), dueDay: String(card.dueDay), estimate: card.estimate, fixed: card.amount ? E.fixed2(card.amount) : "" }
                               : { name: "", closeDay: "", dueDay: "", estimate: "average", fixed: "" });
    var h = '<a href="#transactions" data-go="transactions" class="text-sm font-semibold text-ledger">Back to transactions</a>' +
      '<h1 class="mt-3 text-2xl font-bold tracking-tight">' + (card ? "Edit " + esc(card.description) : "Add card") + "</h1>";
    if (card) {
      var est = E.cardEstimate(rows, card), open = E.openDueDates(rows, card, today);
      h += '<section class="mt-5"><h2 class="section-title">Enter a statement</h2>' +
        '<p class="hint mt-1">' + (est ? "Until you do, the projection uses " + E.money(est.cents) + (est.basis === "average" ? ", the average of your last " + est.count + " statement" + (est.count === 1 ? "" : "s") : ", the amount you set") + "."
                                      : "There is no estimate for this card yet, so nothing is forecast until you enter a statement or set an amount below.") + "</p>";
      if (open.length) {
        h += '<form data-action="statement" class="panel mt-3 grid gap-4 p-4 sm:grid-cols-2" novalidate>' +
          '<div><label class="label" for="st-due">Payment due</label><select class="field" id="st-due" name="due">' +
          open.map(function (due) { var close = E.closeBefore(card, due); return '<option value="' + due + '">' + E.fmtDate(due) + (close <= today ? " (closed " : " (closes ") + E.fmtDate(close, false) + ")</option>"; }).join("") + "</select></div>" +
          '<div><label class="label" for="st-amount">Statement balance</label>' + moneyField("st-amount", "amount", v.statementAmount || "", est ? E.fixed2(est.cents) : "0.00") + fieldError(errors, "statement") + "</div>" +
          '<button class="btn-primary sm:col-span-2">Save statement</button></form>';
      } else {
        h += '<p class="panel mt-3 px-4 py-4 hint">The next three payments already have a statement entered.</p>';
      }
      h += "</section>";
    }
    h += '<form data-action="card-save" class="mt-8 space-y-5" novalidate>' + (card ? '<h2 class="section-title">Card details</h2>' : "") +
      '<div><label class="label" for="card-name">Name</label><input class="field" id="card-name" name="name" value="' + esc(form.name) + '" maxlength="80" autocomplete="off" placeholder="Visa">' + fieldError(errors, "name") + "</div>" +
      '<div class="grid grid-cols-2 gap-5"><div><label class="label" for="card-close">Statement closes on day</label><input class="field" id="card-close" name="closeDay" value="' + esc(form.closeDay) + '" inputmode="numeric" autocomplete="off" placeholder="28">' + fieldError(errors, "closeDay") + "</div>" +
      '<div><label class="label" for="card-due">Payment due on day</label><input class="field" id="card-due" name="dueDay" value="' + esc(form.dueDay) + '" inputmode="numeric" autocomplete="off" placeholder="24">' + fieldError(errors, "dueDay") + "</div></div>" +
      '<p class="hint -mt-2">Day of the month, 1 to 31. In shorter months it moves to the last day.</p>' +
      '<fieldset><legend class="label">Estimate future payments from</legend><div class="grid grid-cols-2 gap-2">' +
      choice("estimate", Object.keys(E.ESTIMATES).map(function (k) { return [k, E.ESTIMATES[k], "accent"]; }), form.estimate) + "</div></fieldset>" +
      '<div><label class="label" for="card-fixed">Set amount</label>' + moneyField("card-fixed", "fixed", form.fixed, "1500.00") +
      '<p class="hint mt-1.5">Used when you choose a set amount, and as the starting estimate for a card with no statements yet.</p>' + fieldError(errors, "fixed") + "</div>" +
      '<button class="btn-primary w-full">' + (card ? "Save changes" : "Add card") + "</button></form>";
    if (card) {
      var past = E.cardStatements(rows, card).slice(-6).reverse();
      if (past.length) {
        h += '<section class="mt-9"><h2 class="section-title">Statements entered</h2><ul class="panel mt-3 divide-y divide-rule">' + past.map(function (r) {
          return '<li><a href="#transactions" data-edit="' + esc(r.id) + '" class="row-link"><div class="min-w-0 flex-1"><div class="font-medium">Due ' + E.fmtDate(r.date) + (r.estimate === E.ASSUMED ? '<span class="tag">estimate</span>' : "") + "</div></div>" + amount(r.amount) + "</a></li>";
        }).join("") + "</ul></section>";
      }
      h += '<div class="mt-8 grid grid-cols-2 gap-3 border-t border-rule pt-6">' +
        '<form data-action="card-pause"><button class="btn-quiet w-full">' + (card.status === "paused" ? "Resume" : "Pause") + "</button></form>" +
        '<form data-action="card-delete" data-confirm="Delete ' + esc(card.description) + '? Statements you entered stay as one-time transactions."><button class="btn-danger w-full">Delete</button></form></div>' +
        '<p class="hint mt-3">Pausing stops the estimated payments. Statements you entered still count.</p>';
    }
    return h;
  }

  function findPay(id) { return E.pays(state.rows).filter(function (p) { return p.id === id; })[0] || null; }

  function pagePay(v) {
    var pay = v.payId === "new" ? null : findPay(v.payId), rows = state.rows, today = state.today, errors = v.errors || {}, check = v.check || { amount: "", hours: "" };
    var form = v.form || (pay ? { name: pay.description, rate: E.fixed2(pay.rate), hours: E.plain(pay.hours), frequency: pay.frequency, payday: E.iso(pay.date), percent: pay.percent ? E.plain(pay.percent) : "" }
                              : { name: "Paycheck", rate: "", hours: "40", frequency: "biweekly", payday: "", percent: "" });
    var h = '<a href="#transactions" data-go="transactions" class="text-sm font-semibold text-ledger">Back to transactions</a>' +
      '<h1 class="mt-3 text-2xl font-bold tracking-tight">' + (pay ? "Edit " + esc(pay.description) : "Add hourly pay") + "</h1>";
    if (pay) {
      var est = E.payEstimate(rows, pay), open = E.openPaydays(rows, pay, today), arrived = open.filter(function (d) { return d <= today; });
      var chosen = open.length ? (arrived.length ? arrived[arrived.length - 1] : open[0]) : null;
      h += '<section class="mt-5"><h2 class="section-title">Enter a paycheck</h2>' +
        '<p class="hint mt-1">Until you do, the projection uses ' + E.money(est.cents) + ". Base pay is " + E.plain(est.hours) + " hours at " + E.money(pay.rate) + " = " + E.money(est.base) + ", and " +
        (est.count ? "your last " + est.count + " paycheck" + (est.count === 1 ? "" : "s") + " kept " + est.kept + "% of what you earned."
                   : "it assumes you keep " + est.kept + "% of it. Enter a paycheck and the ledger learns your real take-home.") + "</p>";
      if (open.length) {
        h += '<form data-action="paycheck" class="panel mt-3 grid gap-4 p-4 sm:grid-cols-2" novalidate>' +
          '<div class="sm:col-span-2"><label class="label" for="check-payday">Payday</label><select class="field" id="check-payday" name="payday">' +
          open.map(function (d) { return '<option value="' + d + '"' + (d === chosen ? " selected" : "") + ">" + E.fmtDate(d) + (d > today ? " (upcoming)" : "") + "</option>"; }).join("") + "</select></div>" +
          '<div><label class="label" for="check-amount">Take-home pay</label>' + moneyField("check-amount", "amount", check.amount, E.fixed2(est.cents)) + fieldError(errors, "paycheck") + "</div>" +
          '<div><label class="label" for="check-hours">Hours worked</label><input class="field" id="check-hours" name="hours" value="' + esc(check.hours) + '" inputmode="decimal" autocomplete="off" placeholder="' + E.plain(est.hours) + '">' + fieldError(errors, "worked") + "</div>" +
          '<p class="hint sm:col-span-2">Take-home is what reached your account. Leave hours blank if you worked your usual ' + E.plain(est.hours) + ".</p>" +
          '<button class="btn-primary sm:col-span-2">Save paycheck</button></form>';
      } else {
        h += '<p class="panel mt-3 px-4 py-4 hint">Every payday so far, and the next one, already has a paycheck entered.</p>';
      }
      h += "</section>";
    }
    h += '<form data-action="pay-save" class="mt-8 space-y-5" novalidate>' +
      (pay ? '<h2 class="section-title">Pay details</h2>' : '<p class="hint">For paychecks that change from one payday to the next. The ledger estimates each one from your rate, your usual hours, and the paychecks you enter.</p>') +
      '<div><label class="label" for="pay-name">Name</label><input class="field" id="pay-name" name="name" value="' + esc(form.name) + '" maxlength="80" autocomplete="off" placeholder="Paycheck">' + fieldError(errors, "name") + "</div>" +
      '<div class="grid grid-cols-2 gap-5"><div><label class="label" for="pay-rate">Hourly rate</label>' + moneyField("pay-rate", "rate", form.rate, "25.00") + fieldError(errors, "rate") + "</div>" +
      '<div><label class="label" for="pay-hours">Hours in a usual week</label><input class="field" id="pay-hours" name="hours" value="' + esc(form.hours) + '" inputmode="decimal" autocomplete="off" placeholder="40">' + fieldError(errors, "hours") + "</div></div>" +
      '<div class="grid gap-5 sm:grid-cols-2"><div><label class="label" for="pay-frequency">Paid</label><select class="field" id="pay-frequency" name="frequency">' +
      E.PAY_FREQUENCIES.map(function (k) { return '<option value="' + k + '"' + (form.frequency === k ? " selected" : "") + ">" + F[k] + "</option>"; }).join("") + "</select>" + fieldError(errors, "frequency") + "</div>" +
      '<div><label class="label" for="pay-payday">A payday</label><input class="field" type="date" id="pay-payday" name="payday" value="' + esc(form.payday) + '">' + fieldError(errors, "payday") + "</div></div>" +
      '<p class="hint -mt-2">Any one payday. Later paydays are counted from it.</p>' +
      '<div><label class="label" for="pay-percent">Take-home percent to start with</label><input class="field" id="pay-percent" name="percent" value="' + esc(form.percent) + '" inputmode="decimal" autocomplete="off" placeholder="100">' +
      '<p class="hint mt-1.5">Optional. The share of your pay you keep after taxes and deductions, used only until you enter a paycheck.</p>' + fieldError(errors, "percent") + "</div>" +
      '<button class="btn-primary w-full">' + (pay ? "Save changes" : "Add hourly pay") + "</button></form>";
    if (pay) {
      var past = E.paychecks(rows, pay).slice(-6).reverse();
      if (past.length) {
        h += '<section class="mt-9"><h2 class="section-title">Paychecks entered</h2><ul class="panel mt-3 divide-y divide-rule">' + past.map(function (r) {
          return '<li><a href="#transactions" data-edit="' + esc(r.id) + '" class="row-link"><div class="min-w-0 flex-1"><div class="font-medium">' + E.fmtDate(r.date) + (r.estimate === E.ASSUMED ? '<span class="tag">estimate</span>' : "") + "</div>" +
            (r.hours ? '<div class="text-[13px] text-muted">' + E.plain(r.hours) + " hours</div>" : "") + "</div>" + amount(r.amount) + "</a></li>";
        }).join("") + "</ul></section>";
      }
      h += '<div class="mt-8 grid grid-cols-2 gap-3 border-t border-rule pt-6">' +
        '<form data-action="pay-pause"><button class="btn-quiet w-full">' + (pay.status === "paused" ? "Resume" : "Pause") + "</button></form>" +
        '<form data-action="pay-delete" data-confirm="Delete ' + esc(pay.description) + '? Paychecks you entered stay as one-time transactions."><button class="btn-danger w-full">Delete</button></form></div>' +
        '<p class="hint mt-3">Pausing stops the estimated paychecks. Paychecks you entered still count.</p>';
    }
    return h;
  }

  // The same text as the app's Help page (templates/_help_body.html), kept in help.js.
  function pageHelp() {
    return '<a href="#overview" data-go="overview" class="text-sm font-semibold text-ledger">Back to overview</a>' +
      '<p class="hint mt-3" data-preview-note>You are reading this inside the preview, which runs in your browser on made-up data. The parts about servers, Docker, and backups describe the real app you host yourself.</p>' +
      HELP_HTML;
  }

  function fileSection(heading, tag, hint, downloadAction, detailsHint, uploadAction, uploadLabel, errors, more, wrapClass) {
    return '<section class="panel ' + wrapClass + ' p-4"><div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div>' +
      "<" + tag + ' class="section-title">' + heading + "</" + tag + '><p class="hint mt-0.5">' + hint + "</p></div>" +
      '<a href="#" data-download="' + downloadAction + '" class="btn-primary shrink-0">Download CSV</a></div>' +
      '<details class="group mt-4 border-t border-rule pt-4"' + (errors && errors.length ? " open" : "") + ">" +
      '<summary class="flex cursor-pointer list-none items-center justify-between text-sm font-semibold">Replace from a CSV' +
      '<span class="text-ledger group-open:hidden">Show</span><span class="hidden text-ledger group-open:inline">Hide</span></summary>' +
      '<p class="hint mt-2">' + detailsHint + "</p>" + uploadForm(uploadAction, uploadLabel, errors, more) + "</details></section>";
  }

  function pageHistory(v) {
    var rows = state.rows, today = state.today;
    var periods = E.categoryPeriods(rows, today, "creditcard"), cardAverage = E.averageMonthly(periods);
    var settled = E.splitOnetime(rows).settled, snapshots = E.snapshotHistory(rows);
    var h = fileSection("Your ledger file", "h1", "Every balance and transaction in one CSV. Opens in Numbers or Excel.", "ledger",
      "Download the file, add or change rows in Numbers or Excel, export it as CSV, and upload it here. The upload replaces everything, and your current file is backed up first.",
      "upload", "Ledger CSV", v.uploadErrors, v.moreErrors, "");

    // The real app reads this from the backup service's status file. The
    // preview has no backup service, so it shows what a healthy one looks like.
    var clock = new Date(), ranToday = clock.getHours() * 60 + clock.getMinutes() >= 3 * 60 + 15;
    h += '<section class="panel mt-4 p-4"><div class="flex items-baseline justify-between"><h2 class="section-title">Cloud backup</h2>' + helpLink("backup") + "</div>" +
      '<p class="mt-1 text-sm"><span class="font-semibold text-gain">Backed up</span> ' + E.fmtDate(ranToday ? today : today - 1) + " at 3:15 AM</p>" +
      '<p class="hint mt-0.5">Encrypted on this server before upload. 30 versions kept.</p>' +
      '<p class="hint mt-1" data-preview-note>Example only: this preview has no backup service and nothing here is uploaded.</p></section>';

    h += '<section class="mt-9"><h2 class="section-title">Credit card spending</h2>' +
      '<p class="hint mt-1">Measured between balance updates. Update your balance on the first day of each quarter (Jan 1, Apr 1, Jul 1, Oct 1) and each row becomes one quarter.</p>';
    if (cardAverage !== null) {
      h += '<p class="mt-3 text-sm">Average across finished periods: <span class="text-lg font-semibold text-card">' + E.money(cardAverage) + '</span><span class="text-muted"> per month</span></p>';
    }
    if (periods.length) {
      h += '<ul class="panel mt-3 divide-y divide-rule">' + periods.map(function (p) {
        return '<li class="flex items-center gap-3 px-4 py-3"><div class="min-w-0 flex-1">' +
          '<div class="font-medium">' + E.fmtDate(p.start, false) + " to " + E.fmtDate(p.end) + "</div>" +
          '<div class="text-[13px] text-muted">' + (p.open ? "In progress, " : "") + p.days + " days, " + p.count + " payment" + (p.count === 1 ? "" : "s") + "</div></div>" +
          '<div class="text-right"><div class="font-semibold text-card">' + E.money(p.spent) + "</div>" +
          '<div class="text-[13px] text-muted">' + E.money(p.monthly) + "/mo</div></div></li>";
      }).join("") + "</ul>";
    } else {
      h += '<p class="panel mt-3 px-4 py-5 hint">Spending shows up here once you\'ve updated your balance at least once after adding credit card transactions.</p>';
    }
    h += "</section>";

    h += '<section class="mt-9"><h2 class="section-title">Balance updates</h2>' +
      '<p class="hint mt-1">“vs expected” is what your bank showed minus what the ledger predicted. A gap usually means spending that isn\'t in the ledger yet.</p>' +
      '<ul class="panel mt-3 divide-y divide-rule">' + snapshots.map(function (s) {
        var note = "";
        if (s.variance !== null && s.variance !== 0) note = '<div class="text-[13px] ' + (s.variance > 0 ? "text-gain" : "text-debit") + '">' + E.money(s.variance, true) + " vs expected</div>";
        else if (s.variance !== null) note = '<div class="text-[13px] text-muted">Matched expected</div>';
        return '<li class="flex items-center gap-3 px-4 py-3"><div class="min-w-0 flex-1">' +
          '<div class="font-medium">' + E.fmtDate(s.row.date) + "</div>" +
          '<div class="text-[13px] text-muted">' + (s.change === null ? esc(s.row.description || "Starting balance") : E.money(s.change, true) + " since previous") + "</div></div>" +
          '<div class="text-right"><div class="font-semibold">' + E.money(s.row.amount) + "</div>" + note + "</div></li>";
      }).join("") + "</ul>";
    if (snapshots.length > 1) {
      h += '<form data-action="balance-undo" class="mt-3" data-confirm="Remove the balance update from ' + E.fmtDate(snapshots[0].row.date) + '?">' +
        '<button class="text-sm font-semibold text-debit">Undo latest update</button></form>';
    }
    h += "</section>";

    h += '<section class="mt-9"><details class="group"><summary class="flex cursor-pointer list-none items-baseline justify-between">' +
      '<h2 class="section-title">Settled one-time transactions</h2>' +
      '<span class="text-sm font-semibold text-ledger group-open:hidden">Show ' + settled.length + "</span>" +
      '<span class="hidden text-sm font-semibold text-ledger group-open:inline">Hide</span></summary>';
    if (settled.length) {
      h += '<ul class="panel mt-3 divide-y divide-rule">' + settled.map(function (r) {
        return '<li class="flex items-center gap-3 px-4 py-3 ' + (E.isActive(r) ? "" : "opacity-50") + '"><div class="min-w-0 flex-1">' +
          '<div class="truncate font-medium">' + esc(r.description) + "</div>" +
          '<div class="flex items-center gap-1.5 text-[13px] text-muted">' + dot(r.category) + C[r.category] + ", " + E.fmtDate(r.date) + (r.estimate === E.ASSUMED ? '<span class="tag">estimate</span>' : "") + "</div></div>" + amount(r.amount) + "</li>";
      }).join("") + "</ul>";
    } else {
      h += '<p class="panel mt-3 px-4 py-5 hint">Nothing settled yet.</p>';
    }
    return h + "</details></section>";
  }

  function pageNetworth(v) {
    var book = state.book, snapsAsc = E.series(book), latest = E.latestValues(book), today = state.today;
    var snaps = snapsAsc.slice().reverse();
    var accounts = book.accounts.slice().sort(function (a, b) {
      var ka = [E.accountActive(a) ? 0 : 1, a.kind !== "asset" ? 1 : 0, a.name.toLowerCase()];
      var kb = [E.accountActive(b) ? 0 : 1, b.kind !== "asset" ? 1 : 0, b.name.toLowerCase()];
      for (var i = 0; i < 3; i++) if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1;
      return 0;
    });
    var activeAccounts = accounts.filter(E.accountActive);
    var accountForm = v.accountForm || { name: "", kind: "asset" }, accountErrors = v.accountErrors || {};
    var h = "";
    if (snaps.length) {
      var now = snaps[0];
      h += '<section data-chart-root><p class="text-sm font-medium text-muted" data-readout-d>Net worth on ' + E.fmtDate(now.date) + "</p>" +
        '<p class="mt-1 text-[44px] font-bold leading-none tracking-[-0.03em] sm:text-6xl ' + (now.net < 0 ? "text-debit" : "") + '" data-readout-b>' + E.money(now.net) + "</p>" +
        '<p class="mt-2 min-h-[1.25rem] text-sm text-muted" data-readout-l>' +
        (snaps.length > 1 ? E.money(now.net - snaps[1].net, true) + " since " + E.fmtDate(snaps[1].date) : "Your first snapshot") + "</p>";
      if (snaps.length > 1) {
        var points = snapsAsc.map(function (s, i) {
          return { date: s.date, cents: s.net, label: i === 0 ? "" : E.money(s.net - snapsAsc[i - 1].net, true) + " from previous" };
        });
        var end = Math.max(snapsAsc[snapsAsc.length - 1].date, snapsAsc[0].date + 1);
        h += chartBox(E.buildChart(points, snapsAsc[0].date, end, "line"), "Net worth from " + E.fmtDate(snapsAsc[0].date) + " to " + E.fmtDate(now.date));
      }
      h += '<dl class="mt-5 grid grid-cols-2 divide-x divide-rule rounded-2xl bg-surface ring-1 ring-rule">' +
        '<div class="px-4 py-3"><dt class="text-[13px] text-muted">Assets</dt><dd class="mt-0.5 text-lg font-semibold">' + E.money(now.assets) + "</dd></div>" +
        '<div class="px-4 py-3"><dt class="text-[13px] text-muted">Debts</dt><dd class="mt-0.5 text-lg font-semibold ' + (now.debts > 0 ? "text-debit" : "") + '">' + E.money(now.debts) + "</dd></div></dl></section>";
    } else {
      h += '<section><h1 class="text-3xl font-bold tracking-tight">Track your net worth</h1>' +
        '<p class="hint mt-2 text-base">Add each account once: savings, retirement, brokerage, credit cards, loans. Then record their balances whenever you check them, and this page charts the total over time.</p></section>';
    }

    if (activeAccounts.length) {
      h += '<section class="mt-9"><h2 class="section-title">Record balances</h2>' +
        '<p class="hint mt-1">Leave an account blank to keep its last balance. Enter debts as the amount you owe.</p>' +
        '<form data-action="nw-record" class="panel mt-3"><div class="border-b border-rule p-4">' +
        '<label class="label" for="nw-date">Date</label>' +
        '<input class="field" type="date" id="nw-date" name="date" value="' + E.iso(today) + '" max="' + E.iso(today) + '"></div><div class="divide-y divide-rule">' +
        activeAccounts.map(function (a, i) {
          var last = latest[a.name];
          return '<div class="flex items-center gap-3 px-4 py-3"><label for="nw-' + (i + 1) + '" class="min-w-0 flex-1">' +
            '<span class="block truncate font-medium">' + esc(a.name) + "</span>" +
            '<span class="block text-[13px] text-muted">' + K[a.kind] + (last ? ", " + E.money(last.amount) + " on " + E.fmtDate(last.date, false) : "") + "</span></label>" +
            '<input type="hidden" name="account" value="' + esc(a.name) + '">' +
            '<div class="relative w-36 shrink-0"><span class="pointer-events-none absolute inset-y-0 left-3 flex items-center text-muted">$</span>' +
            '<input class="field pl-6 text-right" id="nw-' + (i + 1) + '" name="amount" inputmode="decimal" autocomplete="off" placeholder="' + (last ? signedFixed(last.amount) : "0.00") + '"></div></div>';
        }).join("") +
        '</div><div class="border-t border-rule p-4"><button class="btn-primary w-full">Save balances</button></div></form></section>';
    }

    h += '<section class="mt-9"><h2 class="section-title">Accounts</h2>';
    if (accounts.length) {
      h += '<ul class="panel mt-3 divide-y divide-rule">' + accounts.map(function (a) {
        var last = latest[a.name];
        return '<li><a href="#net-worth" data-account="' + esc(a.name) + '" class="row-link ' + (E.accountActive(a) ? "" : "opacity-50") + '">' +
          '<div class="min-w-0 flex-1"><div class="truncate font-medium">' + esc(a.name) + "</div>" +
          '<div class="text-[13px] text-muted">' + K[a.kind] + (E.accountActive(a) ? "" : ", hidden") + "</div></div>" +
          '<span class="whitespace-nowrap font-semibold ' + (a.kind === "debt" && last && last.amount > 0 ? "text-debit" : "") + '">' +
          (last ? E.money(a.kind === "debt" ? -last.amount : last.amount) : '<span class="text-muted">No balance yet</span>') + "</span></a></li>";
      }).join("") + "</ul>";
    }
    h += '<form data-action="nw-add-account" class="panel mt-3 space-y-4 p-4" novalidate><div>' +
      '<label class="label" for="acct-name">Add an account</label>' +
      '<input class="field" id="acct-name" name="name" value="' + esc(accountForm.name) + '" maxlength="80" autocomplete="off" placeholder="Savings, 401k, Visa, Car loan"' +
      (accountErrors.name ? ' aria-invalid="true" aria-describedby="acct-error"' : "") + ">" +
      (accountErrors.name ? '<p class="field-error" id="acct-error">' + esc(accountErrors.name) + "</p>" : "") + "</div>" +
      '<fieldset class="grid grid-cols-2 gap-2"><legend class="sr-only">Kind</legend>' +
      choice("kind", [["asset", "Asset", "gain"], ["debt", "Debt", "debit"]], accountForm.kind) + "</fieldset>" +
      '<button class="btn-quiet w-full">Add account</button></form></section>';

    if (snaps.length) {
      h += '<section class="mt-9"><h2 class="section-title">Snapshots</h2><ul class="panel mt-3 divide-y divide-rule">' +
        snaps.map(function (s, i) {
          return '<li class="flex items-center gap-3 px-4 py-3"><div class="min-w-0 flex-1">' +
            '<div class="font-medium">' + E.fmtDate(s.date) + "</div>" +
            '<div class="text-[13px] text-muted">' + (i < snaps.length - 1 ? E.money(s.net - snaps[i + 1].net, true) : "First snapshot") + "</div></div>" +
            '<div class="text-right font-semibold ' + (s.net < 0 ? "text-debit" : "") + '">' + E.money(s.net) + "</div>" +
            '<form data-action="nw-delete-date" data-day="' + s.date + '" data-confirm="Remove every balance recorded on ' + E.fmtDate(s.date) + '?">' +
            '<button class="-mr-2 flex h-11 w-11 items-center justify-center text-muted hover:text-debit" aria-label="Remove balances from ' + E.fmtDate(s.date) + '">' +
            '<svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button></form></li>';
        }).join("") + "</ul></section>";
    }

    h += fileSection("Your net worth file", "h2", "Accounts and every balance you've recorded, in one CSV.", "networth",
      "Add rows with type <b>value</b>, a date, the account name, and the amount. New accounts need a row with type <b>account</b> and kind <b>asset</b> or <b>debt</b>.",
      "nw-upload", "Net worth CSV", v.uploadErrors, 0, "mt-9");
    return h;
  }

  function pageAccount(v) {
    var account = E.findAccount(state.book, v.accountName);
    if (!account) return pageNetworth({});
    return '<a href="#net-worth" data-go="networth" class="text-sm font-semibold text-ledger">Back to net worth</a>' +
      '<h1 class="mt-3 text-2xl font-bold tracking-tight">Edit ' + esc(account.name) + "</h1>" +
      '<form data-action="nw-edit-account" class="mt-5 space-y-5" novalidate><div>' +
      '<label class="label" for="name">Name</label>' +
      '<input class="field" id="name" name="name" value="' + esc(account.name) + '" maxlength="80" autocomplete="off"' + (v.error ? ' aria-invalid="true" aria-describedby="name-error"' : "") + ">" +
      (v.error ? '<p class="field-error" id="name-error">' + esc(v.error) + "</p>" : "") + "</div>" +
      '<fieldset class="grid grid-cols-2 gap-2"><legend class="label">Kind</legend>' +
      choice("kind", [["asset", "Asset", "gain"], ["debt", "Debt", "debit"]], account.kind) + "</fieldset>" +
      '<label class="flex items-start gap-3"><input type="checkbox" name="status" value="hidden" class="mt-1 h-5 w-5 accent-[rgb(var(--ledger))]"' + (E.accountActive(account) ? "" : " checked") + ">" +
      '<span><span class="font-medium">Hide from Record balances</span><span class="hint block">For accounts you\'ve closed. Its last balance still counts, so record 0 first if it\'s gone.</span></span></label>' +
      '<button class="btn-primary w-full">Save changes</button></form>' +
      '<form data-action="nw-delete-account" class="mt-8 border-t border-rule pt-6" data-confirm="Delete ' + esc(account.name) + ' and every balance recorded for it? This can\'t be undone.">' +
      '<button class="btn-danger w-full">Delete account and its history</button></form>';
  }

  function pageAppearance() {
    var h = '<a href="#overview" data-go="overview" class="text-sm font-semibold text-ledger">Back to overview</a>' +
      '<h1 class="mt-3 text-2xl font-bold tracking-tight">Theme</h1>' +
      '<p class="hint mt-1">Changes how the ledger looks in this browser. Each device keeps its own choice.</p>' +
      '<form data-action="appearance" class="mt-5 space-y-6" data-theme-form>' +
      '<fieldset><legend class="label">Light or dark</legend><div class="grid grid-cols-3 gap-2">' +
      Object.keys(E.MODES).map(function (key) {
        return '<label class="flex min-h-[48px] cursor-pointer items-center justify-center rounded-[10px] border border-rule bg-surface text-[15px] font-semibold text-muted has-[:checked]:border-transparent has-[:checked]:text-ledger has-[:checked]:ring-2 has-[:checked]:ring-ledger has-[:focus-visible]:outline has-[:focus-visible]:outline-2">' +
          '<input type="radio" name="mode" value="' + key + '" class="sr-only"' + (state.mode === key ? " checked" : "") + ">" + E.MODES[key] + "</label>";
      }).join("") + "</div></fieldset>" +
      '<fieldset><legend class="label">Colors</legend><div class="grid grid-cols-2 gap-3 sm:grid-cols-3">' +
      E.THEMES.map(function (t) {
        return '<label class="block cursor-pointer rounded-2xl bg-surface p-3 ring-1 ring-rule has-[:checked]:ring-2 has-[:checked]:ring-ledger has-[:focus-visible]:outline has-[:focus-visible]:outline-2">' +
          '<input type="radio" name="theme" value="' + t[0] + '" class="sr-only"' + (state.theme === t[0] ? " checked" : "") + ">" +
          '<span class="block font-semibold">' + esc(t[1]) + "</span>" +
          '<span class="block min-h-[2.25rem] text-[13px] leading-snug text-muted">' + esc(t[2]) + "</span>" +
          ["dark", "light"].map(function (sample) {
            return '<span data-theme="' + t[0] + '" data-mode="' + sample + '" class="mt-1.5 flex items-center gap-1 rounded-lg bg-paper p-1.5 ring-1 ring-rule" aria-hidden="true">' +
              '<span class="w-6 text-center text-[11px] font-bold text-ink">Aa</span>' +
              '<span class="h-4 flex-1 rounded bg-surface ring-1 ring-rule"></span><span class="h-4 flex-1 rounded bg-ledger"></span>' +
              '<span class="h-4 flex-1 rounded bg-gain"></span><span class="h-4 flex-1 rounded bg-debit"></span><span class="h-4 flex-1 rounded bg-card"></span></span>';
          }).join("") + "</label>";
      }).join("") + "</div>" +
      '<p class="hint mt-3">Each sample shows dark on top and light below: text, panel, accent, money in, money out, credit card.</p></fieldset>' +
      '<button class="btn-primary w-full">Save theme</button></form>' +
      '<p class="hint mt-4">The real app remembers this choice in each browser. In this preview it lasts until you reload.</p>';
    return h;
  }

  // ------------------------------------------------------------------ shell
  var PAGES = {
    appearance: [pageAppearance, null], help: [pageHelp, null],
    login: [pageLogin, null], setup: [pageSetup, "overview"], overview: [pageOverview, "overview"],
    transactions: [pageTransactions, "transactions"], txform: [pageTxForm, "transactions"], card: [pageCard, "transactions"], pay: [pagePay, "transactions"],
    history: [pageHistory, "history"], networth: [pageNetworth, "networth"], account: [pageAccount, "networth"]
  };

  function render() {
    var v = state.view;
    // The same redirects the server does.
    if (!state.authed) { if (v.name !== "login") v = state.view = { name: "login" }; }
    else if (v.name === "login") v = state.view = { name: "overview" };
    var hasBalance = E.anchor(state.rows) !== null;
    if (state.authed && !hasBalance && ["overview", "transactions", "txform", "history", "card", "pay"].indexOf(v.name) >= 0) v = state.view = { name: "setup" };
    if (hasBalance && v.name === "setup") v = state.view = { name: "overview" };
    if (v.name === "txform" && v.rowId && !findRow(v.rowId)) v = state.view = { name: "transactions" };
    if (v.name === "card" && v.cardId !== "new" && !findCard(v.cardId)) v = state.view = { name: "transactions" };
    if (v.name === "pay" && v.payId !== "new" && !findPay(v.payId)) v = state.view = { name: "transactions" };

    // A choice that was tried on the Theme page but not saved doesn't stick.
    document.documentElement.setAttribute("data-theme", state.theme);
    document.documentElement.setAttribute("data-mode", state.mode);
    chartData = null;
    var page = PAGES[v.name], active = page[1], content = page[0](v);
    var h = '<header class="sticky top-0 z-30 border-b border-rule/70 bg-paper/85 backdrop-blur-md">' +
      '<div class="mx-auto flex h-14 max-w-2xl items-center justify-between gap-4 px-4">' +
      '<a href="#overview" data-go="overview" class="text-[17px] font-bold tracking-tight">Ledger</a>' +
      '<nav class="hidden items-center gap-1 sm:flex" aria-label="Main">' +
      TABS.map(function (t) {
        return '<a href="#' + HASH[t[0]] + '" data-go="' + t[0] + '" class="rounded-full px-3.5 py-1.5 text-sm font-medium ' +
          (active === t[0] ? "bg-ink text-paper" : "text-muted hover:text-ink") + '"' + (active === t[0] ? ' aria-current="page"' : "") + ">" + t[1] + "</a>";
      }).join("") + "</nav>" +
      (state.authed ? '<div class="flex items-center gap-4"><a href="#overview" data-go="help" class="text-sm font-medium text-muted hover:text-ink">Help</a>' +
        '<a href="#overview" data-go="appearance" class="text-sm font-medium text-muted hover:text-ink">Theme</a>' +
        '<form data-action="logout"><button class="text-sm font-medium text-muted hover:text-ink">Lock</button></form></div>' : "") +
      "</div></header>" +
      '<main class="mx-auto max-w-2xl px-4 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-5 sm:pb-16">' +
      state.flash.map(function (f) {
        return '<div role="status" class="mb-4 rounded-xl px-4 py-3 text-sm font-medium ' + (f.kind === "error" ? "bg-debit/10 text-debit" : "bg-ledger/10 text-ledger") + '">' + esc(f.text) + "</div>";
      }).join("") + content + "</main>";
    if (active) {
      h += '<nav class="fixed inset-x-0 bottom-0 z-30 border-t border-rule/70 bg-paper/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-md sm:hidden" aria-label="Main">' +
        '<div class="mx-auto grid max-w-md grid-cols-4">' +
        TABS.map(function (t) {
          return '<a href="#' + HASH[t[0]] + '" data-go="' + t[0] + '" class="flex flex-col items-center gap-1 pb-2 pt-2.5 text-[11px] font-medium ' +
            (active === t[0] ? "text-ink" : "text-muted") + '"' + (active === t[0] ? ' aria-current="page"' : "") + ">" +
            '<svg viewBox="0 0 24 24" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="' + (active === t[0] ? "2.2" : "1.7") + '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + t[2] + '"/></svg>' +
            t[1] + "</a>";
        }).join("") + "</div></nav>";
    }
    state.flash = [];
    root.innerHTML = h;
    initChart();
    if (active) { try { if (location.hash !== "#" + HASH[active]) history.replaceState(null, "", "#" + HASH[active]); } catch (e) { /* hash is a nicety */ } }
    var target = v.anchor && document.getElementById(v.anchor);
    if (target) target.scrollIntoView(); else window.scrollTo(0, 0);
  }
  function go(view) { state.view = view; render(); }

  // ------------------------------------------------------------------ chart
  // Scrub the chart with a finger or mouse; the big number above it shows the
  // balance on that day. Same behaviour as the app's static/app.js.
  var activeChart = null;
  function initChart() {
    activeChart = null;
    var chart = root.querySelector("[data-chart]");
    if (!chart || !chartData || !chartData.points.length) return;
    var data = chartData, points = data.points, mode = data.mode;
    var box = chart.closest("[data-chart-root]");
    var outB = box.querySelector("[data-readout-b]"), outD = box.querySelector("[data-readout-d]"), outL = box.querySelector("[data-readout-l]");
    var cursor = chart.querySelector("[data-cursor]"), dotEl = chart.querySelector("[data-dot]"), lowDot = chart.querySelector("[data-low-dot]");
    var o = data.origin.split("-").map(Number), origin = new Date(o[0], o[1] - 1, o[2]), span = data.span || 1;
    var defaults = { b: outB.textContent, d: outD.textContent, l: outL.textContent };
    var fmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });
    function put(node, x, y) { node.style.left = x + "%"; if (y !== undefined) node.style.top = y + "%"; node.classList.remove("hidden"); }
    var low = points[data.lowIndex];
    if (low && mode === "step") put(lowDot, low.x, low.y);
    chart.querySelectorAll("[data-mark]").forEach(function (m) { put(m, Number(m.getAttribute("data-x")), Number(m.getAttribute("data-y"))); });
    function show(clientX) {
      var rect = chart.getBoundingClientRect();
      var x = Math.max(0, Math.min(100, (clientX - rect.left) / rect.width * 100)), p = points[0];
      if (mode === "line") {
        points.forEach(function (q) { if (Math.abs(q.x - x) < Math.abs(p.x - x)) p = q; });
        put(cursor, p.x); put(dotEl, p.x, p.y);
        outB.textContent = p.b; outD.textContent = "Net worth on " + p.D; outL.textContent = p.l || "Your first snapshot";
        return;
      }
      for (var i = 1; i < points.length && points[i].x <= x; i++) p = points[i];
      var day = new Date(origin.getFullYear(), origin.getMonth(), origin.getDate() + Math.round(span * x / 100));
      put(cursor, x); put(dotEl, x, p.y);
      outB.textContent = p.b; outD.textContent = "Balance on " + fmt.format(day);
      outL.textContent = p.l ? "After " + p.l + " on " + p.d : "Start of day, before anything dated " + p.d;
    }
    function reset() {
      cursor.classList.add("hidden"); dotEl.classList.add("hidden");
      outB.textContent = defaults.b; outD.textContent = defaults.d; outL.textContent = defaults.l;
    }
    chart.addEventListener("pointerdown", function (e) { show(e.clientX); });
    chart.addEventListener("pointermove", function (e) { if (e.pointerType === "mouse" || e.buttons || e.pressure) show(e.clientX); });
    chart.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") reset(); });
    chart.addEventListener("pointercancel", reset);
    activeChart = { el: chart, reset: reset };
  }
  document.addEventListener("pointerdown", function (e) {
    if (activeChart && !activeChart.el.contains(e.target)) activeChart.reset();
  });

  // ---------------------------------------------------------------- dialogs
  var overlay = document.getElementById("overlay");
  function closeDialog() { overlay.hidden = true; overlay.innerHTML = ""; }
  function confirmDialog(message, onYes) {
    overlay.innerHTML = '<div class="pv-dialog" role="alertdialog" aria-modal="true" aria-labelledby="pv-msg">' +
      '<p id="pv-msg" class="pv-dialog-text">' + esc(message) + "</p>" +
      '<div class="pv-dialog-actions"><button type="button" class="btn-quiet" data-no>Cancel</button><button type="button" class="btn-primary" data-yes>OK</button></div></div>';
    overlay.hidden = false;
    overlay.querySelector("[data-no]").onclick = closeDialog;
    overlay.querySelector("[data-yes]").onclick = function () { closeDialog(); onYes(); };
    overlay.querySelector("[data-yes]").focus();
  }
  function csvDialog(filename, text) {
    overlay.innerHTML = '<div class="pv-dialog pv-dialog-wide" role="dialog" aria-modal="true" aria-labelledby="pv-file">' +
      '<p id="pv-file" class="section-title">' + esc(filename) + "</p>" +
      '<p class="hint mt-1">The app downloads this file. A preview can\'t start downloads, so here is what\'s in it.</p>' +
      '<pre class="pv-csv" tabindex="0">' + esc(text) + "</pre>" +
      '<div class="pv-dialog-actions"><button type="button" class="btn-quiet" data-no>Close</button><button type="button" class="btn-primary" data-copy>Copy</button></div></div>';
    overlay.hidden = false;
    overlay.querySelector("[data-no]").onclick = closeDialog;
    var copy = overlay.querySelector("[data-copy]");
    copy.onclick = function () {
      function done(ok) { copy.textContent = ok ? "Copied" : "Select the text to copy"; }
      try { navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); }); }
      catch (e) { done(false); }
    };
    copy.focus();
  }
  overlay.addEventListener("click", function (e) { if (e.target === overlay) closeDialog(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !overlay.hidden) closeDialog(); });

  // ---------------------------------------------------------------- actions
  function val(form, name) { var el = form.elements[name]; return el ? String(el.value || "").trim() : ""; }
  function readFile(form, done) {
    var input = form.querySelector('input[type="file"]'), file = input && input.files && input.files[0];
    if (!file) return done(null, "Choose a CSV file to upload.");
    if (!/\.csv$/i.test(file.name)) return done(null, "That file isn't a .csv. In Numbers or Excel, export as CSV first.");
    var reader = new FileReader();
    reader.onload = function () { done(String(reader.result), null); };
    reader.onerror = function () { done(null, "That file couldn't be read."); };
    reader.readAsText(file);
  }
  function readTxForm(form, kind) {
    var f = {};
    ["description", "direction", "amount", "category", "date", "frequency"].forEach(function (k) { f[k] = val(form, k); });
    var errors = {}, description = E.cleanText(f.description), cents = E.parseMoney(f.amount), day = E.parseISO(f.date);
    if (!description) errors.description = "Add a short name, like Rent or Visa payment.";
    if (cents === null || cents <= 0) errors.amount = "Enter an amount greater than zero, like 120.00.";
    if (day === null) errors.date = "Pick a date.";
    if (!C[f.category]) errors.category = "Pick a category.";
    if (kind === "recurring" && !F[f.frequency]) errors.frequency = "Pick how often it repeats.";
    if (f.direction !== "in" && f.direction !== "out") errors.direction = "Choose money in or money out.";
    if (Object.keys(errors).length) return { values: null, errors: errors, form: f };
    return { values: { description: description, category: f.category, date: day, amount: f.direction === "in" ? cents : -cents,
                       frequency: kind === "recurring" ? f.frequency : "" }, errors: {}, form: f };
  }

  var actions = {
    whatif: function (form) {
      var f = { direction: val(form, "direction"), amount: val(form, "amount"), date: val(form, "date") };
      var cents = E.parseMoney(f.amount), day = E.parseISO(f.date), from = Math.max(state.today, E.anchor(state.rows).date);
      var problem = cents === null || cents <= 0 ? "Enter an amount greater than zero, like 1500.00." : day === null ? "Pick a date." : day < from ? "Pick today or a later date." : null;
      if (problem) return go({ name: "overview", whatIfForm: f, whatIfError: problem });
      state.whatIf = { cents: f.direction === "in" ? cents : -cents, date: day };
      go({ name: "overview" });
    },
    "pay-save": function (form) {
      var v = state.view, pay = v.payId === "new" ? null : findPay(v.payId);
      var f = { name: val(form, "name"), rate: val(form, "rate"), hours: val(form, "hours"), frequency: val(form, "frequency"), payday: val(form, "payday"), percent: val(form, "percent") };
      function number(text, low, high) { var n = E.parseMoney(text); return n !== null && n > low * 100 && n <= high * 100 ? n : null; }
      var errors = {}, name = E.cleanText(f.name), rate = number(f.rate, 0, 100000), hours = number(f.hours, 0, 168), payday = E.parseISO(f.payday);
      var percent = f.percent ? number(f.percent, 0, 100) : 0;
      if (!name) errors.name = "Give it a name, like Paycheck.";
      if (rate === null) errors.rate = "Enter your hourly rate, like 25.00.";
      if (hours === null) errors.hours = "Enter the hours in a usual week, like 40.";
      if (E.PAY_FREQUENCIES.indexOf(f.frequency) < 0) errors.frequency = "Pick how often you are paid.";
      if (payday === null) errors.payday = "Pick any payday.";
      if (percent === null) errors.percent = "Enter a percent from 1 to 100, or leave it blank.";
      if (Object.keys(errors).length) return go({ name: "pay", payId: v.payId, form: f, errors: errors });
      if (!pay) { pay = E.Row(E.newId(), "pay", payday, name, "", 0, f.frequency); state.rows.push(pay); flash("Added " + name + "."); }
      else flash("Saved " + name + ".");
      pay.description = name; pay.rate = rate; pay.hours = hours; pay.frequency = f.frequency; pay.date = payday; pay.percent = percent;
      go({ name: "transactions" });
    },
    "pay-pause": function () {
      var pay = findPay(state.view.payId);
      if (pay) { pay.status = pay.status === "paused" ? "active" : "paused"; flash(pay.description + " is " + (pay.status === "paused" ? "paused" : "back on") + "."); }
      go({ name: "transactions" });
    },
    "pay-delete": function () {
      var pay = findPay(state.view.payId);
      if (pay) {
        // Paychecks already entered stay as ordinary one-time transactions.
        state.rows = state.rows.filter(function (r) { return r !== pay; });
        state.rows.forEach(function (r) { if (r.pay === pay.id) r.pay = ""; });
        flash("Deleted " + pay.description + ".");
      }
      go({ name: "transactions" });
    },
    paycheck: function (form) {
      var pay = findPay(state.view.payId);
      if (!pay) return go({ name: "transactions" });
      var check = { amount: val(form, "amount"), hours: val(form, "hours") }, payday = Number(val(form, "payday")), cents = E.parseMoney(check.amount), errors = {};
      var worked = E.parseMoney(check.hours), hours = !check.hours ? 0 : worked !== null && worked > 0 && worked <= 74400 ? worked : null;
      if (cents === null || cents <= 0 || E.openPaydays(state.rows, pay, state.today).indexOf(payday) < 0) errors.paycheck = "Enter your take-home pay, like 1602.11.";
      if (hours === null) errors.worked = "Enter the hours you worked, like 80, or leave it blank.";
      if (Object.keys(errors).length) return go({ name: "pay", payId: pay.id, check: check, errors: errors });
      var row = E.Row(E.newId(), "onetime", payday, pay.description, "income", cents);
      row.pay = pay.id; row.hours = hours;
      state.rows.push(row);
      flash("Saved the " + E.fmtDate(payday) + " paycheck: " + E.money(cents) + ".");
      go({ name: "transactions" });
    },
    "card-save": function (form) {
      var v = state.view, card = v.cardId === "new" ? null : findCard(v.cardId), checked = form.querySelector('input[name="estimate"]:checked');
      var f = { name: val(form, "name"), closeDay: val(form, "closeDay"), dueDay: val(form, "dueDay"), estimate: checked ? checked.value : "", fixed: val(form, "fixed") };
      var errors = {}, name = E.cleanText(f.name), close = /^\d{1,2}$/.test(f.closeDay) ? Number(f.closeDay) : 0, due = /^\d{1,2}$/.test(f.dueDay) ? Number(f.dueDay) : 0;
      var fixed = f.fixed ? E.parseMoney(f.fixed) : 0;
      if (!E.ESTIMATES[f.estimate]) f.estimate = "average";
      if (!name) errors.name = "Give the card a name, like Visa.";
      if (close < 1 || close > 31) errors.closeDay = "Enter a day from 1 to 31.";
      if (due < 1 || due > 31) errors.dueDay = "Enter a day from 1 to 31.";
      if (fixed === null) errors.fixed = "Enter an amount like 1500.00, or leave it blank.";
      else if (f.estimate === "fixed" && !fixed) errors.fixed = "Enter the amount to use, like 1500.00.";
      if (Object.keys(errors).length) return go({ name: "card", cardId: v.cardId, form: f, errors: errors });
      if (!card) { card = E.Row(E.newId(), "card", E.CARD_DATE, name, "", 0); state.rows.push(card); flash("Added " + name + "."); }
      else flash("Saved " + name + ".");
      card.description = name; card.closeDay = close; card.dueDay = due; card.estimate = f.estimate; card.amount = fixed;
      go({ name: "transactions" });
    },
    "card-pause": function () {
      var card = findCard(state.view.cardId);
      if (card) { card.status = card.status === "paused" ? "active" : "paused"; flash(card.description + " is " + (card.status === "paused" ? "paused" : "back on") + "."); }
      go({ name: "transactions" });
    },
    "card-delete": function () {
      var card = findCard(state.view.cardId);
      if (card) {
        // Statements already entered stay as ordinary one-time transactions.
        state.rows = state.rows.filter(function (r) { return r !== card; });
        state.rows.forEach(function (r) { if (r.card === card.id) r.card = ""; });
        flash("Deleted " + card.description + ".");
      }
      go({ name: "transactions" });
    },
    statement: function (form) {
      var card = findCard(state.view.cardId);
      if (!card) return go({ name: "transactions" });
      var due = Number(val(form, "due")), text = val(form, "amount"), cents = E.parseMoney(text);
      if (cents === null || cents <= 0 || E.openDueDates(state.rows, card, state.today).indexOf(due) < 0)
        return go({ name: "card", cardId: card.id, statementAmount: text, errors: { statement: "Enter the statement balance, like 1461.05." } });
      var row = E.Row(E.newId(), "onetime", due, card.description + " payment", "creditcard", -cents);
      row.card = card.id;
      state.rows.push(row);
      flash("Saved the " + card.description + " statement: " + E.money(cents) + " due " + E.fmtDate(due) + ".");
      go({ name: "transactions" });
    },
    appearance: function (form) {
      var theme = form.querySelector('input[name="theme"]:checked'), mode = form.querySelector('input[name="mode"]:checked');
      var found = theme && E.THEMES.filter(function (t) { return t[0] === theme.value; })[0];
      if (!found || !mode || !E.MODES[mode.value]) { flash("Pick a theme and light, dark, or match device.", "error"); return go({ name: "appearance" }); }
      state.theme = found[0]; state.mode = mode.value;
      flash("Theme set to " + found[1] + ", " + E.MODES[mode.value].toLowerCase() + ".");
      go({ name: "appearance" });
    },
    login: function (form) {
      if (val(form, "password") === PASSWORD || form.elements.password.value === PASSWORD) { state.authed = true; return go({ name: "overview" }); }
      var button = form.querySelector("button");
      button.disabled = true;                      // the server waits a second on a wrong password
      setTimeout(function () { go({ name: "login", error: "That password isn't right." }); }, 1000);
    },
    logout: function () { state.authed = false; go({ name: "login" }); },
    setup: function (form) {
      var f = { balance: val(form, "balance"), date: val(form, "date"), pay: val(form, "pay"), pay_date: val(form, "pay_date") };
      var errors = {}, balance = E.parseMoney(f.balance, true), day = E.parseISO(f.date);
      var pay = f.pay ? E.parseMoney(f.pay) : null, payDay = f.pay_date ? E.parseISO(f.pay_date) : null;
      if (balance === null) errors.balance = "Enter your current balance, like 3200.00.";
      if (day === null) errors.date = "Pick the date that balance is from.";
      else if (day > state.today) errors.date = "The balance date can't be in the future.";
      if (f.pay && (pay === null || pay <= 0)) errors.pay = "Enter your take-home pay, like 2808.99.";
      if (pay && payDay === null) errors.pay_date = "Pick your next payday.";
      if (Object.keys(errors).length) return go({ name: "setup", form: f, errors: errors });
      state.rows.push(E.Row(E.newId(), "balance", day, "Starting balance", "", balance));
      if (pay) state.rows.push(E.Row(E.newId(), "recurring", payDay, "Paycheck", "income", pay, "biweekly"));
      flash("You're set up. Add your bills and card payments next.");
      go({ name: "overview" });
    },
    tx: function (form) {
      var v = state.view, row = v.rowId ? findRow(v.rowId) : null, kind = row ? row.type : v.kind;
      var read = readTxForm(form, kind);
      if (!read.values) return go({ name: "txform", kind: kind, rowId: v.rowId, form: read.form, errors: read.errors });
      var x = read.values;
      if (row) {
        row.description = x.description; row.category = x.category; row.date = x.date; row.amount = x.amount; row.frequency = x.frequency;
        row.estimate = "";      // saving an assumed estimate means you've corrected it
        flash("Saved " + x.description + ".");
      } else {
        state.rows.push(E.Row(E.newId(), kind, x.date, x.description, x.category, x.amount, x.frequency));
        flash("Added " + x.description + ".");
      }
      go({ name: "transactions" });
    },
    "tx-pause": function () {
      var row = findRow(state.view.rowId);
      if (!row) return go({ name: "transactions" });
      row.status = row.status === "paused" ? "active" : "paused";
      flash(row.description + " is " + (row.status === "paused" ? "paused" : "back on") + ".");
      go({ name: "transactions" });
    },
    "tx-delete": function () {
      var row = findRow(state.view.rowId);
      if (row) { state.rows = state.rows.filter(function (r) { return r !== row; }); flash("Deleted " + row.description + "."); }
      go({ name: "transactions" });
    },
    balance: function (form) {
      var day = E.parseISO(val(form, "date")), text = val(form, "balance");
      var actual = text ? E.parseMoney(text, true) : null;
      if (day === null) flash("Pick the date for this balance.", "error");
      else if (text && actual === null) flash("Enter the balance as a number, like 3200.00.", "error");
      else {
        try {
          var out = E.takeSnapshot(state.rows, day, state.today, actual);
          state.rows = out.rows;
          flash("Balance updated to " + E.money(out.row.amount) + " as of " + E.fmtDate(out.row.date) + ".");
        } catch (e) { flash(e.message, "error"); }
      }
      go({ name: "overview" });
    },
    "balance-undo": function () {
      try { state.rows = E.undoSnapshot(state.rows); flash("Removed the latest balance update."); }
      catch (e) { flash(e.message, "error"); }
      go({ name: "history" });
    },
    upload: function (form) {
      readFile(form, function (text, error) {
        var errors = error ? [error] : [], rows = [];
        if (text !== null) { var parsed = E.parseLedgerCsv(text); rows = parsed.rows; errors = parsed.errors; }
        if (errors.length) return go({ name: "history", uploadErrors: errors.slice(0, 20), moreErrors: Math.max(0, errors.length - 20) });
        state.rows = rows;
        flash("Replaced your ledger with " + rows.length + " rows from the upload.");
        go({ name: "history" });
      });
    },
    "nw-record": function (form) {
      var day = E.parseISO(val(form, "date"));
      if (day === null) { flash("Pick the date for these balances.", "error"); return go({ name: "networth" }); }
      if (day > state.today) { flash("Balances can't be recorded for a future date.", "error"); return go({ name: "networth" }); }
      var names = form.querySelectorAll('input[name="account"]'), amounts = form.querySelectorAll('input[name="amount"]');
      var entries = {}, bad = [], count = 0;
      for (var i = 0; i < names.length && i < amounts.length; i++) {
        var text = amounts[i].value;
        if (!text.trim()) continue;
        var account = E.findAccount(state.book, names[i].value), value = E.parseMoney(text, true);
        if (!account) continue;
        if (value === null) bad.push(account.name); else { entries[account.name] = value; count++; }
      }
      if (bad.length) flash("Enter amounts as numbers, like 1520.00 (check " + bad.join(", ") + ").", "error");
      else if (!count) flash("Fill in at least one account.", "error");
      else {
        state.book = E.record(state.book, day, entries);
        flash("Saved " + count + " balance" + (count !== 1 ? "s" : "") + " for " + E.fmtDate(day) + ".");
      }
      go({ name: "networth" });
    },
    "nw-add-account": function (form) {
      var checked = form.querySelector('input[name="kind"]:checked');
      var f = { name: val(form, "name"), kind: checked ? checked.value : "" };
      try { state.book = E.addAccount(state.book, f.name, f.kind); }
      catch (e) { return go({ name: "networth", accountErrors: { name: e.message }, accountForm: f }); }
      flash("Added " + E.cleanText(f.name) + ".");
      go({ name: "networth" });
    },
    "nw-edit-account": function (form) {
      var checked = form.querySelector('input[name="kind"]:checked'), name = form.elements.name.value;
      try {
        state.book = E.editAccount(state.book, state.view.accountName, name, checked ? checked.value : "", form.elements.status.checked ? "hidden" : "active");
      } catch (e) { return go({ name: "account", accountName: state.view.accountName, error: e.message }); }
      flash("Saved " + E.cleanText(name) + ".");
      go({ name: "networth" });
    },
    "nw-delete-account": function () {
      var account = E.findAccount(state.book, state.view.accountName);
      if (account) { state.book = E.deleteAccount(state.book, account.name); flash("Deleted " + account.name + " and its history."); }
      go({ name: "networth" });
    },
    "nw-delete-date": function (form) {
      var day = Number(form.getAttribute("data-day"));
      state.book = E.deleteDate(state.book, day);
      flash("Removed the balances from " + E.fmtDate(day) + ".");
      go({ name: "networth" });
    },
    "nw-upload": function (form) {
      readFile(form, function (text, error) {
        var errors = error ? [error] : [], book = null;
        if (text !== null) { var parsed = E.parseNetworthCsv(text); book = parsed.book; errors = parsed.errors; }
        if (errors.length) return go({ name: "networth", uploadErrors: errors.slice(0, 20) });
        state.book = book;
        flash("Replaced your net worth file with " + book.accounts.length + " accounts and " + book.values.length + " balances.");
        go({ name: "networth" });
      });
    }
  };

  document.addEventListener("submit", function (e) {
    var form = e.target, name = form.getAttribute && form.getAttribute("data-action");
    if (!name) return;
    e.preventDefault();
    var run = function () { actions[name](form); };
    var message = form.getAttribute("data-confirm");
    if (message) confirmDialog(message, run); else run();
  });

  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest("a, [data-demo]") : null;
    if (!a) return;
    var demo = a.getAttribute("data-demo");
    if (demo) {
      if (demo === "reset") { loadSample(); state.authed = true; state.horizon = "1y"; flash("Sample data restored."); go({ name: "overview" }); }
      if (demo === "empty") { state.rows = []; state.whatIf = null; state.book = { accounts: [], values: [] }; state.authed = true; go({ name: "setup" }); }
      return;
    }
    if (!root.contains(a)) return;
    if (a.hasAttribute("data-horizon")) { e.preventDefault(); state.horizon = a.getAttribute("data-horizon"); return go({ name: "overview" }); }
    if (a.hasAttribute("data-go")) { e.preventDefault(); return go({ name: a.getAttribute("data-go") }); }
    if (a.hasAttribute("data-new")) { e.preventDefault(); return go({ name: "txform", kind: a.getAttribute("data-new") }); }
    if (a.hasAttribute("data-edit")) { e.preventDefault(); return go({ name: "txform", rowId: a.getAttribute("data-edit") }); }
    if (a.hasAttribute("data-help")) { e.preventDefault(); return go({ name: "help", anchor: a.getAttribute("data-help") }); }
    if (a.hasAttribute("data-pay")) { e.preventDefault(); return go({ name: "pay", payId: a.getAttribute("data-pay") }); }
    if (a.hasAttribute("data-card")) { e.preventDefault(); return go({ name: "card", cardId: a.getAttribute("data-card") }); }
    if (a.hasAttribute("data-whatif")) {
      e.preventDefault();
      var w = state.whatIf;
      state.whatIf = null;
      if (a.getAttribute("data-whatif") === "keep" && w) {
        return go({ name: "txform", kind: "onetime", form: { description: "", direction: w.cents > 0 ? "in" : "out", amount: E.fixed2(w.cents),
                                                            category: w.cents > 0 ? "income" : "bill", date: E.iso(w.date), frequency: "monthly" } });
      }
      return go({ name: "overview" });
    }
    if (a.hasAttribute("data-account")) { e.preventDefault(); return go({ name: "account", accountName: a.getAttribute("data-account") }); }
    if (a.hasAttribute("data-download")) {
      e.preventDefault();
      var which = a.getAttribute("data-download"), stamp = E.iso(state.today);
      if (which === "ledger") csvDialog("checking-ledger-" + stamp + ".csv", E.toCsvText(state.rows));
      else csvDialog("net-worth-" + stamp + ".csv", E.networthCsvText(state.book));
    }
  });

  // Theme page: show a choice as soon as it's picked. Save keeps it.
  document.addEventListener("change", function (e) {
    var form = e.target.closest ? e.target.closest("form[data-theme-form]") : null;
    if (!form) return;
    var theme = form.querySelector('input[name="theme"]:checked'), mode = form.querySelector('input[name="mode"]:checked');
    if (theme) document.documentElement.setAttribute("data-theme", theme.value);
    if (mode) document.documentElement.setAttribute("data-mode", mode.value);
  });

  window.addEventListener("hashchange", function () {
    var name = location.hash.slice(1), current = PAGES[state.view.name][1];
    for (var key in HASH) if (HASH[key] === name && key !== current) return go({ name: key });
  });

  loadSample();
  var start = location.hash.slice(1);
  for (var key in HASH) if (HASH[key] === start) state.view = { name: key };
  render();
})();
