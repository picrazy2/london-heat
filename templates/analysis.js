/* ── What moves Beijing's air: the analysis charts ─────────────────────────
   Static figures from ml/analyze.py, ml/train_lead.py and ml/eval_realfc.py,
   baked into the page as window.ANALYSIS. Nothing is computed here beyond
   drawing. The live outlook above them is templates/forecast.js. */
(function () {
  "use strict";
  var D = window.ANALYSIS;
  if (!D) return;
  var NS = "http://www.w3.org/2000/svg";
  var tip = document.getElementById("tip");
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var SEASON = { DJF: ["Winter", "var(--night-2)"], MAM: ["Spring", "var(--day-1)"], JJA: ["Summer", "var(--positive)"], SON: ["Autumn", "var(--aqi-2)"] };

  function el(n, a) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); return e; }
  function txt(e, s) { e.textContent = s; return e; }
  function moveTip(ev) {
    var w = tip.offsetWidth, hh = tip.offsetHeight, x = Math.max(w / 2 + 6, Math.min(window.innerWidth - w / 2 - 6, ev.clientX));
    var y = ev.pointerType === "touch" ? ev.clientY - 48 : ev.clientY - 12;
    if (y - hh < 4) y = ev.clientY + hh + 28;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  function showTip(ev, html) { tip.innerHTML = html; tip.style.opacity = 1; moveTip(ev); }
  function hideTip() { tip.style.opacity = 0; }
  function hover(node, html) { var f = function (ev) { showTip(ev, html); }; node.addEventListener("pointermove", f); node.addEventListener("pointerdown", f); node.addEventListener("pointerleave", function (ev) { if (ev.pointerType !== "touch") hideTip(); }); }
  function lin(d0, d1, r0, r1) { var f = function (v) { return r0 + (v - d0) / (d1 - d0) * (r1 - r0); }; f.inv = function (p) { return d0 + (p - r0) / (r1 - r0) * (d1 - d0); }; return f; }
  function ticks(lo, hi, n) { var span = hi - lo, p = Math.pow(10, Math.floor(Math.log10(span / n))), s = [1, 2, 2.5, 5, 10].map(function (m) { return m * p; }).filter(function (s) { return span / s <= n; })[0] || p * 10, out = []; for (var v = Math.ceil(lo / s) * s; v <= hi + 1e-9; v += s) out.push(+v.toFixed(6)); return out; }
  function path(pts) { return pts.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(""); }
  function svgIn(id, W, H, label) { var host = document.getElementById(id); if (!host) return null; var s = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in w" + W, role: "img", "aria-label": label }); host.innerHTML = ""; host.appendChild(s); return s; }
  function yAxis(svg, y, tk, x0, x1, unit) { tk.forEach(function (t, i) { svg.appendChild(el("line", { class: "gridline", x1: x0, x2: x1, y1: y(t), y2: y(t) })); svg.appendChild(txt(el("text", { class: "tick", x: x0 - 5, y: y(t) + 3, "text-anchor": "end" }), (Math.abs(t) < 1 && t !== 0 ? t.toFixed(2) : t) + (unit && i === tk.length - 1 ? unit : ""))); }); }
  function xLab(svg, x, v, y0, s) { svg.appendChild(txt(el("text", { class: "tick", x: x(v), y: y0, "text-anchor": "middle" }), s)); }
  function endLabels(svg, ends, x0) {
    ends.sort(function (a, b) { return a.y - b.y; });
    for (var i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 12) ends[i].y = ends[i - 1].y + 12;
    ends.forEach(function (e) { var t = txt(el("text", { class: "tick", x: x0 + 6, y: e.y + 3, style: "fill:var(--ink);font-weight:640" }), e.t); svg.appendChild(t); });
  }

  /* ── skill by lead ───────────────────────────────────────────────────── */
  (function () {
    var W = 900, H = 260, L = 34, R = 150, T = 12, B = 26;
    var svg = svgIn("anLead", W, H, "Forecast skill by lead time"); if (!svg) return;
    var era = D.lead_skill.era5, real = D.lead_skill.real, clim = D.lead_skill.climatology.r2_log;
    var x = lin(0, 168, L, W - R), y = lin(-0.1, 1, H - B, T);
    yAxis(svg, y, [0, 0.2, 0.4, 0.6, 0.8, 1], L, W - R);
    [0, 24, 48, 72, 96, 120, 144, 168].forEach(function (t) { xLab(svg, x, t, H - 8, t ? t / 24 + " d" : "now"); });
    svg.appendChild(el("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), stroke: "var(--ink-faint)" }));
    svg.appendChild(el("line", { x1: L, x2: W - R, y1: y(clim), y2: y(clim), stroke: "var(--ink-faint)", "stroke-dasharray": "4 4" }));
    var series = [
      { name: "perfect weather forecast", c: "var(--accent)", pts: era.map(function (r) { return [r.lead, r.r2_log]; }).concat(real.slice(5).map(function (r) { return [r.lead_h, r["perfect_fc+nowcast"][0]]; })) },
      { name: "real forecast, as issued", c: "var(--aqi-4)", pts: [[1, era[0].r2_log], [6, era[2].r2_log]].concat(real.map(function (r) { return [r.lead_h, r["real_fc+nowcast"][0]]; })) },
      { name: "persistence", c: "var(--ink-faint)", pts: era.map(function (r) { return [r.lead, Math.max(-0.1, r.persistence_r2_log)]; }) },
    ];
    var ends = [{ y: y(clim), t: "climatology " + clim.toFixed(2) }];
    series.forEach(function (s) {
      var p = s.pts.map(function (q) { return [x(q[0]), y(q[1])]; });
      svg.appendChild(el("path", { d: path(p), fill: "none", stroke: s.c, "stroke-width": 2, "stroke-linejoin": "round" }));
      p.forEach(function (q, i) { var c = el("circle", { cx: q[0], cy: q[1], r: 9, fill: "transparent" }); hover(c, "<span class='k'>" + s.name + " · " + s.pts[i][0] + " h</span><br>R² <b>" + s.pts[i][1].toFixed(3) + "</b>"); svg.appendChild(c); });
      ends.push({ y: p[p.length - 1][1], t: s.name + " " + s.pts[s.pts.length - 1][1].toFixed(2) });
    });
    endLabels(svg, ends, W - R);
  })();

  /* ── wind rose ───────────────────────────────────────────────────────── */
  (function () {
    var host = document.getElementById("anRose"), seg = document.getElementById("anRoseSeg"); if (!host || !seg) return;
    var dirs = D.pdp_wind_rose.dirs, speeds = [1, 3, 6, 9], names = { all: "All year", DJF: "Winter", MAM: "Spring", JJA: "Summer", SON: "Autumn" };
    var compass = function (d) { return { 0: "N", 30: "NNE", 60: "ENE", 90: "E", 120: "ESE", 150: "SSE", 180: "S", 210: "SSW", 240: "WSW", 270: "W", 300: "WNW", 330: "NNW" }[d]; };
    var W = 900, H = 230, L = 58, R = 6, T = 24, B = 8, cw = (W - L - R) / dirs.length, ch = (H - T - B) / speeds.length;
    var vmax = 0; Object.keys(names).forEach(function (k) { speeds.forEach(function (s) { D.pdp_wind_rose[k][s].forEach(function (v) { vmax = Math.max(vmax, v); }); }); });
    var svg = svgIn("anRose", W, H, "Predicted PM2.5 by wind direction and speed"), g = el("g", {}); svg.appendChild(g);
    dirs.forEach(function (d, c) { svg.appendChild(txt(el("text", { class: "tick", x: L + c * cw + cw / 2, y: T - 8, "text-anchor": "middle" }), compass(d))); });
    speeds.forEach(function (s, r) { svg.appendChild(txt(el("text", { class: "tick", x: L - 8, y: T + r * ch + ch / 2 + 3, "text-anchor": "end" }), s + " m/s")); });
    function draw(k) {
      g.innerHTML = "";
      speeds.forEach(function (s, r) { dirs.forEach(function (d, c) {
        var v = D.pdp_wind_rose[k][s][c], t = v / vmax;
        var rc = el("rect", { x: L + c * cw + 1, y: T + r * ch + 1, width: cw - 2, height: ch - 2, rx: 5, fill: "var(--accent)", "fill-opacity": (0.06 + 0.94 * t).toFixed(3) });
        hover(rc, "<span class='k'>" + compass(d) + " at " + s + " m/s for 24 h</span><br><b>" + Math.round(v) + "</b> µg/m³");
        g.appendChild(rc);
        g.appendChild(txt(el("text", { x: L + c * cw + cw / 2, y: T + r * ch + ch / 2 + 4, "text-anchor": "middle", style: "font-size:11.5px;font-weight:640;font-variant-numeric:tabular-nums;pointer-events:none;fill:" + (t > 0.5 ? "#fff" : "var(--ink)") }), Math.round(v)));
      }); });
    }
    Object.keys(names).forEach(function (k, i) {
      var b = document.createElement("button"); b.textContent = names[k]; b.setAttribute("aria-pressed", String(i === 0));
      b.addEventListener("click", function () { seg.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", "false"); }); b.setAttribute("aria-pressed", "true"); draw(k); });
      seg.appendChild(b);
    });
    draw("all");
  })();

  /* ── north-wind onset ────────────────────────────────────────────────── */
  (function () {
    var W = 900, H = 260, L = 34, R = 140, T = 12, B = 26;
    var svg = svgIn("anOnset", W, H, "Measured PM2.5 around a strong north-wind onset"); if (!svg) return;
    var lags = D.wind_onset.lags, S = D.wind_onset.seasons;
    var series = [["DJF", S.DJF.mean, S.DJF.n], ["MAM", S.MAM.mean, S.MAM.n], ["JJA", S.JJA.mean, S.JJA.n], ["SON", S.SON.mean, S.SON.n]]
      .map(function (s) { return { name: SEASON[s[0]][0] + " (" + s[2] + ")", c: SEASON[s[0]][1], v: s[1] }; });
    series.push({ name: "Spring, dust reported (" + D.wind_onset.MAM_with_dust.n + ")", c: SEASON.MAM[1], v: D.wind_onset.MAM_with_dust.mean, dash: "5 4" });
    var ymax = Math.max.apply(null, series.map(function (s) { return Math.max.apply(null, s.v); })) * 1.08;
    var x = lin(-24, 48, L, W - R), y = lin(0, ymax, H - B, T);
    yAxis(svg, y, ticks(0, ymax, 5), L, W - R);
    [-24, -12, 0, 12, 24, 36, 48].forEach(function (t) { xLab(svg, x, t, H - 8, (t > 0 ? "+" : "") + t + " h"); });
    svg.appendChild(el("line", { x1: x(0), x2: x(0), y1: T, y2: H - B, stroke: "var(--ink-faint)", "stroke-dasharray": "2 3" }));
    var ends = [];
    series.forEach(function (s) {
      var p = lags.map(function (l, i) { return [x(l), y(s.v[i])]; });
      var a = { d: path(p), fill: "none", stroke: s.c, "stroke-width": 2, "stroke-linejoin": "round" }; if (s.dash) a["stroke-dasharray"] = s.dash;
      svg.appendChild(el("path", a)); ends.push({ y: p[p.length - 1][1], t: s.name.replace(/ \(.*\)/, "") + " " + Math.round(s.v[s.v.length - 1]) });
    });
    endLabels(svg, ends, W - R);
    var cross = el("line", { y1: T, y2: H - B, stroke: "var(--ink-faint)", opacity: 0 }); svg.appendChild(cross);
    var hit = el("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" });
    hit.addEventListener("pointermove", function (ev) { var r = svg.getBoundingClientRect(); var l = Math.round(x.inv((ev.clientX - r.left) / r.width * W)), i = l + 24; if (i < 0 || i >= lags.length) return; cross.setAttribute("x1", x(l)); cross.setAttribute("x2", x(l)); cross.setAttribute("opacity", .6); showTip(ev, "<span class='k'>" + (l > 0 ? "+" : "") + l + " h</span><br>" + series.map(function (s) { return s.name.replace(/ \(.*\)/, "") + " <b>" + Math.round(s.v[i]) + "</b>"; }).join("<br>")); });
    hit.addEventListener("pointerleave", function () { cross.setAttribute("opacity", 0); hideTip(); });
    svg.appendChild(hit);
  })();

  /* ── bars ────────────────────────────────────────────────────────────── */
  function bars(id, cats, series, opts) {
    var W = opts.w || 900, H = opts.h || 230, L = 38, R = 8, T = 12, B = 26;
    var svg = svgIn(id, W, H, opts.label || ""); if (!svg) return;
    var all = [].concat.apply([], series.map(function (s) { return s.v; }));
    var lo = Math.min(0, Math.min.apply(null, all)), hi = Math.max(0, Math.max.apply(null, all)), pad = (hi - lo) * .14;
    var y = lin(lo - (lo < 0 ? pad : 0), hi + (hi > 0 ? pad : 0), H - B, T), x = lin(0, cats.length, L, W - R);
    yAxis(svg, y, ticks(lo - (lo < 0 ? pad : 0), hi + (hi > 0 ? pad : 0), 5), L, W - R, opts.unit);
    svg.appendChild(el("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), stroke: "var(--ink-faint)" }));
    var gw = (W - L - R) / cats.length, bw = Math.min(40, (gw - 10) / series.length - 2);
    cats.forEach(function (c, i) {
      xLab(svg, function () { return x(i) + gw / 2; }, 0, H - 8, c);
      series.forEach(function (s, j) {
        var v = s.v[i], bx = x(i) + gw / 2 - (series.length * (bw + 2)) / 2 + j * (bw + 2), y0 = y(0), y1 = y(v);
        var r = el("rect", { x: bx, y: Math.min(y0, y1), width: bw, height: Math.abs(y1 - y0), rx: 3, fill: s.color || (v < 0 ? "var(--secondary)" : "var(--aqi-3)") });
        hover(r, "<span class='k'>" + (s.name ? s.name + " · " : "") + c + "</span><br><b>" + (v > 0 ? "+" : "") + v.toFixed(1) + (opts.unit || "") + "</b>");
        svg.appendChild(r);
        svg.appendChild(txt(el("text", { class: "tick", x: bx + bw / 2, y: v < 0 ? y1 + 11 : y1 - 4, "text-anchor": "middle" }), (v > 0 && opts.signed ? "+" : "") + Math.round(v) + (opts.unit || "")));
      });
    });
  }
  bars("anRain", ["0.5–2 mm", "2–5", "5–10", "10–20", "20–50", ">50 mm"],
    [{ name: "washout only", v: D.precip_counterfactual.map(function (r) { return r.effect_pct; }), color: "var(--accent)" },
     { name: "net, against a dry day", v: D.precip_counterfactual_dry_day.map(function (r) { return r.effect_pct; }), color: "var(--secondary)" }],
    { unit: "%", signed: true, label: "Effect of rain on predicted PM2.5" });
  bars("anRainMonth", MON, [{ v: MON.map(function (_, i) { return D.precip_stratified_by_month_pct[i + 1]; }) }], { unit: "%", signed: true, w: 460, h: 200, label: "Wet hours vs dry hours by month" });
  var tk = Object.keys(D.precip_timing);
  bars("anRainTiming", tk.map(function (k) { return k === "0" ? "while raining" : "+" + k + " h"; }), [{ v: tk.map(function (k) { return D.precip_timing[k].effect_pct; }), color: "var(--accent)" }], { unit: "%", signed: true, w: 460, h: 200, label: "Washout effect by time since rain" });

  /* ── partial dependence, small multiples ─────────────────────────────── */
  (function () {
    var host = document.getElementById("anPdp"); if (!host) return;
    var panels = [
      ["Month of year", D.pdp_month.grid, D.pdp_month.pred, function (g) { return MON[g - 1][0]; }],
      ["Relative humidity", D.pdp_rh.grid, D.pdp_rh.pred, function (g) { return g + "%"; }],
      ["Boundary-layer height", D.pdp_blh.grid, D.pdp_blh.pred, function (g) { return g + " m"; }, true],
      ["24 h mean wind speed", D.pdp_wspd24.grid, D.pdp_wspd24.pred, function (g) { return g + " m/s"; }],
      ["Hour of day", D.pdp_hour.grid, D.pdp_hour.pred, function (g) { return g + ":00"; }],
      ["Day of week", D.pdp_dow.grid, D.pdp_dow.pred, function (g) { return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][g]; }],
    ];
    host.innerHTML = "";
    panels.forEach(function (p) {
      var title = p[0], grid = p[1], pred = p[2], lab = p[3], logx = p[4];
      var card = document.createElement("div"); card.className = "aq-card an-small";
      card.innerHTML = "<div class='card-head'><h3>" + title + "</h3></div><div class='an-svg'></div>";
      host.appendChild(card);
      var W = 300, H = 150, L = 28, R = 8, T = 10, B = 22;
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in w" + W, role: "img", "aria-label": title }); card.querySelector(".an-svg").appendChild(svg);
      var xs = logx ? grid.map(Math.log10) : grid, x = lin(xs[0], xs[xs.length - 1], L, W - R), y = lin(0, 80, H - B, T);
      yAxis(svg, y, [0, 20, 40, 60, 80], L, W - R);
      var tks = grid.length > 5 ? grid.filter(function (_, i) { return i % Math.ceil(grid.length / 5) === 0 || i === grid.length - 1; }) : grid;
      tks.forEach(function (g) { xLab(svg, function () { return x(logx ? Math.log10(g) : g); }, 0, H - 7, lab(g)); });
      var pts = grid.map(function (g, i) { return [x(xs[i]), y(pred[i])]; });
      svg.appendChild(el("path", { d: path(pts) + "L" + pts[pts.length - 1][0] + " " + y(0) + "L" + pts[0][0] + " " + y(0) + "Z", fill: "var(--accent-soft)" }));
      svg.appendChild(el("path", { d: path(pts), fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "round" }));
      pts.forEach(function (q, i) { var c = el("circle", { cx: q[0], cy: q[1], r: 8, fill: "transparent" }); hover(c, "<span class='k'>" + lab(grid[i]) + "</span><br><b>" + Math.round(pred[i]) + "</b> µg/m³"); svg.appendChild(c); });
      var lo = pred.indexOf(Math.min.apply(null, pred)), hi = pred.indexOf(Math.max.apply(null, pred));
      [lo, hi].forEach(function (i) { svg.appendChild(el("circle", { cx: pts[i][0], cy: pts[i][1], r: 3.5, fill: "var(--accent)", stroke: "var(--surface-1)", "stroke-width": 2 })); svg.appendChild(txt(el("text", { class: "tick", x: Math.min(W - R - 10, Math.max(L + 10, pts[i][0])), y: pts[i][1] - 8, "text-anchor": "middle", style: "fill:var(--ink);font-weight:640" }), Math.round(pred[i]))); });
    });
  })();

  /* ── the year counterfactual ─────────────────────────────────────────── */
  (function () {
    var W = 900, H = 230, L = 34, R = 130, T = 12, B = 26;
    var svg = svgIn("anAnnual", W, H, "Annual mean PM2.5, measured and with 2014 emissions"); if (!svg) return;
    var rows = D.annual.filter(function (r) { return r.year >= 2014; }), yrs = rows.map(function (r) { return r.year; });
    var x = lin(yrs[0], yrs[yrs.length - 1], L, W - R), y = lin(0, 100, H - B, T);
    yAxis(svg, y, [0, 20, 40, 60, 80, 100], L, W - R);
    yrs.filter(function (v) { return v % 2 === 0; }).forEach(function (v) { xLab(svg, x, v, H - 8, v); });
    var a = rows.map(function (r) { return [x(r.year), y(r.actual)]; }), w = rows.map(function (r) { return [x(r.year), y(r.weather_only_2014_city)]; });
    svg.appendChild(el("path", { d: path(w), fill: "none", stroke: "var(--ink-faint)", "stroke-width": 2, "stroke-dasharray": "5 4" }));
    svg.appendChild(el("path", { d: path(a), fill: "none", stroke: "var(--accent)", "stroke-width": 2.5 }));
    rows.forEach(function (r, i) { [a, w].forEach(function (s) { var c = el("circle", { cx: s[i][0], cy: s[i][1], r: 9, fill: "transparent" }); hover(c, "<span class='k'>" + r.year + (r.year === 2026 ? " (to Sep)" : "") + "</span><br>measured <b>" + r.actual.toFixed(1) + "</b> · 2014 city <b>" + r.weather_only_2014_city.toFixed(1) + "</b>"); svg.appendChild(c); }); });
    endLabels(svg, [{ y: a[a.length - 1][1], t: "measured " + Math.round(rows[rows.length - 1].actual) }, { y: w[w.length - 1][1], t: "2014 city " + Math.round(rows[rows.length - 1].weather_only_2014_city) }], W - R);
  })();

  /* ── tables ──────────────────────────────────────────────────────────── */
  function fill(id, rows, cells) { var tb = document.getElementById(id); if (!tb) return; tb.innerHTML = rows.map(function (r) { return "<tr>" + cells(r) + "</tr>"; }).join(""); }
  fill("anDaily", D.daily_real, function (m) { return "<td>" + m.d + " day" + (m.d > 1 ? "s" : "") + " ahead</td><td class='n'>" + m.r2.toFixed(2) + "</td><td class='n'>" + m.mae.toFixed(1) + "</td><td class='n'>" + Math.round(m.hit * 100) + "%</td>"; });
  fill("anModels", D.models.concat(D.models2), function (m) { return "<td>" + m.model + "</td><td class='n'>" + m.r2_log.toFixed(3) + "</td><td class='n'>" + m.r2.toFixed(3) + "</td><td class='n'>" + m.mae.toFixed(1) + "</td>"; });
  fill("anAblation", D.ablation.slice().sort(function (a, b) { return b.r2_loss - a.r2_loss; }), function (m) { return "<td>" + m.group + "</td><td class='n'>−" + m.r2_loss.toFixed(3) + "</td>"; });
})();
