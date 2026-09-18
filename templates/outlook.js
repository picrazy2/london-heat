/* ── The outlook, as data ───────────────────────────────────────────────────
   Turns the model's hourly run into days: the daily mean and its verdict, the
   likely range and confidence, the clean and dirty hours, and the weather
   behind it. Used by the page (templates/forecast.js) and by the nightly
   worker (worker/), so the notification and the card never disagree.

   `outlook(PM25, model, meta, inp)` takes the /api/forecast payload and the
   two /model files; `compose(o, meta, day)` writes the notification for a day. */
(function (root, factory) {
  var m = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = m;
  else root.OUTLOOK = m;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var DAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var DAYL = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function ok(v) { return v != null && !Number.isNaN(v); }
  function compass(d) { return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(d / 45) % 8]; }
  function dateOf(s) { var m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})/.exec(s); return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4])); }

  /* The same breakpoint arithmetic as the page's air module. */
  function aqi(conc, scales, sc) {
    if (!ok(conc)) return null;
    var S = scales[sc || "us"], c = S.trunc ? Math.floor(conc * 10) / 10 : Math.round(conc), bp = S.bp, top = bp[bp.length - 1];
    if (c >= top[1]) return { i: top[3], cat: top[4] };
    for (var k = 0; k < bp.length; k++) if (c <= bp[k][1]) { var span = bp[k][1] - bp[k][0], f = span <= 0 ? 0 : (c - bp[k][0]) / span; return { i: Math.round(bp[k][2] + f * (bp[k][3] - bp[k][2])), cat: bp[k][4] }; }
    return { i: top[3], cat: top[4] };
  }
  function catName(cat, scales, sc) { return scales[sc || "us"].cats[cat].name; }

  /* The error distribution of daily means at each lead (ml/eval_realfc.py):
     push the forecast through the percentiles for its lead; the 10th and 90th
     bound the likely range, and the share landing in the forecast's own
     category is how sure the verdict is. */
  function confidence(mean, leadDays, meta, sc) {
    var I = meta.intervals && meta.intervals[String(Math.max(1, Math.min(7, leadDays)))];
    if (!I) return null;
    var cat = aqi(mean, meta.scales, sc).cat, inCat = 0, lo = null, hi = null;
    I.log_err.forEach(function (e, j) { var v = mean * Math.exp(e); if (I.pct[j] === 10) lo = v; if (I.pct[j] === 90) hi = v; if (aqi(v, meta.scales, sc).cat === cat) inCat++; });
    return { lo: lo, hi: hi, p: inCat / I.log_err.length };
  }

  /* The 80% band for an hour `lead` hours past the last reading: the 10th and
     90th percentiles of actual/forecast at that lead (ml/intervals_hourly.py),
     interpolated between the leads measured. */
  function bandFactors(meta, lead) {
    var I = meta.intervals_h; if (!I) return null;
    var L = I.leads, E = I.log_err, i10 = I.pct.indexOf(10), i90 = I.pct.indexOf(90);
    if (lead <= L[0]) return [Math.exp(E[0][i10]), Math.exp(E[0][i90])];
    if (lead >= L[L.length - 1]) { var e = E[E.length - 1]; return [Math.exp(e[i10]), Math.exp(e[i90])]; }
    for (var k = 1; k < L.length; k++) if (lead <= L[k]) { var f = (lead - L[k - 1]) / (L[k] - L[k - 1]); return [Math.exp(E[k - 1][i10] + f * (E[k][i10] - E[k - 1][i10])), Math.exp(E[k - 1][i90] + f * (E[k][i90] - E[k - 1][i90]))]; }
    return null;
  }

  function outlook(PM25, model, meta, inp) {
    var raw = inp.forecast, n = raw.time.length;
    var obs = raw.time.map(function (s) { var v = inp.obs && inp.obs[s.slice(0, 13) + ":00"]; return v == null ? null : v; });
    var run = PM25.run(model, raw, obs, inp.upwind, meta.level365);
    var F = run.F, t = raw.time, iNow = run.iNow;
    // Per hour, everything a strip or a tooltip wants.
    var hours = [];
    for (var i = 0; i < n; i++) {
      var bf = i > iNow ? bandFactors(meta, i - iNow) : null;
      hours.push({ i: i, t: t[i], d: dateOf(t[i]), obs: obs[i], w: run.w[i], fc: run.fc[i], past: i <= iNow,
        v: i <= iNow && obs[i] != null ? obs[i] : run.fc[i],
        lo: bf ? run.fc[i] * bf[0] : null, hi: bf ? run.fc[i] * bf[1] : null,
        ws: F.e_wind_speed_100m[i], dir: raw.wind_direction_100m[i], ws10: F.e_wind_speed_10m[i], dir10: raw.wind_direction_10m[i],
        vn: F.e_v_north100[i], blh: F.e_boundary_layer_height[i], rh: F.e_relative_humidity_2m[i], rain: F.e_precipitation[i],
        temp: F.e_temperature_2m[i], cloud: F.e_cloud_cover[i], inv: F.s_inv925[i] });
    }
    // Days: every local calendar day in the run, past and future alike.
    var days = [], byDay = {};
    hours.forEach(function (h) { var k = h.t.slice(0, 10); if (!byDay[k]) { byDay[k] = { date: k, hours: [] }; days.push(byDay[k]); } byDay[k].hours.push(h); });
    var nowDate = iNow >= 0 ? t[iNow].slice(0, 10) : null;
    days.forEach(function (d) {
      var hs = d.hours, fut = hs.filter(function (h) { return !h.past; }), src = fut.length ? fut : hs;
      var vals = src.map(function (h) { return h.v; }).filter(ok);
      d.n = hs.length; d.future = fut.length; d.today = d.date === nowDate; d.past = fut.length === 0;
      d.mean = vals.length ? vals.reduce(function (a, b) { return a + b; }, 0) / vals.length : null;
      var all = hs.map(function (h) { return h.v; });
      var lo = null, hi = null; hs.forEach(function (h) { if (!ok(h.v)) return; if (lo == null || h.v < lo.v) lo = h; if (hi == null || h.v > hi.v) hi = h; });
      d.min = lo; d.max = hi;
      var m = function (k, f) { var xs = hs.map(function (h) { return h[k]; }).filter(ok); return xs.length ? (f ? f(xs) : xs.reduce(function (a, b) { return a + b; }, 0) / xs.length) : null; };
      d.ws = m("ws"); d.vn = m("vn"); d.blh = m("blh"); d.blhMax = m("blh", function (x) { return Math.max.apply(null, x); }); d.blhMin = m("blh", function (x) { return Math.min.apply(null, x); });
      d.rh = m("rh"); d.rhMin = m("rh", function (x) { return Math.min.apply(null, x); }); d.rain = m("rain", function (x) { return x.reduce(function (a, b) { return a + b; }, 0); });
      d.tmax = m("temp", function (x) { return Math.max.apply(null, x); }); d.tmin = m("temp", function (x) { return Math.min.apply(null, x); }); d.cloud = m("cloud");
      var ux = 0, uy = 0; hs.forEach(function (h) { if (ok(h.ws) && ok(h.dir)) { ux += h.ws * Math.sin(h.dir * Math.PI / 180); uy += h.ws * Math.cos(h.dir * Math.PI / 180); } });
      d.dir = (Math.atan2(ux, uy) * 180 / Math.PI + 360) % 360;
      d.strongN = hs.filter(function (h) { return ok(h.vn) && h.vn >= 3.5; }).length;
      d.dow = dateOf(d.date + "T00").getUTCDay();
      // Lead in days from the last observed hour to this day's noon, for the confidence tables.
      d.lead = iNow >= 0 ? Math.max(1, Math.round((dateOf(d.date + "T12") - dateOf(t[iNow])) / 864e5)) : 1;
      d.aqi = d.mean != null ? aqi(d.mean, meta.scales) : null;
      d.conf = d.mean != null && !d.past ? confidence(d.mean, d.lead, meta) : null;
      // The best and worst stretch of daylight: 3 h windows, 08–20.
      var best = null, worst = null;
      for (var s = 8; s <= 17; s++) {
        var w = hs.filter(function (h) { var hh = h.d.getUTCHours(); return hh >= s && hh < s + 3 && ok(h.v); });
        if (w.length < 3) continue;
        var mv = w.reduce(function (a, h) { return a + h.v; }, 0) / 3;
        if (best == null || mv < best.v) best = { from: s, to: s + 3, v: mv }; if (worst == null || mv > worst.v) worst = { from: s, to: s + 3, v: mv };
      }
      d.best = best; d.worst = worst;
      var eve = hs.filter(function (h) { var hh = h.d.getUTCHours(); return hh >= 20 && ok(h.v); });
      d.evening = eve.length ? eve.reduce(function (a, h) { return a + h.v; }, 0) / eve.length : null;
    });
    return { t: t, hours: hours, days: days, iNow: iNow, obs: obs, raw: raw, up: inp.upwind, fetched: inp.fetched, byDay: byDay };
  }

  /* One sentence on why the day is what it is. */
  function why(d, scales) {
    var parts = [];
    var wind = compass(d.dir) + " " + d.ws.toFixed(1) + " m/s";
    if (d.strongN >= 6) parts.push("a north wind for " + d.strongN + " h clears it");
    else if (d.vn > 1) parts.push("a light northerly (" + wind + ")");
    else if (d.vn < -2) parts.push("a southerly (" + wind + ") bringing the plain's air");
    else parts.push("light wind (" + wind + ")");
    if (d.blhMax != null) parts.push("lid " + Math.round(d.blhMin / 10) * 10 + "–" + Math.round(d.blhMax / 50) * 50 + " m");
    if (d.rhMin != null) parts.push((d.rhMin < 35 ? "dry" : d.rh > 70 ? "humid" : "RH " + Math.round(d.rhMin) + "–" + Math.round(d.rh) + "%") + (d.rhMin < 35 ? " afternoon" : ""));
    if (d.rain > 0.5) parts.push(d.rain.toFixed(1) + " mm rain");
    return parts.join(" · ");
  }

  function compose(o, meta, day) {
    var d = o.byDay[day]; if (!d || d.mean == null) return null;
    var S = meta.scales, a = d.aqi, cat = catName(a.cat, S), cn = aqi(d.mean, S, "cn");
    var name = DAYL[d.dow] + " " + dateOf(day + "T00").getUTCDate() + " " + MON[dateOf(day + "T00").getUTCMonth()];
    var title = name + ": " + cat + " · " + Math.round(d.mean) + " µg/m³";
    var lines = [];
    lines.push("AQI " + a.i + " US · " + cn.i + " China" + (d.conf ? " · likely " + Math.round(d.conf.lo) + "–" + Math.round(d.conf.hi) + ", " + Math.round(d.conf.p * 100) + "% sure" : ""));
    if (d.best && d.worst) lines.push("Cleanest " + d.best.from + "–" + d.best.to + "h (" + Math.round(d.best.v) + "), worst " + (d.evening != null && d.evening > d.worst.v ? "evening (" + Math.round(d.evening) + ")" : d.worst.from + "–" + d.worst.to + "h (" + Math.round(d.worst.v) + ")"));
    lines.push(why(d, S).replace(/^./, function (c) { return c.toUpperCase(); }));
    if (d.tmax != null) lines.push(Math.round(d.tmin) + "–" + Math.round(d.tmax) + " °C" + (d.cloud != null ? ", " + (d.cloud < 25 ? "clear" : d.cloud < 60 ? "some cloud" : "cloudy") : ""));
    return { title: title, body: lines.join("\n"), url: "/beijing?topic=air&day=" + day, tag: "outlook-" + day,
             day: day, mean: d.mean, aqi: a.i, cat: a.cat, catName: cat, cn: cn.i, conf: d.conf, why: why(d, S) };
  }

  return { outlook: outlook, compose: compose, bandFactors: bandFactors, aqi: aqi, catName: catName, confidence: confidence, why: why, compass: compass, dateOf: dateOf, DAY: DAY, DAYL: DAYL, MON: MON };
});
