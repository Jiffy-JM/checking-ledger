// Small progressive enhancements. The app works without this file.
(function () {
  "use strict";

  // Scrub the balance chart with a finger or mouse; the big number above it
  // shows the balance on that day.
  document.querySelectorAll("[data-chart]").forEach(function (chart) {
    var points;
    try { points = JSON.parse(chart.getAttribute("data-points")); } catch (e) { return; }
    if (!points || !points.length) return;
    var root = chart.closest("[data-chart-root]");
    var outB = root.querySelector("[data-readout-b]");
    var outD = root.querySelector("[data-readout-d]");
    var outL = root.querySelector("[data-readout-l]");
    var cursor = chart.querySelector("[data-cursor]");
    var dot = chart.querySelector("[data-dot]");
    var lowDot = chart.querySelector("[data-low-dot]");
    var parts = chart.getAttribute("data-origin").split("-").map(Number);
    var origin = new Date(parts[0], parts[1] - 1, parts[2]);
    var span = Number(chart.getAttribute("data-span")) || 1;
    var defaults = { b: outB.textContent, d: outD.textContent, l: outL.textContent };
    var fmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

    function put(node, x, y) {
      node.style.left = x + "%";
      if (y !== undefined) node.style.top = y + "%";
      node.classList.remove("hidden");
    }

    var mode = chart.getAttribute("data-mode") || "step";
    var low = points[Number(chart.getAttribute("data-low"))];
    if (low && lowDot && mode === "step") put(lowDot, low.x, low.y);
    chart.querySelectorAll("[data-mark]").forEach(function (m) {
      put(m, Number(m.getAttribute("data-x")), Number(m.getAttribute("data-y")));
    });

    function show(clientX) {
      var box = chart.getBoundingClientRect();
      var x = Math.max(0, Math.min(100, (clientX - box.left) / box.width * 100));
      var p = points[0];
      if (mode === "line") {
        // Net worth: snap to the nearest recorded snapshot.
        points.forEach(function (q) { if (Math.abs(q.x - x) < Math.abs(p.x - x)) p = q; });
        put(cursor, p.x);
        put(dot, p.x, p.y);
        outB.textContent = p.b;
        outD.textContent = "Net worth on " + p.D;
        outL.textContent = p.l || "Your first snapshot";
        return;
      }
      // Balance: the value holds until the next change (step chart).
      for (var i = 1; i < points.length && points[i].x <= x; i++) p = points[i];
      var day = new Date(origin.getFullYear(), origin.getMonth(), origin.getDate() + Math.round(span * x / 100));
      put(cursor, x);
      put(dot, x, p.y);
      outB.textContent = p.b;
      outD.textContent = "Balance on " + fmt.format(day);
      outL.textContent = p.l ? "After " + p.l + " on " + p.d : "Start of day, before anything dated " + p.d;
    }

    function reset() {
      cursor.classList.add("hidden");
      dot.classList.add("hidden");
      outB.textContent = defaults.b;
      outD.textContent = defaults.d;
      outL.textContent = defaults.l;
    }

    chart.addEventListener("pointerdown", function (e) { show(e.clientX); });
    chart.addEventListener("pointermove", function (e) {
      if (e.pointerType === "mouse" || e.buttons || e.pressure) show(e.clientX);
    });
    chart.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") reset(); });
    chart.addEventListener("pointercancel", reset);
    document.addEventListener("pointerdown", function (e) {
      if (!chart.contains(e.target)) reset();
    });
  });

  // Theme page: show a choice as soon as it's picked. Save keeps it.
  var themeForm = document.querySelector("form[data-theme-form]");
  if (themeForm) {
    themeForm.addEventListener("change", function () {
      var theme = themeForm.querySelector('input[name="theme"]:checked');
      var mode = themeForm.querySelector('input[name="mode"]:checked');
      if (theme) document.documentElement.setAttribute("data-theme", theme.value);
      if (mode) document.documentElement.setAttribute("data-mode", mode.value);
    });
  }

  // Ask before destructive actions.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
    });
  });
})();
