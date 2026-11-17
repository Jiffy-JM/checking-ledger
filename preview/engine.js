// Checking Ledger engine, ported from ledger_core.py, networth.py and the
// formatting/chart helpers in app.py. Money is integer cents; dates are whole
// day numbers (days since 1970-01-01), so nothing drifts with time zones.
var Engine = (function () {
  "use strict";

  var TYPES = ["balance", "recurring", "onetime", "card", "pay"];
  var PAY_FREQUENCIES = ["weekly", "biweekly", "monthly"];
  // Weeks in one pay period as a fraction (monthly is 52/12).
  var PAY_WEEKS = { weekly: [1, 1], biweekly: [2, 1], monthly: [52, 12] };
  var PAY_SPAN = { weekly: 7, biweekly: 14, monthly: 31 };   // days in one pay period, at most
  var ASSUMED = "assumed";   // a one-time row that was an estimate when its balance period closed
  var ESTIMATES = { average: "Recent statements", fixed: "A set amount" };
  var CATEGORIES = { income: "Income", bill: "Bill", creditcard: "Credit card", transfer: "Transfer", investment: "Investment" };
  var FREQUENCIES = { weekly: "Weekly", biweekly: "Every 2 weeks", monthly: "Monthly", annually: "Yearly" };
  var KINDS = { asset: "Asset", debt: "Debt" };
  var TYPE_ALIASES = { balance: "balance", recurring: "recurring", onetime: "onetime", "one-time": "onetime", "one time": "onetime", card: "card", "credit card": "card",
                       pay: "pay", "hourly pay": "pay" };
  var FREQ_ALIASES = { "bi-weekly": "biweekly", "every two weeks": "biweekly", annual: "annually", yearly: "annually" };
  var KIND_ALIASES = { liability: "debt", loan: "debt", assets: "asset", debts: "debt" };
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // The same list as themes.py: [key, name, description]. Colors are in app.css.
  var THEMES = [
    ["sage", "Sage", "The original: sage paper and green"],
    ["indigo", "Indigo", "Blue-purple on near-black"],
    ["violet", "Violet", "Purple on near-black"],
    ["neon", "Electric Purple", "Vivid purple, strongest glow"],
    ["orchid", "Orchid", "Purple-pink"],
    ["ocean", "Ocean", "Black and cyan"],
    ["gold", "Amethyst Gold", "Purple-black with a warm gold accent"],
    ["synth", "Synthwave", "Deep violet, hot pink and cyan"],
    ["teal", "Nightshade", "Cool near-black with teal and a violet dot"],
    ["ember", "Ember Violet", "Plum-black with orange and rose"],
    ["mist", "Lavender Mist", "Soft, low-glare pastel lavender on charcoal"],
    ["ultra", "Ultraviolet", "Rich purple backgrounds instead of black"],
    ["ink", "Mono Ink", "Minimal black and white with one violet touch"],
    ["grape", "Grape Soda", "Dark grape with a lime accent"]
  ];
  var MODES = {"auto": "Match device", "light": "Light", "dark": "Dark"};
  var HORIZONS = {
    "2w": ["2W", "2 weeks", ["days", 14]],
    "1m": ["1M", "1 month", ["months", 1]],
    "3m": ["3M", "3 months", ["months", 3]],
    "6m": ["6M", "6 months", ["months", 6]],
    "1y": ["1Y", "1 year", ["months", 12]]
  };

  // ------------------------------------------------------------------ dates
  function D(y, m, d) { return Math.round(Date.UTC(y, m - 1, d) / 864e5); }
  function parts(n) {
    var t = new Date(n * 864e5);
    return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
  }
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  function iso(n) { var p = parts(n); return p.y + "-" + pad(p.m) + "-" + pad(p.d); }
  function validDate(y, m, d) {
    if (m < 1 || m > 12 || d < 1 || d > 31 || y < 1 || y > 9999) return null;
    var n = D(y, m, d), p = parts(n);
    return p.y === y && p.m === m && p.d === d ? n : null;
  }
  function parseISO(text) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(text || "").trim());
    return m ? validDate(+m[1], +m[2], +m[3]) : null;
  }
  function daysInMonth(y, m) { return parts(D(y, m + 1, 0)).d; }
  function addMonths(n, months) {
    var p = parts(n), index = p.m - 1 + months;
    var year = p.y + Math.floor(index / 12), month = ((index % 12) + 12) % 12 + 1;
    return D(year, month, Math.min(p.d, daysInMonth(year, month)));
  }
  function fmtDate(n, year) {
    var p = parts(n);
    return year === false ? MONTHS[p.m - 1] + " " + p.d : MONTHS[p.m - 1] + " " + p.d + ", " + p.y;
  }
  function todayNumber() { var t = new Date(); return D(t.getFullYear(), t.getMonth() + 1, t.getDate()); }

  // ------------------------------------------------------------------ money
  function divRound(n, d) {             // round half away from zero, integers in and out
    var sign = (n < 0) !== (d < 0) ? -1 : 1;
    n = Math.abs(n); d = Math.abs(d);
    var whole = Math.floor(n / d), rest = n - whole * d;
    return sign * (rest * 2 >= d ? whole + 1 : whole);
  }
  function commas(digits) { return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ","); }
  function fixed2(cents) { var a = Math.abs(cents); return Math.floor(a / 100) + "." + pad(a % 100); }
  function money(cents, signed) {
    if (cents === null || cents === undefined) return "";
    var a = Math.abs(cents), text = "$" + commas(String(Math.floor(a / 100))) + "." + pad(a % 100);
    if (cents < 0) return "−" + text;
    return signed && cents > 0 ? "+" + text : text;
  }
  function stripZeros(text) { return text.replace(/0+$/, "").replace(/\.$/, ""); }
  function moneyShort(value) {
    var sign = value < 0 ? "−" : "";
    value = Math.abs(value);
    function grouped(v, digits) { var s = v.toFixed(digits).split("."); return commas(s[0]) + (s[1] ? "." + s[1] : ""); }
    if (value >= 1e6) return stripZeros(sign + "$" + grouped(value / 1e6, 2)) + "M";
    if (value >= 1000) return sign + "$" + stripZeros(grouped(value / 1000, 1)) + "k";
    return sign + "$" + grouped(value, 0);
  }

  // ------------------------------------------------------- tolerant parsing
  function cleanText(text) {
    var out = String(text === null || text === undefined ? "" : text).split(/\s+/).filter(Boolean).join(" ").slice(0, 80);
    return out.replace(/^[=+\-@]+/, "").trim();
  }
  function parseDateText(text) {
    text = String(text === null || text === undefined ? "" : text).trim();
    if (!text) throw new Error("the date is empty");
    var m, n = null, tries = [];
    if ((m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(text))) tries.push([+m[1], +m[2], +m[3]]);
    if ((m = /^(\d{1,2})\/(\d{1,2})\/(\d{2})$/.exec(text))) tries.push([+m[3] + (+m[3] >= 69 ? 1900 : 2000), +m[1], +m[2]]);
    if ((m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(text))) tries.push([+m[3], +m[1], +m[2]]);
    if ((m = /^(\d{4})\/(\d{1,2})\/(\d{1,2})$/.exec(text))) tries.push([+m[1], +m[2], +m[3]]);
    if ((m = /^(\d{1,2})-(\d{1,2})-(\d{4})$/.exec(text))) tries.push([+m[3], +m[1], +m[2]]);
    for (var i = 0; i < tries.length; i++) {
      n = validDate(tries[i][0], tries[i][1], tries[i][2]);
      if (n !== null && tries[i][0] >= 1900 && tries[i][0] <= 2200) return n;
    }
    throw new Error("'" + text + "' isn't a date like 2026-10-06 or 10/6/2026");
  }
  function parseAmountText(text) {
    var raw = String(text === null || text === undefined ? "" : text).trim();
    var cleaned = raw.replace(/−/g, "-").replace(/[$, ]/g, "");
    var negative = cleaned.charAt(0) === "(" && cleaned.charAt(cleaned.length - 1) === ")";
    if (negative) cleaned = cleaned.slice(1, -1);
    if (!cleaned) throw new Error("the amount is empty");
    var m = /^([+-]?)(\d*)(?:\.(\d*))?$/.exec(cleaned);
    if (!m || (!m[2] && !m[3])) throw new Error("'" + raw + "' isn't an amount like -120.50");
    var whole = m[2] || "0", frac = (m[3] || "") + "000";
    if (whole.replace(/^0+/, "").length > 9) throw new Error("'" + raw + "' isn't an amount like -120.50");
    var cents = parseInt(whole, 10) * 100 + parseInt(frac.slice(0, 2), 10) + (frac.charAt(2) >= "5" ? 1 : 0);
    if (m[1] === "-") cents = -cents;
    if (negative) cents = -cents;
    return cents === 0 ? 0 : cents;
  }
  function lookup(text, mapping, aliases) {
    var key = String(text === null || text === undefined ? "" : text).trim().toLowerCase();
    if (Object.prototype.hasOwnProperty.call(mapping, key)) return key;
    for (var k in mapping) if (key === mapping[k].toLowerCase()) return k;
    return aliases && Object.prototype.hasOwnProperty.call(aliases, key) ? aliases[key] : null;
  }
  function parseMoney(text, allowNegative) {
    if (!String(text || "").trim()) return null;
    var value;
    try { value = parseAmountText(text); } catch (e) { return null; }
    return value < 0 && !allowNegative ? null : value;
  }

  // -------------------------------------------------------------------- CSV
  function parseCsv(text) {
    var rows = [], row = [], field = "", quoted = false, i = 0, c;
    text = String(text).replace(/^﻿/, "");
    while (i < text.length) {
      c = text.charAt(i);
      if (quoted) {
        if (c === '"') {
          if (text.charAt(i + 1) === '"') { field += '"'; i += 2; continue; }
          quoted = false; i++; continue;
        }
        field += c; i++; continue;
      }
      if (c === '"') { quoted = true; i++; continue; }
      if (c === ",") { row.push(field); field = ""; i++; continue; }
      if (c === "\r" || c === "\n") {
        if (c === "\r" && text.charAt(i + 1) === "\n") i++;
        row.push(field); rows.push(row); row = []; field = ""; i++; continue;
      }
      field += c; i++;
    }
    if (field !== "" || row.length) { row.push(field); rows.push(row); }
    return rows;
  }
  // [{line, raw}] with lower-cased header names; blank lines skipped.
  function readCsvDicts(text) {
    var lines = parseCsv(text), out = { header: null, items: [] };
    if (!lines.length) return out;
    var header = lines[0].map(function (h) { return h.trim().toLowerCase(); });
    for (var i = 1; i < lines.length; i++) {
      var values = lines[i];
      if (!values.some(function (v) { return v.trim(); })) continue;
      var raw = {};
      for (var j = 0; j < header.length && j < values.length; j++) raw[header[j]] = values[j];
      out.header = header;
      out.items.push({ line: i + 1, raw: raw });
    }
    return out;
  }
  function csvField(value) {
    value = String(value);
    return /[",\r\n]/.test(value) ? '"' + value.replace(/"/g, '""') + '"' : value;
  }
  function csvLine(values) { return values.map(csvField).join(",") + "\r\n"; }

  // ------------------------------------------------------------------- rows
  var CARD_DATE = D(2000, 1, 1);   // card rows have no date of their own; this keeps sorting simple
  function newId() {
    var out = "";
    for (var i = 0; i < 12; i++) out += Math.floor(Math.random() * 16).toString(16);
    return out;
  }
  function Row(id, type, date, description, category, amount, frequency, status) {
    return { id: id, type: type, date: date, description: description || "", category: category || "",
             amount: amount || 0, frequency: frequency || "", status: status || "active",
             card: "", closeDay: 0, dueDay: 0, estimate: "",    // see "credit cards" below
             pay: "", hours: 0, rate: 0, percent: 0 };          // see "hourly pay": hours and percent in hundredths, rate in cents
  }
  function isActive(r) { return r.status !== "paused"; }
  function get(raw, key) { var v = raw[key]; return v === undefined || v === null ? "" : v; }

  function rowFromDict(raw, strict) {
    var typeMap = {}; TYPES.forEach(function (t) { typeMap[t] = t; });
    var rtype = lookup(raw.type, typeMap, TYPE_ALIASES);
    if (rtype === null) throw new Error("type '" + get(raw, "type") + "' should be balance, recurring, onetime, or card");
    if (rtype === "card") return cardFromDict(raw, strict);
    if (rtype === "pay") return payFromDict(raw, strict);
    var day = parseDateText(raw.date), amount = parseAmountText(raw.amount), freq = "";
    if (rtype === "recurring") {
      freq = lookup(raw.frequency, FREQUENCIES, FREQ_ALIASES);
      if (freq === null) throw new Error("frequency '" + get(raw, "frequency") + "' should be weekly, biweekly, monthly, or annually");
    }
    var category = "";
    if (rtype !== "balance") {
      category = lookup(raw.category, CATEGORIES);
      if (category === null) {
        if (strict && String(get(raw, "category")).trim())
          throw new Error("category '" + raw.category + "' should be one of: " + Object.keys(CATEGORIES).join(", "));
        category = "bill";
      }
    }
    var status = String(get(raw, "status")).trim().toLowerCase() === "paused" ? "paused" : "active";
    var rid = String(get(raw, "id")).trim().slice(0, 40) || newId();
    var description = cleanText(raw.description);
    if (rtype !== "balance" && !description) {
      if (strict) throw new Error("the description is empty");
      description = "Untitled";
    }
    var row = Row(rid, rtype, day, description, category, amount, freq, status);
    if (rtype !== "onetime") return row;
    if (String(get(raw, "hours")).trim()) {
      try { row.hours = numberIn(raw.hours, "hours", 0, 744, "the hours worked, like 80"); }
      catch (e) { if (strict) throw e; }
    }
    row.card = cleanId(raw.card); row.pay = cleanId(raw.pay);
    row.estimate = String(get(raw, "estimate")).trim().toLowerCase() === ASSUMED ? ASSUMED : "";
    return row;
  }
  function cleanId(text) {
    text = String(text === null || text === undefined ? "" : text).trim();
    return /^[A-Za-z0-9_-]{1,40}$/.test(text) ? text : "";
  }
  // 1250 -> "12.5", 4000 -> "40" (hundredths to a plain number).
  function plain(hundredths) {
    var text = fixed2(hundredths);
    return text.replace(/0+$/, "").replace(/\.$/, "");
  }
  // A plain number for the hours, rate, and percent columns, returned in hundredths.
  function numberIn(text, column, low, high, example) {
    var value = null;
    try { value = parseAmountText(text); } catch (e) { value = null; }
    if (value === null || !(value > low * 100 && value <= high * 100))
      throw new Error(column + " '" + String(text === null || text === undefined ? "" : text).trim() + "' should be " + example);
    return value;
  }
  // An hourly pay row: description is its name, date is any payday,
  // frequency is how often it is paid.
  function payFromDict(raw, strict) {
    var name = cleanText(raw.description);
    if (!name) {
      if (strict) throw new Error("the pay's name (description) is empty");
      name = "Paycheck";
    }
    var payday = parseDateText(raw.date);
    var freq = lookup(raw.frequency, FREQUENCIES, FREQ_ALIASES);
    if (PAY_FREQUENCIES.indexOf(freq) < 0) throw new Error("frequency '" + get(raw, "frequency") + "' should be weekly, biweekly, or monthly");
    var hours = numberIn(raw.hours, "hours", 0, 168, "the hours in a usual week, like 40");
    var rate = numberIn(raw.rate, "rate", 0, 100000, "an hourly rate, like 25.00");
    var percent = String(get(raw, "percent")).trim() ? numberIn(raw.percent, "percent", 0, 100, "between 1 and 100") : 0;
    var status = String(get(raw, "status")).trim().toLowerCase() === "paused" ? "paused" : "active";
    var row = Row(cleanId(raw.id) || newId(), "pay", payday, name, "", 0, freq, status);
    row.hours = hours; row.rate = rate; row.percent = percent;
    return row;
  }
  function dayOfMonth(text, column) {
    text = String(text === null || text === undefined ? "" : text).trim();
    if (!/^\d{1,2}$/.test(text) || Number(text) < 1 || Number(text) > 31)
      throw new Error(column + " '" + text + "' should be a day of the month from 1 to 31");
    return Number(text);
  }
  // A credit card row: description is the card's name, amount is the set
  // amount to estimate with (0 for none).
  function cardFromDict(raw, strict) {
    var name = cleanText(raw.description);
    if (!name) {
      if (strict) throw new Error("the card's name (description) is empty");
      name = "Card";
    }
    var closeDay = dayOfMonth(raw.close_day, "close_day"), dueDay = dayOfMonth(raw.due_day, "due_day");
    var estimate = lookup(raw.estimate, ESTIMATES);
    if (estimate === null) {
      if (strict && String(get(raw, "estimate")).trim()) throw new Error("estimate '" + raw.estimate + "' should be average or fixed");
      estimate = "average";
    }
    var amount = String(get(raw, "amount")).trim() ? Math.abs(parseAmountText(raw.amount)) : 0;
    var status = String(get(raw, "status")).trim().toLowerCase() === "paused" ? "paused" : "active";
    var rid = String(get(raw, "id")).trim();
    if (!/^[A-Za-z0-9_-]{1,40}$/.test(rid)) rid = newId();
    var row = Row(rid, "card", CARD_DATE, name, "", amount, "", status);
    row.closeDay = closeDay; row.dueDay = dueDay; row.estimate = estimate;
    return row;
  }

  // Strict parse for uploads: {rows, errors}. Any error rejects the upload.
  function parseLedgerCsv(text) {
    var read = readCsvDicts(text), rows = [], errors = [], seen = {};
    read.items.forEach(function (item) {
      var row;
      try { row = rowFromDict(item.raw, true); }
      catch (e) { errors.push("Row " + item.line + ": " + e.message + "."); return; }
      if (seen[row.id]) row.id = newId();
      seen[row.id] = true;
      rows.push(row);
    });
    if (read.header === null) return { rows: [], errors: ["The file is empty."] };
    var missing = ["type", "date", "amount"].filter(function (c) { return read.header.indexOf(c) < 0; });
    if (missing.length) return { rows: [], errors: ["The first row needs these column names: " + missing.join(", ") + "."] };
    if (!errors.length && !rows.some(function (r) { return r.type === "balance"; }))
      errors.push("The file needs at least one balance row so projections have a starting point.");
    return { rows: rows, errors: errors };
  }

  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  function toCsvText(rows) {
    var sorted = rows.slice().sort(function (a, b) {
      return cmp(TYPES.indexOf(a.type), TYPES.indexOf(b.type)) || cmp(a.date, b.date) ||
             cmp(a.description.toLowerCase(), b.description.toLowerCase()) || cmp(a.id, b.id);
    });
    var out = csvLine(["id", "type", "date", "description", "category", "amount", "frequency", "status",
                       "card", "close_day", "due_day", "estimate", "pay", "hours", "rate", "percent"]);
    sorted.forEach(function (r) {
      out += csvLine([r.id, r.type, r.type === "card" ? "" : iso(r.date), r.description, r.category,
                      (r.amount < 0 ? "-" : "") + fixed2(r.amount), r.frequency, r.status,
                      r.card || "", r.closeDay || "", r.dueDay || "", r.estimate || "",
                      r.pay || "", r.hours ? plain(r.hours) : "", r.rate ? fixed2(r.rate) : "", r.percent ? plain(r.percent) : ""]);
    });
    return out;
  }

  // -------------------------------------------------------------- date math
  // Dates a recurring row lands on within [start, end]. Monthly/yearly dates
  // are computed from the original date, so the 31st never drifts.
  function occurrences(row, start, end) {
    if (end < start) return [];
    var anchorDay = row.date, out = [], day;
    if (row.frequency === "weekly" || row.frequency === "biweekly") {
      var step = row.frequency === "weekly" ? 7 : 14, first = anchorDay;
      if (anchorDay < start) first = anchorDay + Math.ceil((start - anchorDay) / step) * step;
      for (day = first; day <= end; day += step) out.push(day);
      return out;
    }
    var stride = row.frequency === "annually" ? 12 : 1, n = 0;
    if (anchorDay < start) {
      var a = parts(anchorDay), s = parts(start);
      var monthsApart = (s.y - a.y) * 12 + (s.m - a.m);
      n = Math.max(0, Math.floor(monthsApart / stride) - 1);
      while (addMonths(anchorDay, n * stride) < start) n++;
    }
    while ((day = addMonths(anchorDay, n * stride)) <= end) { out.push(day); n++; }
    return out;
  }
  function nextOccurrence(row, fromDay) {
    var hits = occurrences(row, fromDay, addMonths(fromDay, 13));
    return hits.length ? hits[0] : null;
  }

  // ----------------------------------------------------------------- events
  function eventsIn(rows, start, end) {
    if (end < start) return [];
    var out = [];
    rows.forEach(function (r) {
      if (!isActive(r)) return;
      if (r.type === "recurring") {
        occurrences(r, start, end).forEach(function (day) {
          out.push({ date: day, description: r.description, category: r.category, amount: r.amount, rowId: r.id, recurring: true,
                     estimated: false, whatIf: false });
        });
      } else if (r.type === "onetime" && start <= r.date && r.date <= end) {
        out.push({ date: r.date, description: r.description, category: r.category, amount: r.amount, rowId: r.id, recurring: false,
                   estimated: !!r.estimated, whatIf: !!r.whatIf });
      }
    });
    out.sort(function (a, b) {
      return cmp(a.date, b.date) || cmp(a.amount < 0 ? 1 : 0, b.amount < 0 ? 1 : 0) ||
             cmp(a.description.toLowerCase(), b.description.toLowerCase());
    });
    return out;
  }
  function total(events) { return events.reduce(function (sum, e) { return sum + e.amount; }, 0); }

  // --------------------------------------------------------------- balances
  function balances(rows) {
    return rows.filter(function (r) { return r.type === "balance"; }).sort(function (a, b) { return cmp(a.date, b.date); });
  }
  function anchor(rows) { var found = balances(rows); return found.length ? found[found.length - 1] : null; }
  // Balance at the start of `day`, before anything dated that day.
  function startOfDay(rows, day) {
    var base = null;
    balances(rows).forEach(function (b) { if (b.date <= day) base = b; });
    if (base === null) return null;
    return base.amount + total(eventsIn(rows, base.date, day - 1));
  }
  function endOfDay(rows, day) {
    var start = startOfDay(rows, day);
    return start === null ? null : start + total(eventsIn(rows, day, day));
  }
  function horizonEnd(origin, span) { return span[0] === "days" ? origin + span[1] : addMonths(origin, span[1]); }

  function project(rows, today, span) {
    var base = anchor(rows);
    if (base === null) return null;
    var origin = Math.max(today, base.date);
    var originBalance = startOfDay(rows, origin);
    var end = horizonEnd(origin, span);
    var events = eventsIn(rows, origin, end);
    var points = [{ date: origin, balance: originBalance, events: [] }];
    var running = originBalance, i = 0;
    while (i < events.length) {
      var group = [], day = events[i].date;
      while (i < events.length && events[i].date === day) group.push(events[i++]);
      running += total(group);
      points.push({ date: day, balance: running, events: group });
    }
    var low = points[0];
    points.forEach(function (p) { if (p.balance < low.balance) low = p; });
    return { origin: origin, end: end, originBalance: originBalance, endBalance: running, low: low, points: points, events: events };
  }

  // Totals by category over the next 12 months, with monthly averages.
  function cashFlow(rows, today) {
    var base = anchor(rows);
    if (base === null) return { lines: [], net: 0 };
    var origin = Math.max(today, base.date), sums = {};
    eventsIn(rows, origin, addMonths(origin, 12) - 1).forEach(function (e) {
      sums[e.category] = (sums[e.category] || 0) + e.amount;
    });
    var lines = [], net = 0;
    Object.keys(CATEGORIES).forEach(function (key) {
      if (!sums[key]) return;
      lines.push({ key: key, label: CATEGORIES[key], yearly: sums[key], monthly: divRound(sums[key], 12) });
      net += sums[key];
    });
    return { lines: lines, net: net };
  }

  // ----------------------------------------------------------- credit cards
  // A card has a statement closing day and a payment due day. Every due date
  // from the latest balance onward gets a payment: the amount you entered for
  // that statement if there is one, otherwise an estimate.
  //
  // Estimates are never written to the file while they are estimates. When
  // you update your balance, the estimates dated before it are saved as
  // ordinary one-time rows marked "assumed", so history never changes later.
  function cards(rows) { return rows.filter(function (r) { return r.type === "card"; }); }
  function clampDay(y, m, day) { return D(y, m, Math.min(day, daysInMonth(y, m))); }
  function dueDates(card, start, end) {
    var out = [], p = parts(start), y = p.y, m = p.m, day;
    while ((day = clampDay(y, m, card.dueDay)) <= end) {
      if (day >= start) out.push(day);
      m++; if (m > 12) { m = 1; y++; }
    }
    return out;
  }
  function closeBefore(card, due) {                 // the closing date that leads to this due date
    var p = parts(due), close = clampDay(p.y, p.m, card.closeDay);
    if (close >= due) { var q = parts(addMonths(D(p.y, p.m, 1), -1)); close = clampDay(q.y, q.m, card.closeDay); }
    return close;
  }
  // The payments recorded for a card (entered or assumed), oldest first.
  function cardStatements(rows, card) {
    return rows.filter(function (r) { return r.type === "onetime" && r.card === card.id && !r.estimated; })
               .sort(function (a, b) { return cmp(a.date, b.date); });
  }
  // The candidate date closest to `day` (the earlier one on a tie), or null.
  function nearest(day, candidates) {
    var best = null;
    candidates.forEach(function (d) { if (best === null || Math.abs(d - day) < Math.abs(best - day)) best = d; });
    return best;
  }
  // {due date: the statement recorded for it}. Each statement counts for the
  // due date nearest to it, so one paid a few days early or late, even across
  // a month end, still replaces the right estimate and no other.
  function coveredDues(statements, card) {
    var out = {};
    statements.forEach(function (r) {
      var due = nearest(r.date, dueDates(card, r.date - 31, r.date + 31));
      if (due !== null && !(due in out)) out[due] = r;
    });
    return out;
  }
  function statementFor(rows, card, due) { return coveredDues(cardStatements(rows, card), card)[due] || null; }
  // {cents, basis, count}: a set amount, or the average of the last six statements you entered.
  function cardEstimate(rows, card) {
    var fixed = card.amount > 0 ? { cents: card.amount, basis: "fixed", count: 0 } : null;
    if (card.estimate === "fixed") return fixed;
    var recent = cardStatements(rows, card).filter(function (r) { return isActive(r) && r.estimate !== ASSUMED; }).slice(-6);
    if (!recent.length) return fixed;
    var sum = recent.reduce(function (n, r) { return n - r.amount; }, 0);
    return { cents: divRound(sum, recent.length), basis: "average", count: recent.length };
  }
  function cardForecast(rows, start, end) {
    var out = [];
    cards(rows).forEach(function (card) {
      if (!isActive(card)) return;
      var est = cardEstimate(rows, card);
      if (!est) return;
      var taken = coveredDues(cardStatements(rows, card), card);
      dueDates(card, start, end).forEach(function (due) {
        if (due in taken) return;
        var row = Row("est-" + card.id + "-" + iso(due), "onetime", due, card.description + " payment", "creditcard", -est.cents);
        row.estimated = true; row.card = card.id;
        out.push(row);
      });
    });
    return out;
  }
  function nextPayment(rows, card, today) {
    var due = dueDates(card, today, addMonths(today, 2))[0];
    return { due: due, close: closeBefore(card, due), entered: statementFor(rows, card, due), estimate: cardEstimate(rows, card) };
  }
  // Estimates count from the latest balance onward.
  function since(rows, today) { var base = anchor(rows); return base ? Math.min(base.date, today) : today; }
  // Due dates since the latest balance with no statement entered, through the next three months.
  function openDueDates(rows, card, today) {
    var taken = coveredDues(cardStatements(rows, card), card);
    return dueDates(card, since(rows, today), addMonths(today, 3)).filter(function (d) { return !(d in taken); }).slice(0, 4);
  }
  // For each card, the earliest statement that has closed but whose amount isn't entered yet.
  function pendingStatements(rows, today) {
    var out = [];
    cards(rows).forEach(function (card) {
      if (!isActive(card)) return;
      var due = openDueDates(rows, card, today)[0];
      if (due === undefined) return;
      var close = closeBefore(card, due);
      if (close <= today) out.push({ card: card, due: due, close: close });
    });
    return out;
  }

  // -------------------------------------------------------------- hourly pay
  // For paychecks that vary. You give a rate, the hours in a usual week, and
  // how often you are paid. That is the base: hours x rate for one pay
  // period. Each paycheck you enter (take-home, and optionally the hours you
  // worked) teaches the ledger what share of your pay you actually keep.
  // Future paydays are estimated as base pay x that share.
  function pays(rows) { return rows.filter(function (r) { return r.type === "pay"; }); }
  function paydays(pay, start, end) { return occurrences(pay, start, end); }
  function paychecks(rows, pay) {
    return rows.filter(function (r) { return r.type === "onetime" && r.pay === pay.id && !r.estimated; })
               .sort(function (a, b) { return cmp(a.date, b.date); });
  }
  // {payday: the paycheck recorded for it}. Each paycheck counts for the
  // payday nearest to it, so one that lands a day or two off still replaces
  // the right estimate and no other.
  function coveredPaydays(checks, pay) {
    var span = PAY_SPAN[pay.frequency], out = {};
    checks.forEach(function (r) {
      var payday = nearest(r.date, paydays(pay, r.date - span, r.date + span));
      if (payday !== null && !(payday in out)) out[payday] = r;
    });
    return out;
  }
  function periodHours(pay) { var w = PAY_WEEKS[pay.frequency]; return divRound(pay.hours * w[0], w[1]); }           // hundredths
  function basePay(pay) { var w = PAY_WEEKS[pay.frequency]; return divRound(pay.hours * w[0] * pay.rate, w[1] * 100); } // cents
  // {cents, base, hours, kept, count}: kept is the percent of pay kept, to one decimal place.
  function payEstimate(rows, pay) {
    var base = basePay(pay), kept, earned;
    var recent = paychecks(rows, pay).filter(function (r) { return isActive(r) && r.estimate !== ASSUMED && r.amount > 0; }).slice(-6);
    if (recent.length) {
      kept = recent.reduce(function (n, r) { return n + r.amount; }, 0);
      earned = recent.reduce(function (n, r) { return n + (r.hours > 0 ? divRound(r.hours * pay.rate, 100) : base); }, 0);
    } else {
      kept = pay.percent > 0 ? pay.percent : 10000; earned = 10000;
    }
    if (earned <= 0) return { cents: base, base: base, hours: periodHours(pay), kept: 100, count: 0 };
    return { cents: divRound(base * kept, earned), base: base, hours: periodHours(pay), kept: divRound(kept * 1000, earned) / 10, count: recent.length };
  }
  function payForecast(rows, start, end) {
    var out = [];
    pays(rows).forEach(function (pay) {
      if (!isActive(pay)) return;
      var est = payEstimate(rows, pay), taken = coveredPaydays(paychecks(rows, pay), pay);
      if (est.cents <= 0) return;
      paydays(pay, start, end).forEach(function (payday) {
        if (payday in taken) return;
        var row = Row("est-" + pay.id + "-" + iso(payday), "onetime", payday, pay.description, "income", est.cents);
        row.estimated = true; row.pay = pay.id;
        out.push(row);
      });
    });
    return out;
  }
  function nextPaycheck(rows, pay, today) {
    var payday = paydays(pay, today, addMonths(today, 2))[0];
    if (payday === undefined) return null;
    return { payday: payday, entered: coveredPaydays(paychecks(rows, pay), pay)[payday] || null, estimate: payEstimate(rows, pay) };
  }
  // Paydays since the latest balance with no paycheck entered, up to and
  // including the next one. The most recent ones if there are many.
  function openPaydays(rows, pay, today) {
    var taken = coveredPaydays(paychecks(rows, pay), pay);
    var days = paydays(pay, since(rows, today), today).concat(paydays(pay, today + 1, addMonths(today, 2)).slice(0, 1));
    return days.filter(function (d) { return !(d in taken); }).slice(-4);
  }
  // For each pay, the earliest payday that has arrived with no paycheck entered.
  function pendingPaychecks(rows, today) {
    var out = [];
    pays(rows).forEach(function (pay) {
      if (!isActive(pay)) return;
      var due = openPaydays(rows, pay, today).filter(function (d) { return d <= today; });
      if (due.length) out.push({ pay: pay, payday: due[0] });
    });
    return out;
  }

  // -------------------------------------------------------------- forecasts
  // Estimated card payments and paychecks dated within [start, end] that have
  // nothing entered. They are only saved when a balance update closes the
  // period they fall in.
  function forecastRows(rows, start, end) { return cardForecast(rows, start, end).concat(payForecast(rows, start, end)); }

  // -------------------------------------------------------------- snapshots
  function takeSnapshot(rows, asOf, today, actual) {
    var base = anchor(rows);
    if (base === null) throw new Error("Set a starting balance first.");
    if (asOf <= base.date) throw new Error("Pick a date after your last balance update (" + fmtDate(base.date) + ").");
    if (asOf > today) throw new Error("A balance update can't be in the future.");
    // Estimates dated before the new balance become part of history: they are
    // saved as they stood, so later changes to an average can't rewrite the past.
    var assumed = forecastRows(rows, base.date, asOf - 1).map(function (r) {
      var copy = {}; for (var k in r) copy[k] = r[k];
      copy.id = newId(); copy.estimated = false; copy.estimate = ASSUMED;
      return copy;
    });
    var settled = rows.concat(assumed);
    var amount = actual !== null && actual !== undefined ? actual : startOfDay(settled, asOf);
    var row = Row(newId(), "balance", asOf, "Balance update", "", amount, "", "active");
    return { rows: settled.concat([row]), row: row };
  }
  function undoSnapshot(rows) {
    var found = balances(rows);
    if (found.length < 2) throw new Error("There's no balance update to undo.");
    var last = found[found.length - 1];
    return rows.filter(function (r) { return r.id !== last.id; });
  }
  function snapshotHistory(rows) {
    var found = balances(rows), out = [];
    found.forEach(function (b, i) {
      if (i === 0) { out.push({ row: b, change: null, expected: null, variance: null }); return; }
      var prev = found[i - 1];
      var expected = prev.amount + total(eventsIn(rows, prev.date, b.date - 1));
      out.push({ row: b, change: b.amount - prev.amount, expected: expected, variance: b.amount - expected });
    });
    return out.reverse();
  }
  // Spending in one category between consecutive balance updates, plus the
  // period in progress. DAYS_PER_MONTH is 30.4375 (365.25 / 12).
  function perMonth(spent, days) { return divRound(spent * 304375, days * 10000); }
  function categoryPeriods(rows, today, category) {
    category = category || "creditcard";
    var found = balances(rows), spans = [], i;
    for (i = 0; i + 1 < found.length; i++) spans.push([found[i].date, found[i + 1].date - 1, false]);
    if (found.length && today >= found[found.length - 1].date) spans.push([found[found.length - 1].date, today, true]);
    return spans.map(function (s) {
      var hits = eventsIn(rows, s[0], s[1]).filter(function (e) { return e.category === category; });
      var spent = hits.reduce(function (sum, e) { return sum - e.amount; }, 0);
      var days = s[1] - s[0] + 1;
      return { start: s[0], end: s[1], days: days, count: hits.length, spent: spent, monthly: perMonth(spent, days), open: s[2] };
    }).reverse();
  }
  function averageMonthly(periods) {
    var closed = periods.filter(function (p) { return !p.open; });
    var days = closed.reduce(function (n, p) { return n + p.days; }, 0);
    if (!days) return null;
    return perMonth(closed.reduce(function (n, p) { return n + p.spent; }, 0), days);
  }
  function splitOnetime(rows) {
    var base = anchor(rows), cut = base ? base.date : -Infinity;
    var onetime = rows.filter(function (r) { return r.type === "onetime"; });
    return {
      upcoming: onetime.filter(function (r) { return r.date >= cut; }).sort(function (a, b) { return cmp(a.date, b.date); }),
      settled: onetime.filter(function (r) { return r.date < cut; }).sort(function (a, b) { return cmp(b.date, a.date); })
    };
  }

  // -------------------------------------------------------------- net worth
  function findAccount(book, name) {
    var key = String(name || "").trim().toLowerCase();
    for (var i = 0; i < book.accounts.length; i++) if (book.accounts[i].name.toLowerCase() === key) return book.accounts[i];
    return null;
  }
  function accountActive(a) { return a.status !== "hidden"; }
  function series(book) {
    var kinds = {}, byDate = {}, days = [], current = {}, order = [], out = [];
    book.accounts.forEach(function (a) { kinds[a.name] = a.kind; });
    book.values.forEach(function (v) {
      if (!byDate[v.date]) { byDate[v.date] = []; days.push(v.date); }
      byDate[v.date].push(v);
    });
    days.sort(cmp).forEach(function (day) {
      byDate[day].forEach(function (v) {
        if (!(v.account in current)) order.push(v.account);
        current[v.account] = v.amount;
      });
      var assets = 0, debts = 0;
      order.forEach(function (name) {
        if ((kinds[name] || "asset") === "debt") debts += current[name]; else assets += current[name];
      });
      out.push({ date: day, assets: assets, debts: debts, net: assets - debts });
    });
    return out;
  }
  function latestValues(book) {
    var out = {};
    book.values.slice().sort(function (a, b) { return cmp(a.date, b.date); }).forEach(function (v) { out[v.account] = v; });
    return out;
  }
  function record(book, day, entries) {
    var keep = book.values.filter(function (v) { return !(v.date === day && Object.prototype.hasOwnProperty.call(entries, v.account)); });
    var added = Object.keys(entries).map(function (name) { return { date: day, account: name, amount: entries[name] }; });
    return { accounts: book.accounts.slice(), values: keep.concat(added) };
  }
  function addAccount(book, name, kind) {
    name = cleanText(name);
    if (!name) throw new Error("Give the account a name, like Savings or Visa.");
    if (!KINDS[kind]) throw new Error("Choose asset or debt.");
    if (findAccount(book, name)) throw new Error("You already have an account named " + name + ".");
    return { accounts: book.accounts.concat([{ name: name, kind: kind, status: "active" }]), values: book.values.slice() };
  }
  function editAccount(book, oldName, name, kind, status) {
    var account = findAccount(book, oldName);
    if (!account) throw new Error("That account no longer exists.");
    name = cleanText(name);
    if (!name) throw new Error("Give the account a name.");
    var clash = findAccount(book, name);
    if (clash && clash !== account) throw new Error("You already have an account named " + name + ".");
    if (!KINDS[kind]) throw new Error("Choose asset or debt.");
    var fresh = { name: name, kind: kind, status: status === "hidden" ? "hidden" : "active" };
    return {
      accounts: book.accounts.map(function (a) { return a === account ? fresh : a; }),
      values: book.values.map(function (v) { return v.account === account.name ? { date: v.date, account: name, amount: v.amount } : v; })
    };
  }
  function deleteAccount(book, name) {
    var account = findAccount(book, name);
    if (!account) return book;
    return { accounts: book.accounts.filter(function (a) { return a !== account; }),
             values: book.values.filter(function (v) { return v.account !== account.name; }) };
  }
  function deleteDate(book, day) {
    return { accounts: book.accounts.slice(), values: book.values.filter(function (v) { return v.date !== day; }) };
  }
  function networthCsvText(book) {
    var out = csvLine(["type", "date", "account", "kind", "amount", "status"]);
    book.accounts.forEach(function (a) { out += csvLine(["account", "", a.name, a.kind, "", a.status]); });
    book.values.slice().sort(function (a, b) {
      return cmp(a.date, b.date) || cmp(a.account.toLowerCase(), b.account.toLowerCase());
    }).forEach(function (v) {
      out += csvLine(["value", iso(v.date), v.account, "", (v.amount < 0 ? "-" : "") + fixed2(v.amount), ""]);
    });
    return out;
  }
  function parseNetworthCsv(text) {
    var read = readCsvDicts(text), book = { accounts: [], values: [] }, errors = [], pending = [];
    read.items.forEach(function (item) {
      var raw = item.raw;
      try {
        var rtype = String(get(raw, "type")).trim().toLowerCase(), name = cleanText(raw.account);
        if (rtype === "account") {
          if (!name) throw new Error("the account name is empty");
          var kind = lookup(raw.kind, KINDS, KIND_ALIASES);
          if (kind === null) throw new Error("kind '" + get(raw, "kind") + "' should be asset or debt");
          if (findAccount(book, name)) throw new Error("'" + name + "' is listed as an account twice");
          book.accounts.push({ name: name, kind: kind, status: String(get(raw, "status")).trim().toLowerCase() === "hidden" ? "hidden" : "active" });
        } else if (rtype === "value") {
          if (!name) throw new Error("the account name is empty");
          pending.push({ line: item.line, name: name, day: parseDateText(raw.date), amount: parseAmountText(raw.amount), kind: raw.kind });
        } else {
          throw new Error("type '" + get(raw, "type") + "' should be account or value");
        }
      } catch (e) { errors.push("Row " + item.line + ": " + e.message + "."); }
    });
    if (read.header === null) return { book: { accounts: [], values: [] }, errors: ["The file is empty."] };
    var missing = ["type", "account"].filter(function (c) { return read.header.indexOf(c) < 0; });
    if (missing.length) return { book: { accounts: [], values: [] }, errors: ["The first row needs these column names: " + missing.join(", ") + "."] };
    var latest = {}, keys = [];
    pending.forEach(function (p) {
      var account = findAccount(book, p.name);
      if (!account) {
        var kind = lookup(p.kind, KINDS, KIND_ALIASES);
        if (kind === null) {
          errors.push("Row " + p.line + ": '" + p.name + "' isn't set up as an account. Add an account row for it, or fill in its kind (asset or debt).");
          return;
        }
        account = { name: p.name, kind: kind, status: "active" };
        book.accounts.push(account);
      }
      var key = p.day + "|" + account.name;
      if (!(key in latest)) keys.push(key);
      latest[key] = { date: p.day, account: account.name, amount: p.amount };   // last one for a date wins
    });
    book.values = keys.map(function (k) { return latest[k]; });
    return { book: book, errors: errors };
  }

  // ------------------------------------------------------------------ chart
  function pyRound(x) {                  // Python's round(): halves go to the even number
    var f = Math.floor(x), diff = x - f;
    if (diff < 0.5) return f;
    if (diff > 0.5) return f + 1;
    return f % 2 === 0 ? f : f + 1;
  }
  function niceTicks(lo, hi, count) {
    count = count || 4;
    if (hi - lo < 1) { lo -= 50; hi += 50; }
    var raw = (hi - lo) / count;
    var magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    var step = [1, 2, 2.5, 5, 10].map(function (m) { return m * magnitude; }).filter(function (s) { return s >= raw; })[0];
    var start = Math.floor(lo / step) * step, stop = Math.ceil(hi / step) * step;
    var ticks = [];
    for (var value = start; value <= stop + step * 1e-9; value += step) ticks.push(Math.round(value * 100) / 100);
    return ticks;
  }
  // Coordinates for a chart in a 1000x300 SVG box, plus scrubber data.
  // points: [{date, cents, label}]. "step" holds each value until the next
  // change (balances); "line" connects the points (net worth).
  function buildChart(points, start, end, mode, ghost) {
    var values = points.map(function (p) { return p.cents / 100; });
    var ghostValues = (ghost || []).map(function (p) { return p.cents / 100; }), all = values.concat(ghostValues);
    var ticks = niceTicks(Math.min.apply(null, all), Math.max.apply(null, all));
    var yMin = ticks[0], yMax = ticks[ticks.length - 1];
    var spanDays = Math.max(end - start, 1);
    function x(day) { return (day - start) / spanDays * 1000; }
    function y(value) { return (1 - (value - yMin) / (yMax - yMin)) * 300; }
    var line, area, i;
    if (mode === "step") {
      line = "M0," + y(values[0]).toFixed(1);
      for (i = 1; i < points.length; i++) line += " H" + x(points[i].date).toFixed(1) + " V" + y(values[i]).toFixed(1);
      line += " H1000";
      area = line + " V300 H0 Z";
    } else {
      line = "M" + x(points[0].date).toFixed(1) + "," + y(values[0]).toFixed(1);
      for (i = 1; i < points.length; i++) line += " L" + x(points[i].date).toFixed(1) + "," + y(values[i]).toFixed(1);
      area = line + " V300 H" + x(points[0].date).toFixed(1) + " Z";
      if (points.length === 1) line += " H" + (x(points[0].date) + 0.1).toFixed(1);
    }
    var ghostLine = null;
    if (ghost && ghost.length) {                     // the projection without the what-if, drawn faintly
      ghostLine = "M0," + y(ghostValues[0]).toFixed(1);
      for (i = 1; i < ghost.length; i++) ghostLine += " H" + x(ghost[i].date).toFixed(1) + " V" + y(ghostValues[i]).toFixed(1);
      ghostLine += " H1000";
    }
    var lowest = 0;
    points.forEach(function (p, idx) { if (p.cents < points[lowest].cents) lowest = idx; });
    var labels = [0, 1, 2, 3, 4].map(function (k) { return start + pyRound(spanDays * k / 4); });
    return {
      line: line, area: area, mode: mode, ghostLine: ghostLine,
      grid: ticks.map(function (t) { return Math.round(y(t) * 10) / 10; }),
      zero: yMin < 0 && 0 < yMax ? Math.round(y(0) * 10) / 10 : null,
      yLabels: ticks.slice().reverse().map(moneyShort),
      xLabels: labels.map(function (d) {
        var p = parts(d);
        return spanDays > 180 ? MONTHS[p.m - 1] + " '" + pad(p.y % 100) : fmtDate(d, false);
      }),
      points: points.map(function (p, idx) {
        return { x: Math.round(x(p.date) / 10 * 1000) / 1000, y: Math.round(y(values[idx]) / 3 * 1000) / 1000,
                 b: money(p.cents), l: p.label, d: fmtDate(p.date, false), D: fmtDate(p.date) };
      }),
      lowIndex: lowest, origin: iso(start), span: spanDays
    };
  }

  // ------------------------------------------------------------ sample data
  // A made-up household, laid out around `today` so the preview always looks
  // current: two finished quarters of history and a year of projections.
  function sampleData(today) {
    var t = parts(today - 20);
    var q0 = D(t.y, Math.floor((t.m - 1) / 3) * 3 + 1, 1);      // latest balance update
    var q1 = addMonths(q0, -3), q2 = addMonths(q0, -6);
    var n = 0;
    function id() { n++; return "demo" + ("00000000" + n).slice(-8); }
    function at(base, months, dayOfMonth) { var p = parts(addMonths(base, months)); return D(p.y, p.m, dayOfMonth); }
    var payday = q2;
    while ((payday + 4) % 7 !== 5) payday++;                      // first Friday of the history
    var rows = [
      Row(id(), "balance", q2, "Starting balance", "", 320000),
      Row(id(), "recurring", q2, "Rent", "bill", -215000, "monthly"),
      Row(id(), "recurring", at(q2, 0, 5), "Car loan", "bill", -38900, "monthly"),
      Row(id(), "recurring", at(q2, 0, 12), "Electric", "bill", -11840, "monthly"),
      Row(id(), "recurring", at(q2, 0, 18), "Internet", "bill", -6500, "monthly"),
      Row(id(), "recurring", at(q2, 0, 22), "Phone", "bill", -4500, "monthly"),
      Row(id(), "recurring", at(q2, 0, 9), "Streaming bundle", "bill", -2299, "monthly"),
      Row(id(), "recurring", at(q0, 2, 14), "Car insurance", "bill", -68400, "annually"),
      Row(id(), "recurring", at(q2, 0, 3), "Move to savings", "transfer", -40000, "monthly"),
      Row(id(), "recurring", at(q2, 0, 16), "Roth IRA", "investment", -50000, "monthly"),
      Row(id(), "recurring", at(q2, 0, 7), "Gym membership", "bill", -4200, "monthly", "paused")
    ];
    // Hourly pay: 40 hours a week at $45.00, paid every 2 weeks. Each payday
    // that has passed has its paycheck entered, except the latest one.
    var job = Row("job", "pay", payday, "Paycheck", "", 0, "biweekly");
    job.hours = 4000; job.rate = 4500; job.percent = 7800;
    rows.push(job);
    var worked = [8000, 8400, 7600, 8000, 8800, 8000, 7250, 8000, 8600, 8000, 8200, 7800], wobble = [99, -350, 120, 0, 410, -75, 230, -180, 60, 0, -290, 145];
    var past = occurrences(job, payday, today);
    past.slice(0, Math.max(0, past.length - 1)).forEach(function (day, k) {
      var hours = worked[k % 12], check = Row(id(), "onetime", day, "Paycheck", "income", divRound(hours * 4500 * 78, 10000) + wobble[k % 12]);
      check.pay = "job"; check.hours = hours === 8000 ? 0 : hours;
      rows.push(check);
    });
    // Two cards. Visa estimates from its past statements; the store card uses a set amount.
    var visa = Row("visa", "card", CARD_DATE, "Visa", "", 0), store = Row("store", "card", CARD_DATE, "Store card", "", 18000);
    visa.closeDay = 28; visa.dueDay = 24; visa.estimate = "average";
    store.closeDay = 12; store.dueDay = 7; store.estimate = "fixed";
    rows.push(visa, store);
    var cardAmounts = [138422, 151280, 129745, 168810, 142367, 157530, 134992, 146105, 161240, 139875, 150410, 144630];
    for (var m = 0; m < 12; m++) {
      var due = at(q2, m, 24);
      if (closeBefore(visa, due) > today) break;       // only statements that have closed are entered
      var paid = Row(id(), "onetime", due, "Visa payment", "creditcard", -cardAmounts[m]);
      paid.card = "visa";
      rows.push(paid);
    }
    // Store card: every closed statement is entered except the latest, which is waiting for you.
    var storeDues = [], storeAmounts = [17240, 19815, 16490, 21240, 18360, 17725, 20110, 18900, 16975, 19430, 18255, 20680];
    for (var n2 = 0; n2 < 12; n2++) {
      var storeDue = at(q2, n2, 7);
      if (closeBefore(store, storeDue) > today) break;
      storeDues.push(storeDue);
    }
    storeDues.slice(0, Math.max(0, storeDues.length - 1)).forEach(function (day, k) {
      var bill = Row(id(), "onetime", day, "Store card payment", "creditcard", -storeAmounts[k % 12]);
      bill.card = "store";
      rows.push(bill);
    });
    rows.push(Row(id(), "onetime", at(q1, 1, 10), "Tax refund", "income", 61200));
    rows.push(Row(id(), "onetime", at(q1, 2, 2), "Vet visit", "creditcard", -23650));
    rows.push(Row(id(), "onetime", today + 6, "Work reimbursement", "income", 23850));
    rows.push(Row(id(), "onetime", today + 19, "Car registration", "bill", -16400));
    // Two balance updates: the first found spending that wasn't in the ledger.
    rows.push(Row(id(), "balance", q1, "Balance update", "", startOfDay(rows, q1) - 18240));
    rows.push(Row(id(), "balance", q0, "Balance update", "", startOfDay(rows, q0)));

    var accounts = [
      { name: "Savings", kind: "asset", status: "active" },
      { name: "401k", kind: "asset", status: "active" },
      { name: "Brokerage", kind: "asset", status: "active" },
      { name: "Roth IRA", kind: "asset", status: "active" },
      { name: "Visa", kind: "debt", status: "active" },
      { name: "Car loan", kind: "debt", status: "active" }
    ];
    var tracks = {
      "Savings": [840000, 880000, 920000, 960000, 1000000, 1040000, 1080000, 1120000],
      "401k": [4120000, 4236500, 4198200, 4371900, 4489300, 4452800, 4630100, 4748600],
      "Brokerage": [1275000, null, 1318400, 1296700, null, 1342100, 1387900, 1365200],
      "Roth IRA": [930000, 985300, 1031800, 1094200, 1148900, 1192400, 1257600, 1311500],
      "Visa": [151280, 129745, 168810, 142367, 157530, 134992, 146105, 161240],
      "Car loan": [1480000, 1447200, 1414200, 1381000, 1347600, 1314000, 1280200, 1246200]
    };
    var tm = parts(today), month0 = D(tm.y, tm.m, 1), values = [];
    for (var k = 0; k < 8; k++) {
      var day = addMonths(month0, k - 7);
      accounts.forEach(function (a) {
        var amount = tracks[a.name][k];
        if (amount !== null) values.push({ date: day, account: a.name, amount: amount });
      });
    }
    return { rows: rows, book: { accounts: accounts, values: values } };
  }

  return {
    CATEGORIES: CATEGORIES, FREQUENCIES: FREQUENCIES, KINDS: KINDS, HORIZONS: HORIZONS, MONTHS: MONTHS,
    THEMES: THEMES, MODES: MODES,
    D: D, parts: parts, iso: iso, parseISO: parseISO, addMonths: addMonths, fmtDate: fmtDate, todayNumber: todayNumber,
    money: money, moneyShort: moneyShort, fixed2: fixed2, divRound: divRound,
    cleanText: cleanText, parseDateText: parseDateText, parseAmountText: parseAmountText, parseMoney: parseMoney,
    parseCsv: parseCsv, newId: newId, Row: Row, isActive: isActive,
    parseLedgerCsv: parseLedgerCsv, toCsvText: toCsvText,
    occurrences: occurrences, nextOccurrence: nextOccurrence, eventsIn: eventsIn, total: total,
    balances: balances, anchor: anchor, startOfDay: startOfDay, endOfDay: endOfDay, project: project, cashFlow: cashFlow,
    takeSnapshot: takeSnapshot, undoSnapshot: undoSnapshot, snapshotHistory: snapshotHistory,
    categoryPeriods: categoryPeriods, averageMonthly: averageMonthly, splitOnetime: splitOnetime,
    findAccount: findAccount, accountActive: accountActive, series: series, latestValues: latestValues, record: record,
    addAccount: addAccount, editAccount: editAccount, deleteAccount: deleteAccount, deleteDate: deleteDate,
    networthCsvText: networthCsvText, parseNetworthCsv: parseNetworthCsv,
    ESTIMATES: ESTIMATES, CARD_DATE: CARD_DATE, ASSUMED: ASSUMED, cards: cards, dueDates: dueDates, closeBefore: closeBefore,
    cardStatements: cardStatements, statementFor: statementFor, cardEstimate: cardEstimate, forecastRows: forecastRows,
    nextPayment: nextPayment, openDueDates: openDueDates, pendingStatements: pendingStatements,
    PAY_FREQUENCIES: PAY_FREQUENCIES, plain: plain, pays: pays, paydays: paydays, paychecks: paychecks, payEstimate: payEstimate,
    nextPaycheck: nextPaycheck, openPaydays: openPaydays, pendingPaychecks: pendingPaychecks,
    niceTicks: niceTicks, buildChart: buildChart, sampleData: sampleData
  };
})();
if (typeof module !== "undefined") module.exports = Engine;
