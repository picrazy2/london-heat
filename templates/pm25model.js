/* ── The PM2.5 forecast model, in the browser ──────────────────────────────
   A port of ml/dataset.engineer() and ml/forecast.py for the inputs a weather
   forecast can supply, plus an evaluator for the LightGBM trees exported by
   ml/export_model.py. Nothing is fitted here; the browser is handed a forecast,
   the last few days of readings, and the trees, and does the arithmetic.

   log1p(PM2.5) = W(weather at that hour and its 72 h history)
                + R(lead, what was known at the last observed hour)

   Every rolling window, shift and missing-value rule matches pandas exactly —
   ml/test_js.mjs checks this against a Python-generated vector to 1e-9 — so
   the trees are asked the same question they were trained on.               */
(function (root, factory) {
  var m = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = m;
  else root.PM25 = m;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var NaN_ = Number.NaN;
  function ok(v) { return v !== null && v !== undefined && !Number.isNaN(v); }
  function num(v) { return ok(v) ? +v : NaN_; }

  /* pandas Series.interpolate(limit=n, limit_direction="both"): linear inside a
     gap, clamped to the nearest value at the ends, at most n filled from each side. */
  function interp(a, limit) {
    var n = a.length, out = a.slice(), i = 0;
    while (i < n) {
      if (ok(out[i])) { i++; continue; }
      var j = i; while (j < n && !ok(out[j])) j++;
      var lo = i - 1, hi = j, gap = j - i;
      for (var k = i; k < j; k++) {
        var fromLeft = k - i, fromRight = j - 1 - k, v = NaN_;
        if (lo >= 0 && hi < n) v = a[lo] + (a[hi] - a[lo]) * (k - lo) / (hi - lo);
        else if (lo >= 0) v = a[lo]; else if (hi < n) v = a[hi];
        if (fromLeft < limit || fromRight < limit) out[k] = v;
      }
      i = j;
    }
    return out;
  }

  /* pandas rolling(w, min_periods=mp): inclusive of the current row, NaN-skipping. */
  function roll(a, w, mp, sum) {
    var n = a.length, out = new Array(n), s = 0, c = 0;
    for (var i = 0; i < n; i++) {
      if (ok(a[i])) { s += a[i]; c++; }
      var d = i - w; if (d >= 0 && ok(a[d])) { s -= a[d]; c--; }
      out[i] = c >= mp ? (sum ? s : s / c) : NaN_;
    }
    return out;
  }
  function rmean(a, w) { return roll(a, w, Math.max(1, Math.floor(w / 2)), false); }
  function rsum(a, w) { return roll(a, w, Math.max(1, Math.floor(w / 2)), true); }
  function shift(a, k) { return a.map(function (_, i) { return i - k >= 0 ? a[i - k] : NaN_; }); }
  function map2(a, b, f) { return a.map(function (v, i) { return ok(v) && ok(b[i]) ? f(v, b[i]) : NaN_; }); }
  var D2R = Math.PI / 180;

  /* "2026-09-07T13:00" (Beijing local, as Open-Meteo returns with timezone=) -> parts. */
  function parseLocal(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(s);
    return { y: +m[1], mo: +m[2], d: +m[3], h: +m[4], ms: Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) };
  }

  function timeFeatures(times, cny) {
    var n = times.length, F = {};
    var keys = ["hour", "dow", "month", "doy", "hour_sin", "hour_cos", "doy_sin", "doy_cos", "dow_sin", "dow_cos", "weekend", "cny_window", "cny_night"];
    keys.forEach(function (k) { F[k] = new Array(n); });
    for (var i = 0; i < n; i++) {
      var p = parseLocal(times[i]);
      var doy = Math.floor((p.ms - Date.UTC(p.y, 0, 1)) / 864e5) + 1;
      var dow = (new Date(p.ms).getUTCDay() + 6) % 7;      // pandas: Monday = 0
      var c = cny[p.y] ? parseLocal(cny[p.y] + "T00:00") : parseLocal(p.y + "-02-01T00:00");
      var dh = (p.ms - c.ms) / 36e5;
      F.hour[i] = p.h; F.dow[i] = dow; F.month[i] = p.mo; F.doy[i] = doy;
      F.hour_sin[i] = Math.sin(2 * Math.PI * p.h / 24); F.hour_cos[i] = Math.cos(2 * Math.PI * p.h / 24);
      F.doy_sin[i] = Math.sin(2 * Math.PI * doy / 365.25); F.doy_cos[i] = Math.cos(2 * Math.PI * doy / 365.25);
      F.dow_sin[i] = Math.sin(2 * Math.PI * dow / 7); F.dow_cos[i] = Math.cos(2 * Math.PI * dow / 7);
      F.weekend[i] = dow >= 5 ? 1 : 0;
      F.cny_window[i] = dh >= -48 && dh <= 168 ? 1 : 0;
      F.cny_night[i] = dh >= -6 && dh <= 12 ? 1 : 0;
    }
    return F;
  }

  /* Open-Meteo hourly block -> the weather feature table, one row per hour.
     `raw` is {time:[...], temperature_2m:[...], ...}; `cols` is the model's
     column order; `level365` the emissions baseline from the build. */
  function features(raw, cols, level365, cny) {
    var n = raw.time.length, F = timeFeatures(raw.time, cny || {});
    var g = function (k) { return interp((raw[k] || []).map(num), 6); };
    var SURF = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation", "rain", "snowfall",
      "pressure_msl", "surface_pressure", "cloud_cover", "cloud_cover_low", "wind_speed_10m", "wind_gusts_10m",
      "wind_speed_100m", "boundary_layer_height", "shortwave_radiation", "vapour_pressure_deficit"];
    SURF.forEach(function (k) { F["e_" + k] = g(k); });
    var ws10 = F.e_wind_speed_10m, wd10 = g("wind_direction_10m"), ws100 = F.e_wind_speed_100m, wd100 = g("wind_direction_100m");
    F.e_v_north = map2(ws10, wd10, function (s, d) { return s * Math.cos(d * D2R); });
    F.e_u_east = map2(ws10, wd10, function (s, d) { return s * Math.sin(d * D2R); });
    F.e_v_north100 = map2(ws100, wd100, function (s, d) { return s * Math.cos(d * D2R); });
    F.e_u_east100 = map2(ws100, wd100, function (s, d) { return s * Math.sin(d * D2R); });
    F.e_blh_missing = F.e_boundary_layer_height.map(function (v) { return ok(v) ? 0 : 1; });
    F.e_precip_flag = F.e_precipitation.map(function (v) { return ok(v) && v > 0.1 ? 1 : 0; });
    F.e_snow_flag = F.e_snowfall.map(function (v) { return ok(v) && v > 0.05 ? 1 : 0; });
    [3, 6, 12, 24, 48, 72].forEach(function (w) { F["e_precipitation_s" + w] = rsum(F.e_precipitation, w); });
    [6, 24].forEach(function (w) { F["e_boundary_layer_height_m" + w] = rmean(F.e_boundary_layer_height, w); });
    [6, 12, 24, 48].forEach(function (w) { F["e_v_north_m" + w] = rmean(F.e_v_north, w); });
    [12, 24].forEach(function (w) { F["e_v_north100_m" + w] = rmean(F.e_v_north100, w); });
    [12, 24, 48].forEach(function (w) { F["e_wind_speed_10m_m" + w] = rmean(F.e_wind_speed_10m, w); });
    [12, 24].forEach(function (w) { F["e_wind_speed_100m_m" + w] = rmean(F.e_wind_speed_100m, w); });
    F.e_relative_humidity_2m_m24 = rmean(F.e_relative_humidity_2m, 24);
    [6, 24].forEach(function (w) { F["e_precip_flag_s" + w] = rsum(F.e_precip_flag, w); F["e_snow_flag_s" + w] = rsum(F.e_snow_flag, w); });
    F.e_temp_d24 = map2(F.e_temperature_2m, shift(F.e_temperature_2m, 24), function (a, b) { return a - b; });
    F.e_pres_d24 = map2(F.e_pressure_msl, shift(F.e_pressure_msl, 24), function (a, b) { return a - b; });
    // A ventilation clock: hours since the wind last blew hard from the north.
    var thr = 5 * Math.cos(45 * D2R), last = -1, strong = new Array(n);
    F.e_hrs_since_strong_n = new Array(n);
    for (var i = 0; i < n; i++) {
      var v = F.e_v_north[i], u = F.e_u_east[i];
      strong[i] = ok(v) && ok(u) && v >= thr && v > Math.abs(u) ? 1 : 0;
      if (strong[i]) last = i;
      F.e_hrs_since_strong_n[i] = last < 0 ? 96 : Math.min(i - last, 96);
    }
    F.e_strong_n_hours24 = roll(strong, 24, 1, true);
    // Sounding-style features: the pressure levels sampled at the two launch
    // hours and carried forward up to 18 h, as the radiosonde was in training.
    var t2 = F.e_temperature_2m, S = {};
    S.s_inv925 = map2(g("temperature_925hPa"), t2, function (a, b) { return a - b; });
    S.s_inv850 = map2(g("temperature_850hPa"), t2, function (a, b) { return a - b; });
    [925, 850, 700].forEach(function (p) {
      var ws = g("wind_speed_" + p + "hPa"), wd = g("wind_direction_" + p + "hPa");
      S["s_ws" + p] = ws;
      S["s_vn" + p] = map2(ws, wd, function (s, d) { return s * Math.cos(d * D2R); });
    });
    var hours = raw.time.map(function (s) { return parseLocal(s).h; });
    Object.keys(S).forEach(function (k) {
      var src = S[k], out = new Array(n), lastI = -1, lastV = NaN_;
      for (var i = 0; i < n; i++) {
        if ((hours[i] === 8 || hours[i] === 20) && ok(src[i])) { lastI = i; lastV = src[i]; }
        out[i] = lastI >= 0 && i - lastI <= 18 ? lastV : NaN_;
      }
      F[k] = out;
    });
    F.s_inv925_m24 = rmean(F.s_inv925, 24); F.s_vn850_m24 = rmean(F.s_vn850, 24); F.s_vn925_m24 = rmean(F.s_vn925, 24);
    F.level365 = new Array(n).fill(level365);
    var X = new Array(n);
    for (var r = 0; r < n; r++) {
      var row = new Float64Array(cols.length);
      for (var c = 0; c < cols.length; c++) { var col = F[cols[c]]; row[c] = col ? num(col[r]) : NaN_; }
      X[r] = row;
    }
    return { X: X, F: F };
  }

  /* The compact tree format from ml/export_model.py. */
  function predict(trees, X) {
    var out = new Float64Array(X.length);
    for (var k = 0; k < X.length; k++) {
      var row = X[k], s = 0;
      for (var t = 0; t < trees.length; t++) {
        var T = trees[t], f = T.f, th = T.t, l = T.l, r = T.r, d = T.d, i = 0;
        while (i >= 0) {
          var x = row[f[i]], dd = d[i];
          if (dd >= 3) { if (Number.isNaN(x) || x === 0) { i = dd === 4 ? l[i] : r[i]; continue; } }
          else if (Number.isNaN(x)) { if (dd === 2) x = 0; else { i = dd === 1 ? l[i] : r[i]; continue; } }
          i = x <= th[i] ? l[i] : r[i];
        }
        s += T.v[-i - 1];
      }
      out[k] = s;
    }
    return out;
  }

  /* The residual model's inputs for every hour after the last observation.
     `w` is W's log-scale prediction per hour; `obs` PM2.5 per hour (null where
     unmeasured) on the same index; `iNow` the index of the last observed hour;
     `upwind` the city-group readings at that hour. Mirrors ml/forecast.py. */
  function residualFeatures(colsR, w, obs, iNow, upwind, F) {
    var n = w.length, r = new Array(n);
    for (var i = 0; i < n; i++) r[i] = ok(obs[i]) ? Math.log1p(obs[i]) - w[i] : NaN_;
    var tail = function (k) { var s = 0, c = 0; for (var j = Math.max(0, iNow - k + 1); j <= iNow; j++) if (ok(r[j])) { s += r[j]; c++; } return c ? s / c : NaN_; };
    var rLast = r[iNow], rM6 = tail(6), rM24 = tail(24), pmLast = Math.log1p(obs[iNow]), wLast = w[iNow];
    var up = function (k) { return upwind && ok(upwind[k]) ? Math.log1p(upwind[k]) : NaN_; };
    var vn = F.e_v_north100, pr = F.e_precipitation, hourIssue = F.hour[iNow];
    var rows = [], idx = [];
    var cs = 0, cp = 0;
    for (var t = iNow + 1; t < n; t++) {
      cs += ok(vn[t]) ? vn[t] : 0; cp += ok(pr[t]) ? pr[t] : 0;
      var lead = t - iNow;
      var f = { lead: lead, r_last: rLast, r_last_m6: rM6, r_last_m24: rM24, pm25_last: pmLast, w_last: wLast, w_now: w[t],
        c_south_PM25_last: up("c_south_PM25"), c_east_PM25_last: up("c_east_PM25"), c_northwest_PM25_last: up("c_northwest_PM25"),
        c_north_PM25_last: up("c_north_PM25"), c_southwest_PM25_last: up("c_southwest_PM25"),
        c_south_PM10_last: up("c_south_PM10"), c_northwest_PM10_last: up("c_northwest_PM10"),
        vn100_mean_window: cs / lead, precip_window: cp, hour_issue: hourIssue };
      f.south_grad_last = f.c_south_PM25_last - pmLast; f.nw_grad_last = f.c_northwest_PM25_last - pmLast;
      var row = new Float64Array(colsR.length);
      for (var c = 0; c < colsR.length; c++) row[c] = num(f[colsR[c]]);
      rows.push(row); idx.push(t);
    }
    return { X: rows, idx: idx };
  }

  /* Everything at once: -> {t, w (µg/m³ per hour from weather alone), fc (with
     the nowcast correction for hours after iNow), iNow}. */
  function run(model, raw, obs, upwind, level365) {
    var fw = features(raw, model.w.cols, level365, model.cny);
    var w = predict(model.w.trees, fw.X);
    var iNow = -1;
    for (var i = obs.length - 1; i >= 0; i--) if (ok(obs[i])) { iNow = i; break; }
    var fc = Array.from(w, function (v) { return Math.expm1(v); });
    if (iNow >= 0) {
      var rf = residualFeatures(model.r.cols, w, obs, iNow, upwind, fw.F);
      var corr = predict(model.r.trees, rf.X);
      rf.idx.forEach(function (t, k) { fc[t] = Math.expm1(w[t] + corr[k]); });
    }
    return { t: raw.time, w: Array.from(w, function (v) { return Math.expm1(v); }), fc: fc, iNow: iNow, F: fw.F };
  }

  return { features: features, predict: predict, residualFeatures: residualFeatures, run: run, interp: interp, rmean: rmean };
});
