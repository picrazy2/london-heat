/* ── The PM2.5 outlook ─────────────────────────────────────────────────────
   Fetches the model's inputs from /api/forecast and its trees from
   /model/pm25.json, runs templates/pm25model.js in the browser, and draws:

     the chart      the past days measured, the coming week forecast
     the strip      every hour, Apple-style: PM2.5, wind, humidity, lid, rain
     the day tiles  daily mean, verdict, likely range, confidence, drivers
     the sheet      one day in detail, opened from a tile or a notification

   The same module renders the card on /beijing and the page at
   /beijing/forecast; the container's data-mode says which. Nothing here is
   precomputed by the build: a reader at 14:07 sees a forecast issued from the
   13:00 reading and the forecast run Open-Meteo had at the time.            */
(function () {
  "use strict";
  var host = document.getElementById("fcRoot");
  var A = window.AIR, PM25 = window.PM25, O = window.OUTLOOK;
  if (!host || !A || !PM25 || !O) return;
  var FULL = host.dataset.mode === "full";
  var NS = "http://www.w3.org/2000/svg";
  var tip = document.getElementById("tip");
  var DAY = O.DAY, DAYL = O.DAYL, MON = O.MON, compass = O.compass;

  function el(n, a) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); return e; }
  function txt(e, s) { e.textContent = s; return e; }
  function h(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function narrow() { return host.clientWidth < 600; }

  /* ── tooltips that work under a finger ──────────────────────────────────
     With a mouse the tip follows the pointer. With a finger it would sit
     under the finger, so it is pinned above the chart's top edge at the
     touch x, and a vertical drag is left to the page (touch-action:pan-y). */
  function moveTip(ev, anchor) {
    var w = tip.offsetWidth, hh = tip.offsetHeight, x = ev.clientX, y = ev.clientY;
    x = Math.max(w / 2 + 6, Math.min(window.innerWidth - w / 2 - 6, x));
    if (ev.pointerType === "touch" && anchor) y = anchor.getBoundingClientRect().top + 8;
    tip.style.left = x + "px"; tip.style.top = (y - 10 < hh + 8 ? y + hh + 24 : y - 10) + "px";
  }
  function showTip(ev, html, anchor) { tip.innerHTML = html; tip.style.opacity = 1; moveTip(ev, anchor); }
  function hideTip() { tip.style.opacity = 0; }
  function scrub(svg, onIndex) {
    var over = svg.querySelector(".scrub");
    over.style.touchAction = "pan-y";
    var f = function (ev) { onIndex(ev); };
    over.addEventListener("pointermove", f); over.addEventListener("pointerdown", f);
    over.addEventListener("pointerleave", hideTip); over.addEventListener("pointerup", function () { setTimeout(hideTip, 1500); });
  }

  /* The scale follows the air module's toggle when the two share a page, and
     the query string otherwise. */
  function scale() { var b = document.querySelector('#aqScale [aria-checked="true"]'); return b ? b.dataset.scale : (window.WX && window.WX.param("scale", "us")) || "us"; }
  function aqi(c, sc) { return O.aqi(c, A.scales, sc || scale()); }
  function catToken(ci) { return "var(" + A.scales.us.cats[ci].css + ")"; }
  function catInk(ci) { return "var(" + A.scales.us.cats[ci].css + "-ink)"; }
  function catName(ci, sc) { return A.scales[sc || scale()].cats[ci].name; }
  function fmtT(s) { var d = O.dateOf(s); return DAY[d.getUTCDay()] + " " + d.getUTCDate() + " " + MON[d.getUTCMonth()] + ", " + String(d.getUTCHours()).padStart(2, "0") + ":00"; }
  function arrow(dir, size) { return "<svg viewBox='0 0 12 12' width='" + size + "' height='" + size + "' aria-hidden='true' style='transform:rotate(" + Math.round(dir) + "deg)'><path d='M6 1 L6 11 M2.5 7.5 L6 11 L9.5 7.5' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/></svg>"; }

  var R = null, MODEL = null, INPUT = null;

  /* ── the chart ───────────────────────────────────────────────────────── */
  function chart(into, opts) {
    opts = opts || {};
    var hs = R.hours, iNow = R.iNow, nar = opts.narrow != null ? opts.narrow : narrow();
    var first = opts.first != null ? opts.first : (FULL ? 0 : Math.max(0, iNow - (nar ? 24 : 72)));
    var n = opts.last != null ? opts.last + 1 : hs.length;
    var W = opts.w || (nar ? 420 : 900), H = opts.h || (nar ? 200 : (FULL ? 260 : 220)), m = { t: 24, r: 8, b: 22, l: 30 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var vals = []; for (var i = first; i < n; i++) { if (hs[i].v != null) vals.push(hs[i].v); if (hs[i].hi != null) vals.push(Math.min(hs[i].hi, hs[i].fc * 2.2)); }
    var max = Math.max(20, Math.max.apply(null, vals) * 1.12);
    var x = function (i) { return m.l + (i - first) / Math.max(1, n - 1 - first) * pw; };
    var y = function (v) { return m.t + ph - v / max * ph; };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in", role: "img", "aria-label": "Beijing PM2.5, measured over the past days and forecast for the coming week" });
    var S = A.scales[scale()], prev = 0;
    S.bp.forEach(function (b) { var hi = Math.min(b[1], max); if (hi <= prev) return; svg.appendChild(el("rect", { x: m.l, y: y(hi), width: pw, height: Math.max(0, y(prev) - y(hi)), fill: catToken(b[4]), "fill-opacity": ".13" })); prev = hi; });
    var gstep = [5, 10, 20, 25, 50, 100, 200].filter(function (s) { return max / s <= 5; })[0] || 250;
    for (var g = 0; g <= max; g += gstep) { svg.appendChild(el("line", { class: "gridline", x1: m.l, x2: m.l + pw, y1: y(g), y2: y(g) })); svg.appendChild(txt(el("text", { class: "tick", x: m.l - 5, y: y(g) + 3, "text-anchor": "end" }), g)); }
    if (iNow < first && n - 1 > first) svg.appendChild(el("rect", { x: x(first), y: m.t, width: x(n - 1) - x(first), height: ph, fill: "var(--accent-soft)", "fill-opacity": ".55" }));
    if (iNow >= first && iNow < n - 1) {
      svg.appendChild(el("rect", { x: x(iNow), y: m.t, width: x(n - 1) - x(iNow), height: ph, fill: "var(--accent-soft)", "fill-opacity": ".55" }));
      svg.appendChild(el("line", { x1: x(iNow), x2: x(iNow), y1: m.t, y2: m.t + ph, stroke: "var(--ink-faint)", "stroke-dasharray": "3 3" }));
      svg.appendChild(txt(el("text", { class: "tick", x: x(iNow) + 4, y: m.t + 10 }), "now"));
    }
    if (opts.hours) {
      // One day: the hours along the bottom, the clean and dirty stretches above.
      for (var i = first; i < n; i++) { var hh = hs[i].d.getUTCHours(); if (hh % (nar ? 6 : 3) === 0) svg.appendChild(txt(el("text", { class: "tick", x: x(i), y: H - 6, "text-anchor": "middle" }), String(hh).padStart(2, "0"))); }
      var dyy = opts.hours;
      if (dyy.best) { var b0 = first + dyy.best.from, b1 = first + dyy.best.to - 1; if (b1 < n) { svg.appendChild(el("rect", { x: x(b0), y: m.t, width: x(b1) - x(b0), height: ph, fill: "var(--positive)", "fill-opacity": ".10" })); svg.appendChild(txt(el("text", { class: "tick", x: (x(b0) + x(b1)) / 2, y: m.t - 8, "text-anchor": "middle" }), "cleanest")); } }
    } else {
      for (var i = first; i < n; i++) { var d = hs[i].d; if (d.getUTCHours() === 0 && n - i >= 12) svg.appendChild(txt(el("text", { class: "tick", x: x(i), y: H - 6, "text-anchor": "middle" }), DAY[d.getUTCDay()] + (FULL && !nar ? " " + d.getUTCDate() : ""))); }
      R.days.forEach(function (dy) { if (dy.past) return; var mid = dy.hours[Math.floor(dy.hours.length / 2)].i; if (mid < first + 4 || mid >= n) return; svg.appendChild(txt(el("text", { class: "tick fc-daylab", x: x(mid), y: m.t - 8, "text-anchor": "middle" }), Math.round(dy.mean))); });
    }
    function path(get, from, to, attrs) {
      var d = "", pen = false;
      for (var i = from; i <= to; i++) { var v = get(hs[i]); if (v == null || isNaN(v)) { pen = false; continue; } d += (pen ? " L" : " M") + " " + x(i).toFixed(1) + " " + y(Math.min(v, max)).toFixed(1); pen = true; }
      var p = el("path", { d: d.trim(), fill: "none", "stroke-linejoin": "round", "stroke-linecap": "round" }); for (var k in attrs) p.setAttribute(k, attrs[k]); return p;
    }
    // The 80% band: where the measured value landed, at this lead, eight times in ten.
    var split = Math.min(iNow, n - 1), bd = "", top = [], bot = [];
    for (var i = Math.max(first, split); i < n; i++) { var q = hs[i]; if (q.lo == null) continue; top.push([x(i), y(Math.min(q.hi, max))]); bot.push([x(i), y(q.lo)]); }
    if (top.length > 1) {
      bd = top.map(function (p, k) { return (k ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join("") + bot.reverse().map(function (p) { return "L" + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join("") + "Z";
      svg.appendChild(el("path", { d: bd, fill: "var(--accent)", "fill-opacity": ".13", stroke: "none" }));
    }
    if (split >= first) {
      svg.appendChild(path(function (q) { return q.w; }, first, split, { stroke: "var(--accent)", "stroke-width": 1.5, "stroke-opacity": ".55" }));
      svg.appendChild(path(function (q) { return q.obs; }, first, split, { stroke: "var(--ink)", "stroke-width": 2 }));
    }
    svg.appendChild(path(function (q) { return q.fc; }, Math.max(first, split), n - 1, { stroke: "var(--accent)", "stroke-width": 2.5 }));
    var cross = el("line", { y1: m.t, y2: m.t + ph, stroke: "var(--ink-faint)", opacity: 0 }); svg.appendChild(cross);
    svg.appendChild(el("rect", { class: "scrub", x: m.l, y: m.t, width: pw, height: ph, fill: "transparent", style: "cursor:crosshair" }));
    into.innerHTML = ""; into.appendChild(svg);
    scrub(svg, function (ev) {
      var rect = svg.getBoundingClientRect();
      var i = Math.round(first + ((ev.clientX - rect.left) / rect.width * W - m.l) / pw * (n - 1 - first)); i = Math.max(first, Math.min(n - 1, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("opacity", .7);
      var q = hs[i], s = "<span class='k'>" + fmtT(q.t) + "</span><br>";
      if (q.past && q.obs != null) { var ro = aqi(q.obs); s += "measured <b>" + q.obs.toFixed(0) + "</b> · AQI " + ro.i + " " + catName(ro.cat) + "<br>weather model " + q.w.toFixed(0); }
      else { var rf = aqi(q.fc); s += "forecast <b>" + q.fc.toFixed(0) + "</b> µg/m³ · AQI " + rf.i + " " + catName(rf.cat) + (q.lo != null ? "<br><span class='k'>likely " + Math.round(q.lo) + "–" + Math.round(q.hi) + " (80%)</span>" : ""); }
      s += "<br><span class='k'>" + (q.ws || 0).toFixed(1) + " m/s from " + compass(q.dir || 0) + " · lid " + Math.round(q.blh || 0) + " m · RH " + Math.round(q.rh || 0) + "%" + (q.rain > 0.05 ? " · rain " + q.rain.toFixed(1) + " mm" : "") + "</span>";
      showTip(ev, s, svg);
    });
    svg.querySelector(".scrub").addEventListener("pointerleave", function () { cross.setAttribute("opacity", 0); });
  }

  /* ── the hourly strip ─────────────────────────────────────────────────
     One column per hour, scrolled sideways, snapped to now on first paint.
     The number is coloured by its band; wind is an arrow the way it blows
     with the origin letter; the lid and humidity sit below. A day boundary
     is a labelled hairline. Tapping a column shows the full tooltip. */
  function strip(into, from, to, opts) {
    opts = opts || {};
    var hs = R.hours, iNow = R.iNow;
    var wrap = h("div", "fc-strip" + (opts.compact ? " compact" : "")), row = h("div", "fc-strip-row");
    var lastDay = null;
    for (var i = from; i <= to; i++) {
      var q = hs[i], day = q.t.slice(0, 10);
      if (day !== lastDay && lastDay !== null) { var sep = h("div", "fc-sep"); sep.innerHTML = "<span>" + DAY[q.d.getUTCDay()] + " " + q.d.getUTCDate() + "</span>"; row.appendChild(sep); }
      lastDay = day;
      var v = q.v, r = v != null ? aqi(v) : null;
      var col = h("div", "fc-h" + (i === iNow ? " now" : "") + (q.past ? " past" : ""));
      col.dataset.i = i;
      var hr = q.d.getUTCHours();
      col.innerHTML = "<div class='fc-hh'>" + (i === iNow ? "now" : hr === 0 ? DAY[q.d.getUTCDay()] : hr) + "</div>" +
        "<div class='fc-hv tnum' style='--tint:" + (r ? catToken(r.cat) : "var(--ink-faint)") + ";--tint-ink:" + (r ? catInk(r.cat) : "#fff") + "'>" + (v != null ? Math.round(v) : "–") + "</div>" +
        "<div class='fc-hw'>" + arrow(q.dir || 0, 11) + "<span class='tnum'>" + (q.ws != null ? q.ws.toFixed(q.ws < 10 ? 1 : 0) : "–") + "</span></div>" +
        "<div class='fc-hm tnum'>" + (q.rh != null ? Math.round(q.rh) + "%" : "–") + "</div>" +
        "<div class='fc-hl tnum'>" + (q.blh != null ? (q.blh >= 1000 ? (q.blh / 1000).toFixed(1) + "k" : Math.round(q.blh / 10) * 10) : "–") + "</div>" +
        (q.rain > 0.05 ? "<div class='fc-hr tnum'>" + q.rain.toFixed(1) + "</div>" : "<div class='fc-hr'></div>");
      row.appendChild(col);
    }
    var lab = h("div", "fc-h fc-lab");
    lab.innerHTML = "<div class='fc-hh'>&nbsp;</div><div class='fc-hv'>PM2.5</div><div class='fc-hw'>wind</div><div class='fc-hm'>RH</div><div class='fc-hl'>lid</div><div class='fc-hr'>rain</div>";
    row.insertBefore(lab, row.firstChild); wrap.appendChild(row);
    into.innerHTML = ""; into.appendChild(wrap);
    row.addEventListener("pointerdown", function (ev) {
      var c = ev.target.closest(".fc-h"); if (!c) return;
      var q = hs[+c.dataset.i], r = q.v != null ? aqi(q.v) : null;
      showTip(ev, "<span class='k'>" + fmtT(q.t) + "</span><br>" + (q.past ? "measured" : "forecast") + " <b>" + (q.v != null ? Math.round(q.v) : "–") + "</b> µg/m³" + (r ? " · AQI " + r.i + " " + catName(r.cat) : "") +
        "<br><span class='k'>" + (q.ws || 0).toFixed(1) + " m/s from " + compass(q.dir || 0) + " at 100 m · lid " + Math.round(q.blh || 0) + " m · RH " + Math.round(q.rh || 0) + "% · " + Math.round(q.temp || 0) + " °C" + (q.rain > 0.05 ? " · rain " + q.rain.toFixed(1) + " mm" : "") + "</span>", row);
      setTimeout(hideTip, 2500);
    });
    // Start scrolled so "now" sits a few columns in from the left.
    if (opts.snapNow !== false) requestAnimationFrame(function () { var nowEl = row.querySelector(".now"); if (nowEl) row.scrollLeft = Math.max(0, nowEl.offsetLeft - 3 * nowEl.offsetWidth); });
    return wrap;
  }

  /* ── the day tiles ───────────────────────────────────────────────────── */
  function tiles(into) {
    into.innerHTML = "";
    R.days.forEach(function (dy) {
      if (dy.past || dy.mean == null || dy.future < 6) return;
      var r = aqi(dy.mean), cf = dy.conf;
      var tile = h("button", "fc-day pressable"); tile.type = "button"; tile.dataset.day = dy.date;
      tile.style.setProperty("--tint", catToken(r.cat)); tile.style.setProperty("--tint-ink", catInk(r.cat));
      tile.innerHTML = "<div class='fc-dow'>" + (dy.today ? "Today" : DAY[dy.dow]) + "</div>" +
        "<div class='fc-idx tnum'>" + r.i + "</div>" +
        "<div class='fc-cat'>" + catName(r.cat) + "</div>" +
        "<div class='fc-conc tnum'>" + Math.round(dy.mean) + "<small> µg/m³</small></div>" +
        (cf ? "<div class='fc-conf tnum'><span class='fc-range'>likely " + Math.round(cf.lo) + "–" + Math.round(cf.hi) + "</span><span class='fc-sure'>" + Math.round(cf.p * 100) + "% sure</span></div>" : "") +
        "<div class='fc-wx'><span class='fc-wind'>" + arrow(dy.dir, 11) + compass(dy.dir) + " " + dy.ws.toFixed(1) + "<small> m/s</small></span>" +
          "<span>lid " + Math.round(dy.blhMax / 50) * 50 + "<small> m</small></span>" + (dy.rain > 0.2 ? "<span>rain " + dy.rain.toFixed(1) + "<small> mm</small></span>" : "") + "</div>";
      tile.addEventListener("click", function () { openDay(dy.date); });
      into.appendChild(tile);
    });
  }

  function why() {
    var fut = R.days.filter(function (d) { return !d.past && d.mean != null && d.future >= 6; }); if (!fut.length) return "";
    var peak = fut.reduce(function (a, b) { return b.mean > a.mean ? b : a; }), low = fut.reduce(function (a, b) { return b.mean < a.mean ? b : a; });
    var north = fut.filter(function (d) { return d.strongN >= 6; }).length, rain = fut.filter(function (d) { return d.rain > 2; }).length;
    var s = "Peak <b>" + DAY[peak.dow] + "</b> (" + Math.round(peak.mean) + ": " + O.why(peak, A.scales) + "), cleanest <b>" + DAY[low.dow] + "</b> (" + Math.round(low.mean) + ").";
    if (north) s += " A north wind on " + north + (north === 1 ? " day" : " days") + " does the clearing.";
    if (rain) s += " Rain on " + rain + (rain === 1 ? " day" : " days") + ".";
    if (!north && !rain) s += " No north wind and no rain in the forecast: what accumulates, stays.";
    return s;
  }
  function stamp() {
    var i = R.iNow, s = i >= 0 ? "From the " + fmtT(R.t[i]) + " reading (" + Math.round(R.obs[i]) + " µg/m³)" : "No recent reading; weather only";
    if (R.up && R.up.c_south_PM25 != null) s += " · upwind south " + Math.round(R.up.c_south_PM25) + ", north-west " + Math.round(R.up.c_northwest_PM25 || 0);
    return s + " · forecast run " + (R.fetched ? new Date(R.fetched).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "");
  }

  /* ── the day sheet ────────────────────────────────────────────────────
     One day in detail: the verdict, the range, the hours, the drivers.
     A bottom sheet on phones, a centred card on wide screens; drag down,
     tap the scrim, Escape, or the ✕ to close. ?day= in the URL opens it,
     which is how a notification lands on the right day. */
  var sheet = null;
  function openDay(day) {
    var dy = R.byDay[day]; if (!dy || dy.mean == null) return;
    closeSheet();
    var r = aqi(dy.mean), cn = aqi(dy.mean, "cn"), us = aqi(dy.mean, "us"), cf = dy.conf;
    var d0 = O.dateOf(day + "T00");
    sheet = h("div", "fc-sheet-wrap");
    sheet.innerHTML = "<div class='fc-scrim'></div><div class='fc-sheet' role='dialog' aria-modal='true' aria-label='" + DAYL[dy.dow] + " in detail'>" +
      "<div class='fc-grab'></div><button class='fc-close iconbtn' aria-label='Close'>✕</button>" +
      "<div class='fc-sh-head' style='--tint:" + catToken(r.cat) + "'>" +
        "<div class='fc-sh-day'>" + (dy.today ? "Today · " : "") + DAYL[dy.dow] + " " + d0.getUTCDate() + " " + MON[d0.getUTCMonth()] + "</div>" +
        "<div class='fc-sh-idx'><span class='n display tnum'>" + r.i + "</span><span class='of'>" + A.scales[scale()].name + " AQI</span></div>" +
        "<div class='fc-sh-cat'>" + catName(r.cat) + (scale() === "cn" && A.scales.cn.cats[r.cat].zh ? " · " + A.scales.cn.cats[r.cat].zh : "") + "</div>" +
        "<div class='fc-sh-conc'>PM2.5 <b>" + Math.round(dy.mean) + "</b> µg/m³ daily mean · US " + us.i + " · China " + cn.i + "</div>" +
        (cf ? "<div class='fc-sh-conf'>Likely <b>" + Math.round(cf.lo) + "–" + Math.round(cf.hi) + "</b> µg/m³ · <b>" + Math.round(cf.p * 100) + "%</b> sure of the verdict, " + dy.lead + (dy.lead === 1 ? " day" : " days") + " out</div>" : "") +
      "</div>" +
      "<div class='fc-sh-chart'></div>" +
      "<div class='fc-sh-grid'>" +
        stat("Cleanest", dy.best ? dy.best.from + "–" + dy.best.to + "h" : "–", dy.best ? Math.round(dy.best.v) + " µg/m³" : "") +
        stat("Worst", dy.evening != null && dy.worst && dy.evening > dy.worst.v ? "evening" : dy.worst ? dy.worst.from + "–" + dy.worst.to + "h" : "–", dy.worst ? Math.round(Math.max(dy.worst.v, dy.evening || 0)) + " µg/m³" : "") +
        stat("Wind, 100 m", arrow(dy.dir, 13) + " " + compass(dy.dir) + " " + dy.ws.toFixed(1) + " m/s", dy.strongN >= 6 ? "north wind " + dy.strongN + " h" : dy.vn > 1 ? "light northerly" : dy.vn < -2 ? "southerly" : "light") +
        stat("Lid", lidRange(dy.blhMin, dy.blhMax), dy.blhMax >= 1500 ? "deep afternoon" : dy.blhMax < 800 ? "shallow all day" : "ordinary") +
        stat("Humidity", Math.round(dy.rhMin) + "–" + Math.round(dy.rh) + "%", dy.rhMin < 35 ? "dry afternoon" : dy.rh > 70 ? "humid, hazy-looking" : "") +
        stat(dy.rain > 0.2 ? "Rain" : "Temperature", dy.rain > 0.2 ? dy.rain.toFixed(1) + " mm" : Math.round(dy.tmin) + "–" + Math.round(dy.tmax) + " °C", dy.rain > 0.2 ? Math.round(dy.tmin) + "–" + Math.round(dy.tmax) + " °C" : dy.cloud != null ? (dy.cloud < 25 ? "clear" : dy.cloud < 60 ? "some cloud" : "cloudy") : "") +
      "</div>" +
      "<div class='fc-sh-strip'></div>" +
      "<p class='fc-sh-why'>" + O.why(dy, A.scales).replace(/^./, function (c) { return c.toUpperCase(); }) + ".</p>" +
      "<p class='footnote'>" + stamp() + "</p>" +
    "</div>";
    document.body.appendChild(sheet);
    var hs = dy.hours; strip(sheet.querySelector(".fc-sh-strip"), hs[0].i, hs[hs.length - 1].i, { compact: true, snapNow: false });
    chart(sheet.querySelector(".fc-sh-chart"), { first: hs[0].i, last: hs[hs.length - 1].i, w: 520, h: 180, narrow: false, hours: dy });
    document.body.style.overflow = "hidden";
    var panel = sheet.querySelector(".fc-sheet");
    requestAnimationFrame(function () { sheet.classList.add("on"); });
    sheet.querySelector(".fc-scrim").addEventListener("click", closeSheet);
    sheet.querySelector(".fc-close").addEventListener("click", closeSheet);
    // Drag to dismiss: a pull of 90 px, or a quick flick, from anywhere the panel isn't scrolled.
    var y0 = null, dy0 = 0, t0 = 0;
    panel.addEventListener("touchstart", function (e) { if (panel.scrollTop > 0) return; y0 = e.touches[0].clientY; t0 = Date.now(); dy0 = 0; }, { passive: true });
    panel.addEventListener("touchmove", function (e) { if (y0 == null) return; dy0 = Math.max(0, e.touches[0].clientY - y0); panel.style.transform = "translateY(" + dy0 + "px)"; panel.style.transition = "none"; }, { passive: true });
    panel.addEventListener("touchend", function () { if (y0 == null) return; var v = dy0 / Math.max(1, Date.now() - t0); panel.style.transition = ""; if (dy0 > 90 || v > 0.5) closeSheet(); else panel.style.transform = ""; y0 = null; });
    try { window.WX.setParam("day", day, ""); } catch (e) {}
  }
  function lidRange(lo, hi) { return hi >= 1000 ? (lo / 1000).toFixed(1) + "–" + (hi / 1000).toFixed(1) + " km" : Math.round(lo / 10) * 10 + "–" + Math.round(hi / 50) * 50 + " m"; }
  function stat(k, v, s) { return "<div class='fc-stat'><div class='k'>" + k + "</div><div class='v tnum'>" + v + "</div>" + (s ? "<div class='s'>" + s + "</div>" : "") + "</div>"; }
  function closeSheet() {
    if (!sheet) return;
    var s = sheet; sheet = null; s.classList.remove("on"); document.body.style.overflow = "";
    setTimeout(function () { s.remove(); }, 300);
    try { window.WX.setParam("day", "", ""); } catch (e) {}
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeSheet(); });

  /* ── render everything ───────────────────────────────────────────────── */
  function render() {
    var c = document.getElementById("fcChart"); if (c) chart(c);
    var s = document.getElementById("fcStrip"); if (s) strip(s, Math.max(0, R.iNow - 24), R.hours.length - 1);
    var d = document.getElementById("fcDays"); if (d) tiles(d);
    var w = document.getElementById("fcWhy"); if (w) w.innerHTML = why();
    var st = document.getElementById("fcStamp"); if (st) st.textContent = stamp();
  }
  function fail(msg) { var c = document.getElementById("fcChart"); if (c) c.innerHTML = "<p class='footnote'>" + msg + "</p>"; }

  function run(inp) {
    if (!inp.forecast) { fail("The weather forecast is unavailable right now."); return; }
    INPUT = inp;
    R = O.outlook(PM25, MODEL, { level365: A.level365, scales: A.scales, intervals: A.intervals, intervals_h: A.intervals_h }, inp);
    render();
    var want = window.WX && window.WX.param("day", ""); if (want && R.byDay[want]) openDay(want);
  }

  function refresh() {
    return fetch("/api/forecast").then(function (r) { if (!r.ok) throw new Error("api"); return r.json(); }).then(run);
  }
  fetch("/model/pm25.json", { cache: "force-cache" }).then(function (r) { if (!r.ok) throw new Error("model"); return r.json(); })
    .then(function (m) { MODEL = m; return refresh(); })
    .catch(function (e) { fail("The forecast could not be computed (" + (e && e.message) + ")."); });
  // Fresh every ten minutes, like the live tile — and when the tab comes back.
  setInterval(function () { if (MODEL && !document.hidden) refresh().catch(function () {}); }, 10 * 60 * 1000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden && MODEL) refresh().catch(function () {}); });
  var sc = document.getElementById("aqScale"); if (sc) sc.addEventListener("click", function () { setTimeout(function () { if (R) render(); }, 0); });
  var rt; window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(function () { if (R) { var c = document.getElementById("fcChart"); if (c) chart(c); } }, 150); });
})();
