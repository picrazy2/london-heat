/* ── The PM2.5 outlook ─────────────────────────────────────────────────────
   Fetches the model's inputs from /api/forecast and its trees from
   /model/pm25.json, runs templates/pm25model.js in the browser, and draws the
   past few days against the coming week. The same module renders the compact
   card on /beijing and the full page at /beijing/forecast; the container's
   data-mode says which.

   Nothing here is precomputed by the build. A reader at 14:07 sees a forecast
   issued from the 13:00 reading and the forecast run Open-Meteo had at the
   time, at most ten minutes stale at the edge. */
(function () {
  "use strict";
  var host = document.getElementById("fcRoot");
  var A = window.AIR, PM25 = window.PM25;
  if (!host || !A || !PM25) return;
  var FULL = host.dataset.mode === "full";
  var NS = "http://www.w3.org/2000/svg";
  var tip = document.getElementById("tip");
  var DAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function el(n, a) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); return e; }
  function txt(e, s) { e.textContent = s; return e; }
  function h(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function moveTip(ev) {
    var x = ev.clientX, y = ev.clientY, w = tip.offsetWidth, hh = tip.offsetHeight;
    tip.style.left = Math.min(x + 14, window.innerWidth - w - 8) + "px";
    tip.style.top = (y - hh - 14 < 8 ? y + 18 : y - hh - 14) + "px";
  }
  function showTip(ev, html) { tip.innerHTML = html; tip.style.opacity = 1; moveTip(ev); }
  function hideTip() { tip.style.opacity = 0; }

  /* The scale follows the air module's toggle when the two share a page, and
     the query string otherwise, so a link to the page carries the reader's choice. */
  function scale() {
    var b = document.querySelector('#aqScale [aria-checked="true"]');
    return b ? b.dataset.scale : (window.WX && window.WX.param("scale", "us")) || "us";
  }
  function aqi(conc, sc) {
    if (conc == null || isNaN(conc)) return null;
    var S = A.scales[sc || scale()];
    var c = S.trunc ? Math.floor(conc * 10) / 10 : Math.round(conc);
    var bp = S.bp, top = bp[bp.length - 1];
    if (c >= top[1]) return { i: top[3], cat: top[4] };
    for (var k = 0; k < bp.length; k++) {
      if (c <= bp[k][1]) {
        var span = bp[k][1] - bp[k][0], frac = span <= 0 ? 0 : (c - bp[k][0]) / span;
        return { i: Math.round(bp[k][2] + frac * (bp[k][3] - bp[k][2])), cat: bp[k][4] };
      }
    }
    return { i: top[3], cat: top[4] };
  }
  function catToken(ci) { return "var(" + A.scales.us.cats[ci].css + ")"; }
  function catInk(ci) { return "var(" + A.scales.us.cats[ci].css + "-ink)"; }
  function catName(ci, sc) { return A.scales[sc || scale()].cats[ci].name; }
  function compass(d) { return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(d / 45) % 8]; }
  function parseT(s) { var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})/.exec(s); return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4])); }
  function fmtT(s) { var d = parseT(s); return DAY[d.getUTCDay()] + " " + d.getUTCDate() + " " + MON[d.getUTCMonth()] + ", " + String(d.getUTCHours()).padStart(2, "0") + ":00"; }

  var R = null;   // the run: {t, w, fc, iNow, F, obs, raw, up}

  /* ── the chart ───────────────────────────────────────────────────────── */
  function chart(into, opts) {
    var t = R.t, n = t.length, iNow = R.iNow;
    var first = FULL ? 0 : Math.max(0, iNow - 72);
    var W = 900, H = FULL ? 260 : 220, m = { t: 22, r: 8, b: 22, l: 30 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var vals = [];
    for (var i = first; i < n; i++) { if (R.obs[i] != null) vals.push(R.obs[i]); vals.push(R.fc[i]); }
    var max = Math.max(20, Math.max.apply(null, vals) * 1.18);
    var x = function (i) { return m.l + (i - first) / Math.max(1, n - 1 - first) * pw; };
    var y = function (v) { return m.t + ph - v / max * ph; };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in", role: "img",
      "aria-label": "Beijing PM2.5, measured over the past days and forecast for the coming week" });

    var S = A.scales[scale()], prev = 0;
    S.bp.forEach(function (b) {
      var hi = Math.min(b[1], max); if (hi <= prev) return;
      svg.appendChild(el("rect", { x: m.l, y: y(hi), width: pw, height: Math.max(0, y(prev) - y(hi)), fill: catToken(b[4]), "fill-opacity": ".13" }));
      prev = hi;
    });
    var gstep = [5, 10, 20, 25, 50, 100, 200].filter(function (s) { return max / s <= 5; })[0] || 250;
    for (var g = 0; g <= max; g += gstep) {
      svg.appendChild(el("line", { class: "gridline", x1: m.l, x2: m.l + pw, y1: y(g), y2: y(g) }));
      svg.appendChild(txt(el("text", { class: "tick", x: m.l - 5, y: y(g) + 3, "text-anchor": "end" }), g));
    }
    // The future, tinted; "now" as a hairline.
    if (iNow >= first && iNow < n - 1) {
      svg.appendChild(el("rect", { x: x(iNow), y: m.t, width: x(n - 1) - x(iNow), height: ph, fill: "var(--accent-soft)", "fill-opacity": ".55" }));
      svg.appendChild(el("line", { x1: x(iNow), x2: x(iNow), y1: m.t, y2: m.t + ph, stroke: "var(--ink-faint)", "stroke-dasharray": "3 3" }));
      svg.appendChild(txt(el("text", { class: "tick", x: x(iNow) + 4, y: m.t + 10 }), "now"));
    }
    // Day ticks at midnight, and the daily-mean labels above each forecast day.
    for (var i = first; i < n; i++) {
      var d = parseT(t[i]);
      if (d.getUTCHours() === 0 && n - i >= 12)
        svg.appendChild(txt(el("text", { class: "tick", x: x(i), y: H - 6, "text-anchor": "middle" }), DAY[d.getUTCDay()] + (FULL ? " " + d.getUTCDate() : "")));
    }
    R.days.forEach(function (dy) {
      if (dy.i0 + 12 < first) return;
      svg.appendChild(txt(el("text", { class: "tick fc-daylab", x: x(dy.i0 + 12), y: m.t - 8, "text-anchor": "middle" }), Math.round(dy.mean)));
    });
    function path(arr, from, to, attrs) {
      var d = "", pen = false;
      for (var i = from; i <= to; i++) {
        var v = arr[i];
        if (v == null || isNaN(v)) { pen = false; continue; }
        d += (pen ? " L" : " M") + " " + x(i).toFixed(1) + " " + y(Math.min(v, max)).toFixed(1); pen = true;
      }
      var p = el("path", { d: d.trim(), fill: "none", "stroke-linejoin": "round", "stroke-linecap": "round" });
      for (var k in attrs) p.setAttribute(k, attrs[k]);
      return p;
    }
    svg.appendChild(path(R.w, first, iNow, { stroke: "var(--accent)", "stroke-width": 1.5, "stroke-opacity": ".55" }));
    svg.appendChild(path(R.obs, first, iNow, { stroke: "var(--ink)", "stroke-width": 2 }));
    svg.appendChild(path(R.fc, iNow, n - 1, { stroke: "var(--accent)", "stroke-width": 2.5 }));

    var over = el("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent", style: "cursor:crosshair" });
    over.addEventListener("mousemove", function (ev) {
      var rect = svg.getBoundingClientRect();
      var i = Math.round(first + ((ev.clientX - rect.left) / rect.width * W - m.l) / pw * (n - 1 - first));
      i = Math.max(first, Math.min(n - 1, i));
      var F = R.F, s = "<span class='k'>" + fmtT(t[i]) + "</span><br>";
      if (i <= iNow && R.obs[i] != null) { var ro = aqi(R.obs[i]); s += "measured <b>" + R.obs[i].toFixed(0) + "</b> · AQI " + ro.i + " " + catName(ro.cat) + "<br>weather model " + R.w[i].toFixed(0); }
      else { var rf = aqi(R.fc[i]); s += "forecast <b>" + R.fc[i].toFixed(0) + "</b> µg/m³ · AQI " + rf.i + " " + catName(rf.cat); }
      s += "<br><span class='k'>" + (F.e_wind_speed_100m[i] || 0).toFixed(1) + " m/s from " + compass(R.raw.wind_direction_100m[i] || 0) +
        " · lid " + Math.round(F.e_boundary_layer_height[i] || 0) + " m · RH " + Math.round(F.e_relative_humidity_2m[i] || 0) + "%" +
        (F.e_precipitation[i] > 0.05 ? " · rain " + F.e_precipitation[i].toFixed(1) + " mm" : "") + "</span>";
      showTip(ev, s);
    });
    over.addEventListener("mouseleave", hideTip);
    svg.appendChild(over);
    into.innerHTML = ""; into.appendChild(svg);
  }

  /* ── the day tiles ───────────────────────────────────────────────────── */
  function tiles(into) {
    into.innerHTML = "";
    R.days.forEach(function (dy) {
      var r = aqi(dy.mean), d = parseT(R.t[dy.i0]);
      var tile = h("div", "fc-day");
      tile.style.setProperty("--tint", catToken(r.cat)); tile.style.setProperty("--tint-ink", catInk(r.cat));
      tile.innerHTML = "<div class='fc-dow'>" + (dy.today ? "Today" : DAY[d.getUTCDay()]) + "</div>" +
        "<div class='fc-idx tnum'>" + r.i + "</div>" +
        "<div class='fc-cat'>" + catName(r.cat) + "</div>" +
        "<div class='fc-conc tnum'>" + Math.round(dy.mean) + "<small> µg/m³</small></div>" +
        (FULL ? "<div class='fc-wx'>" + dy.ws.toFixed(1) + " m/s " + compass(dy.dir) + " · lid " + Math.round(dy.blh) + " m" +
          (dy.rain > 0.2 ? " · " + dy.rain.toFixed(1) + " mm" : "") + "</div>" : "");
      into.appendChild(tile);
    });
  }

  /* ── one sentence on why ─────────────────────────────────────────────── */
  function why() {
    var F = R.F, days = R.days, fut = days.filter(function (d) { return !d.today; });
    if (!fut.length) return "";
    var peak = fut.reduce(function (a, b) { return b.mean > a.mean ? b : a; });
    var low = fut.reduce(function (a, b) { return b.mean < a.mean ? b : a; });
    var pd = parseT(R.t[peak.i0]), ld = parseT(R.t[low.i0]);
    var north = fut.filter(function (d) { return d.vn > 1.5; }).length, rain = fut.filter(function (d) { return d.rain > 2; }).length;
    var s = "Peak on <b>" + DAY[pd.getUTCDay()] + "</b> (" + Math.round(peak.mean) + " µg/m³, " + peak.ws.toFixed(1) + " m/s from the " + compass(peak.dir) +
      ", lid " + Math.round(peak.blh) + " m, RH " + Math.round(peak.rh) + "%), cleanest on <b>" + DAY[ld.getUTCDay()] + "</b> (" + Math.round(low.mean) + ").";
    if (north) s += " A northerly on " + north + (north === 1 ? " day" : " days") + " does the clearing.";
    if (rain) s += " Rain on " + rain + (rain === 1 ? " day" : " days") + ".";
    if (!north && !rain) s += " No north wind and no rain in the forecast: what accumulates, stays.";
    return s;
  }

  function stamp() {
    var i = R.iNow, s = i >= 0 ? "From the " + fmtT(R.t[i]) + " reading (" + Math.round(R.obs[i]) + " µg/m³)" : "No recent reading; weather only";
    if (R.up && R.up.c_south_PM25 != null) s += " · upwind south " + Math.round(R.up.c_south_PM25) + ", north-west " + Math.round(R.up.c_northwest_PM25 != null ? R.up.c_northwest_PM25 : 0);
    return s + " · forecast run " + (R.fetched ? new Date(R.fetched).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "");
  }

  function render() {
    var c = document.getElementById("fcChart"); if (c) chart(c);
    var d = document.getElementById("fcDays"); if (d) tiles(d);
    var w = document.getElementById("fcWhy"); if (w) w.innerHTML = why();
    var s = document.getElementById("fcStamp"); if (s) s.textContent = stamp();
  }

  function fail(msg) {
    var c = document.getElementById("fcChart");
    if (c) c.innerHTML = "<p class='footnote'>" + msg + "</p>";
  }

  /* ── load, run, draw ─────────────────────────────────────────────────── */
  Promise.all([
    fetch("/model/pm25.json", { cache: "force-cache" }).then(function (r) { if (!r.ok) throw new Error("model"); return r.json(); }),
    fetch("/api/forecast").then(function (r) { if (!r.ok) throw new Error("api"); return r.json(); }),
  ]).then(function (res) {
    var model = res[0], inp = res[1];
    if (!inp.forecast) { fail("The weather forecast is unavailable right now."); return; }
    var raw = inp.forecast, n = raw.time.length;
    var obs = raw.time.map(function (s) { var v = inp.obs && inp.obs[s.slice(0, 13) + ":00"]; return v == null ? null : v; });
    var out = PM25.run(model, raw, obs, inp.upwind, A.level365);
    R = { t: raw.time, w: out.w, fc: out.fc, iNow: out.iNow, F: out.F, obs: obs, raw: raw, up: inp.upwind, fetched: inp.fetched };
    // Daily means over the forecast hours (today = the remaining hours).
    R.days = [];
    var i = out.iNow + 1;
    while (i < n) {
      var d0 = raw.time[i].slice(0, 10), i0 = i, sum = 0, c = 0, ws = 0, vn = 0, ux = 0, uy = 0, blh = 0, rh = 0, rain = 0;
      while (i < n && raw.time[i].slice(0, 10) === d0) {
        sum += out.fc[i]; c++; ws += out.F.e_wind_speed_100m[i] || 0; vn += out.F.e_v_north100[i] || 0;
        ux += out.F.e_u_east100[i] || 0; uy += out.F.e_v_north100[i] || 0;
        blh += out.F.e_boundary_layer_height[i] || 0; rh += out.F.e_relative_humidity_2m[i] || 0; rain += out.F.e_precipitation[i] || 0; i++;
      }
      // i0 is the day's midnight, which for today lies before the last reading.
      if (c >= 6) R.days.push({ i0: i0 - (24 - c), mean: sum / c, ws: ws / c, vn: vn / c, blh: blh / c, rh: rh / c, rain: rain,
        dir: (Math.atan2(ux, uy) * 180 / Math.PI + 360) % 360, today: R.days.length === 0 && c < 24 });
      if (R.days.length === 8) break;
    }
    R.days.forEach(function (d) { d.i0 = Math.max(0, d.i0); });
    render();
    var sc = document.getElementById("aqScale");
    if (sc) sc.addEventListener("click", function () { setTimeout(render, 0); });
    window.addEventListener("resize", function () { /* SVG scales itself */ });
  }).catch(function (e) {
    fail("The forecast could not be computed (" + (e && e.message) + ").");
  });
})();
