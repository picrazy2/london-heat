/* ── The temperature module ────────────────────────────────────────────────
   Driven entirely by the TEMP object the build injects, so both cities run this
   file unchanged. Nothing here knows that London's hot day is 25 C and
   Beijing's is 30; it knows there are four metrics and where their thresholds,
   colours and labels are written down. */
(function () {
  "use strict";
  var T = window.TEMP, WX = window.WX;
  if (!T || !WX) return;

  var NS = "http://www.w3.org/2000/svg";
  var MABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var MFULL = ["January","February","March","April","May","June","July","August",
               "September","October","November","December"];
  var MSTART = [1,32,60,91,121,152,182,213,244,274,305,335,366];
  var M = T.metrics, HIST = T.hist, MON = T.monthly, ALL = T.all;
  var YEARS = HIST.years, N = YEARS.length, PARTIAL = HIST.partial;
  var tip = document.getElementById("tip");

  function el(n, a) {
    var e = document.createElementNS(NS, n);
    for (var k in a) if (a[k] != null) e.setAttribute(k, a[k]);
    return e;
  }
  function txt(e, s) { e.textContent = s; return e; }
  function fmtDay(dn) { var m = 0; while (m < 11 && MSTART[m+1] <= dn) m++; return (dn - MSTART[m] + 1) + " " + MABBR[m]; }
  function sign(v, d) { d = d == null ? 1 : d; return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d); }
  function ord(n) {
    var s = ["th","st","nd","rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  /* ── the segmented controls ───────────────────────────────────────────── */
  function segment(id, onChange) {
    var root = document.getElementById(id);
    if (!root) return function () {};
    var btns = [].slice.call(root.querySelectorAll("button"));
    var thumb = root.querySelector(".thumb");
    function place() {
      var i = btns.findIndex(function (b) { return b.getAttribute("aria-checked") === "true"; });
      if (i < 0) i = 0;
      thumb.style.width = "calc((100% - 8px) / " + btns.length + ")";
      thumb.style.transform = "translateX(calc(" + i + " * 100%))";
    }
    btns.forEach(function (b) {
      b.addEventListener("click", function () {
        btns.forEach(function (o) { o.setAttribute("aria-checked", String(o === b)); });
        place();
        onChange(b.dataset);
      });
    });
    place();
    // The thumb is positioned from the button count, which is stable, but the
    // track width is not until layout settles on a slow first paint.
    window.addEventListener("resize", place);
    return place;
  }

  /* ── tooltip ──────────────────────────────────────────────────────────── */
  function showTip(ev, html) {
    tip.innerHTML = html;
    tip.style.opacity = 1;
    moveTip(ev);
  }
  function moveTip(ev) {
    tip.style.left = ev.clientX + "px";
    tip.style.top = (ev.clientY - 12) + "px";
  }
  function hideTip() { tip.style.opacity = 0; }

  /* ── view 1: the record ───────────────────────────────────────────────── */
  var WIN = "full";
  function vals(m)   { return WIN === "ytd" ? HIST[m.key + "y"] : HIST[m.key]; }
  function streaks(m) { return WIN === "ytd" ? HIST[m.key + "sy"] : HIST[m.key + "s"]; }

  /* A ceiling a tick can land on, with room above the tallest bar. Without the
     headroom a record year's bar touches the frame and its label has nowhere to
     sit; without the "nice" step the axis reads 0, 12.5, 25. */
  function niceMax(v) {
    if (!(v > 0)) return 1;
    var target = v * 1.12;
    var mag = Math.pow(10, Math.floor(Math.log10(target)));
    var steps = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (var i = 0; i < steps.length; i++) {
      var c = steps[i] * mag;
      if (c >= target - 1e-9) return c >= 10 ? Math.round(c) : Math.ceil(c);
    }
    return Math.ceil(target);
  }
  function ticks(max) {
    var divs = [5, 4, 3, 2];
    for (var i = 0; i < divs.length; i++) {
      if (max % divs[i] === 0 && max / divs[i] >= 1) {
        var out = [];
        for (var t = 0; t <= max + 1e-9; t += max / divs[i]) out.push(Math.round(t));
        return out;
      }
    }
    var small = [];
    for (var t2 = 0; t2 <= max + 1e-9; t2++) small.push(t2);
    return small;
  }

  // The right margin holds nothing but a gutter now. The baseline used to be
  // labelled inside it, which cost the plot 16% of its width to carry two lines
  // of static text; that text reads the same in a key under the chart, where it
  // costs nothing and cannot collide with a bar.
  var CW = 560, CH = 200, CM = { t: 22, r: 14, b: 26, l: 30 };
  var cpw = CW - CM.l - CM.r, cph = CH - CM.t - CM.b;

  function baselineAvg(v) {
    var i0 = YEARS.indexOf(T.baseline[0]), i1 = YEARS.indexOf(T.baseline[1]);
    if (i0 < 0 || i1 < i0) return null;
    var s = 0; for (var i = i0; i <= i1; i++) s += v[i];
    return s / (i1 - i0 + 1);
  }
  function baselineLabel() {
    return T.baseline[0] + "–" + String(T.baseline[1]).slice(2) + " avg";
  }

  function annualChart(m, v, partialYr) {
    var max = niceMax(Math.max.apply(null, v));
    var normal = baselineAvg(v);
    // The record excludes the year still running, so a part-year drawing level
    // with 1976 does not quietly take 1976's name off the label.
    var recVal = -1, recIdx = -1;
    for (var k = 0; k < N; k++) if (YEARS[k] !== partialYr && v[k] > recVal) { recVal = v[k]; recIdx = k; }

    var svg = el("svg", { viewBox: "0 0 " + CW + " " + CH, class: "chart chart-in",
      role: "img", "aria-label": m.label + " (" + m.sub + ") per year, " + YEARS[0] + " to " + YEARS[N-1] });
    var x = function (i) { return CM.l + (i + 0.5) / N * cpw; };
    var y = function (val) { return CM.t + cph - (val / max) * cph; };
    var bw = Math.max(2.5, cpw / N - 1.1);

    ticks(max).forEach(function (t) {
      svg.appendChild(el("line", { class: "gridline", x1: CM.l, x2: CM.l + cpw, y1: y(t), y2: y(t) }));
      svg.appendChild(txt(el("text", { class: "tick", x: CM.l - 6, y: y(t) + 3, "text-anchor": "end" }), t));
    });
    svg.appendChild(el("line", { class: "axisline", x1: CM.l, x2: CM.l + cpw, y1: y(0), y2: y(0) }));

    var step = N > 45 ? 10 : 5;
    for (var d = Math.ceil(YEARS[0] / step) * step; d <= YEARS[N-1]; d += step) {
      var ix = YEARS.indexOf(d); if (ix < 0) continue;
      svg.appendChild(txt(el("text", { class: "tick", x: x(ix), y: CH - 8, "text-anchor": "middle" }), d));
    }

    var defs = el("defs", {});
    var pat = el("pattern", { id: "h-" + T.slug + "-" + m.key, width: 4, height: 4,
      patternTransform: "rotate(45)", patternUnits: "userSpaceOnUse" });
    pat.appendChild(el("rect", { width: 4, height: 4, fill: "var(" + m.css + ")", "fill-opacity": ".22" }));
    pat.appendChild(el("line", { x1: 0, y1: 0, x2: 0, y2: 4, stroke: "var(" + m.css + ")", "stroke-width": 2 }));
    defs.appendChild(pat);
    svg.appendChild(defs);

    v.forEach(function (val, i) {
      var part = YEARS[i] === partialYr;
      var h = y(0) - y(val);
      var r = el("rect", { class: "bar", x: x(i) - bw / 2, y: y(val), width: bw,
        height: Math.max(0, h), rx: Math.min(2, bw / 2),
        fill: part ? "url(#h-" + T.slug + "-" + m.key + ")" : "var(" + m.css + ")" });
      if (part) { r.setAttribute("stroke", "var(" + m.css + ")"); r.setAttribute("stroke-width", "1"); }
      r.addEventListener("mouseenter", function (ev) {
        var rel = normal == null ? "" :
          "<br><span style='opacity:.7'>" + sign(val - normal) + " vs " + T.baseline[0] + "–" + String(T.baseline[1]).slice(2) + " normal</span>";
        showTip(ev, "<span class='k'>" + YEARS[i] + (part ? " · part-year" : "") + "</span><br><b>" +
          val + "</b> " + m.unit + " <span style='opacity:.6'>" + m.sub + "</span>" + rel);
      });
      r.addEventListener("mousemove", moveTip);
      r.addEventListener("mouseleave", hideTip);
      svg.appendChild(r);
    });

    if (normal != null) {
      svg.appendChild(el("line", { class: "ref", x1: CM.l, x2: CM.l + cpw, y1: y(normal), y2: y(normal) }));
    }
    if (recIdx >= 0) {
      svg.appendChild(txt(el("text", { class: "mark-lab", x: x(recIdx), y: y(recVal) - 5, "text-anchor": "middle" }),
        YEARS[recIdx] + ": " + recVal));
    }
    return svg;
  }

  function renderTiles() {
    var host = document.getElementById("tmTiles");
    host.innerHTML = "";
    var i = YEARS.indexOf(PARTIAL);
    M.forEach(function (m) {
      var v = HIST[m.key + "y"], now = i >= 0 ? v[i] : 0;
      var normal = baselineAvg(v);
      var rank = 1; for (var k2 = 0; k2 < N; k2++) if (v[k2] > now) rank++;
      var d = document.createElement("div");
      d.className = "tile";
      d.style.setProperty("--tint", "var(" + m.css + ")");
      d.innerHTML =
        '<div class="rank' + (rank <= 3 ? " top" : "") + '">' + ord(rank) + " of " + N + "</div>" +
        '<div class="lab">' + m.label + '</div><div class="sub">' + m.sub + "</div>" +
        '<div class="num display">' + now + "<small>" + m.unit + "</small></div>" +
        '<div class="delta">' + (normal == null ? "" :
          "<b>" + sign(now - normal) + "</b> vs " + T.baseline[0] + "–" +
          String(T.baseline[1]).slice(2) + ", same window") + "</div>";
      host.appendChild(d);
    });
  }

  function renderCharts() {
    var host = document.getElementById("tmCharts");
    host.innerHTML = "";
    var partialYr = WIN === "full" ? PARTIAL : null;
    M.forEach(function (m) {
      var v = vals(m);
      var card = document.createElement("figure");
      card.className = "chart-card";
      card.style.setProperty("--tint", "var(" + m.css + ")");
      card.innerHTML =
        '<div class="card-head"><h3><span class="swatch"></span>' + m.label + "</h3>" +
        '<span class="sub">' + m.sub + "</span></div>";
      card.appendChild(annualChart(m, v, partialYr));
      var normal = baselineAvg(v);
      if (normal != null) {
        var key = document.createElement("div");
        key.className = "chartkey";
        key.innerHTML = "<i></i>" + baselineLabel() + " · <b>" + normal.toFixed(1) +
          "</b> " + m.unit;
        card.appendChild(key);
      }
      var cap = document.createElement("figcaption");
      cap.className = "cap";
      cap.innerHTML = T.captions[m.key] || "";
      card.appendChild(cap);
      host.appendChild(card);
    });
  }

  /* ── view 2: rankings ─────────────────────────────────────────────────── */
  function rankCard(title, sub, rows, meYear, noneNote, provisional) {
    var d = document.createElement("div");
    d.className = "card card-tight";
    var body = '<div class="card-head"><h3>' + title + "</h3><span class='sub'>" + sub + "</span></div>";
    body += "<table class='rtbl'><tbody>";
    if (!rows.length) {
      body += "<tr class='none'><td colspan='3'>" + noneNote + "</td></tr>";
    } else {
      var lastRank = 0;
      rows.forEach(function (r) {
        if (r.rank > lastRank + 1) body += "<tr class='gap'><td colspan='3'>···</td></tr>";
        lastRank = r.rank;
        body += "<tr class='" + (r.year === meYear ? "me" : "") + "'><td class='rk'>" + r.rank +
          "</td><td>" + r.year + (r.year === meYear ? " ✿" : "") + "</td><td class='rv'>" + r.val + "</td></tr>";
      });
    }
    if (provisional) {
      body += "<tr class='prov'><td class='rk'>–</td><td>" + provisional.label +
        "<span class='pflag'>running</span></td><td class='rv'>" + provisional.val + "</td></tr>";
    }
    body += "</tbody></table>";
    d.innerHTML = body;
    return d;
  }

  /* Top ten, plus the current year wherever it lands. Ties share a rank, which
     is why the rank is computed from the value and not from the row index. */
  function topRows(values, years, n, meYear) {
    var pairs = years.map(function (y, i) { return { year: y, val: values[i] }; })
      .filter(function (p) { return p.val != null; });
    pairs.sort(function (a, b) { return b.val - a.val || a.year - b.year; });
    pairs.forEach(function (p, i) {
      p.rank = (i > 0 && pairs[i-1].val === p.val) ? pairs[i-1].rank : i + 1;
    });
    var out = pairs.slice(0, n);
    if (meYear != null && !out.some(function (p) { return p.year === meYear; })) {
      var me = pairs.filter(function (p) { return p.year === meYear; })[0];
      if (me) out.push(me);
    }
    return out;
  }

  function renderStreaks() {
    var host = document.getElementById("tmStreaks");
    host.innerHTML = "";
    M.forEach(function (m) {
      var v = streaks(m);
      var rows = topRows(v, YEARS, 8, PARTIAL).filter(function (r) { return r.val > 0; });
      host.appendChild(rankCard(m.label, "consecutive " + m.unit,
        rows.map(function (r) { return { rank: r.rank, year: r.year, val: r.val + "" }; }),
        PARTIAL, "No run of consecutive " + m.unit + " has ever been recorded."));
    });
  }

  var MMODE = "avg", MOFF = 0;
  function renderMonths() {
    var host = document.getElementById("tmMonths");
    host.innerHTML = "";
    // The window ends at the last month that has actually finished, so the four
    // cards are always four months you can read a completed figure for.
    var anchor = (MON.ay - MON.years[0]) * 12 + (MON.am - 1) + MOFF;
    var first = anchor - 3;
    var labels = [];
    for (var s = 0; s < 4; s++) {
      var idx = first + s;
      var yy = MON.years[0] + Math.floor(idx / 12), mm = (idx % 12 + 12) % 12;
      labels.push({ y: yy, m: mm });
      var series = MON[MMODE][String(mm + 1)];
      var rows = topRows(series, MON.years, 6, null);
      // Which year of this month to highlight: the most recent one that exists.
      var me = yy;
      var prov = null;
      if (MON.part && MON.part.m === mm + 1) {
        prov = { label: MON.part.y + " to " + MON.part.through + " (" + MON.part.days + " days)",
                 val: MON.part[MMODE] == null ? "–" : MON.part[MMODE].toFixed(1) + "°" };
      }
      rows = rows.map(function (r) { return { rank: r.rank, year: r.year, val: r.val.toFixed(1) + "°" }; });
      host.appendChild(rankCard(MFULL[mm], { avg: "daily mean", hi: "average high", lo: "average low" }[MMODE],
        rows, me, "No complete month on record.", prov));
    }
    var a = labels[0], b = labels[3];
    document.getElementById("tmRange").textContent =
      MABBR[a.m] + " " + a.y + " – " + MABBR[b.m] + " " + b.y;
  }

  var SORT = { col: 0, dir: -1 };
  function renderTable() {
    var t = document.getElementById("tmTable");
    var cols = [{ k: "year", l: "Year" }].concat(
      M.map(function (m) { return { k: m.key, l: m.label, sub: m.sub }; }),
      [{ k: "hi", l: "Avg high" }, { k: "lo", l: "Avg low" }, { k: "avg", l: "Daily mean" }]);
    var rows = YEARS.map(function (y, i) {
      var r = { year: y };
      M.forEach(function (m) { r[m.key] = vals(m)[i]; });
      r.hi = MON.ann.hi[i]; r.lo = MON.ann.lo[i]; r.avg = MON.ann.avg[i];
      return r;
    });
    var key = cols[SORT.col].k;
    rows.sort(function (a, b) {
      var av = a[key], bv = b[key];
      if (av == null && bv == null) return a.year - b.year;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av - bv) * SORT.dir || a.year - b.year;
    });
    var head = "<thead><tr>" + cols.map(function (c, i) {
      return "<th data-col='" + i + "'>" + c.l + (SORT.col === i ? "<span class='ar'>" + (SORT.dir < 0 ? "▾" : "▴") + "</span>" : "") + "</th>";
    }).join("") + "</tr></thead>";
    var body = "<tbody>" + rows.map(function (r) {
      return "<tr class='" + (r.year === PARTIAL ? "me" : "") + "'>" + cols.map(function (c) {
        var v = r[c.k];
        if (c.k === "year") return "<td>" + v + (v === PARTIAL ? " ✿" : "") + "</td>";
        if (v == null) return "<td class='na'>–</td>";
        return "<td>" + (["hi","lo","avg"].indexOf(c.k) >= 0 ? v.toFixed(1) + "°" : v) + "</td>";
      }).join("") + "</tr>";
    }).join("") + "</tbody>";
    t.innerHTML = head + body;
    [].forEach.call(t.querySelectorAll("th"), function (th) {
      th.addEventListener("click", function () {
        var i = +th.dataset.col;
        if (SORT.col === i) SORT.dir = -SORT.dir; else { SORT.col = i; SORT.dir = -1; }
        renderTable();
      });
    });
  }

  /* ── view 3: the daily explorer ───────────────────────────────────────── */
  var EW = 1040, EH = 470, EM = { t: 18, r: 16, b: 28, l: 34 };
  var epw = EW - EM.l - EM.r, eph = EH - EM.t - EM.b;
  var YMIN = T.yMin, YMAX = T.yMax;
  var ex = function (dn) { return EM.l + (dn - 1) / 364 * epw; };
  var ey = function (v) { return EM.t + eph - (v - YMIN) / (YMAX - YMIN) * eph; };

  function renderYear(yr) {
    var D = ALL[yr];
    if (!D) return;
    var pts = [], curMax = {}, curMin = {};
    for (var i = 0; i < D.x.length; i++) {
      var hi = D.x[i]; if (hi == null) continue;
      var lo = D.n[i], dn = D.s + i;
      pts.push([dn, hi, lo]); curMax[dn] = hi; curMin[dn] = lo;
    }
    if (!pts.length) return;

    var counts = M.map(function () { return 0; });
    var peak = [0, -99], cold = [0, 99];
    pts.forEach(function (p) {
      var dn = p[0], h = p[1], l = p[2];
      M.forEach(function (m, k) {
        var v = m.series === "max" ? h : l;
        if (v != null && v >= m.thr) counts[k]++;
      });
      if (h > peak[1]) peak = [dn, h];
      if (l != null && l < cold[1]) cold = [dn, l];
    });
    var lastDoy = pts[pts.length - 1][0], partial = lastDoy < 360;

    document.getElementById("tmYearSummary").innerHTML =
      "Hottest day <b>" + peak[1].toFixed(1) + "°</b> on " + fmtDay(peak[0]) +
      "; coldest night <b>" + cold[1].toFixed(1) + "°</b> on " + fmtDay(cold[0]) +
      (partial ? " · <b>year in progress, to " + fmtDay(lastDoy) + "</b>" : "") + ".";

    var stats = document.getElementById("tmYearStats");
    stats.innerHTML = M.map(function (m, k) {
      return "<div class='mini' style='--tint:var(" + m.css + ")'><div class='v'>" + counts[k] +
        "</div><div class='l'>" + m.label.toLowerCase() + " " + m.sub + "</div></div>";
    }).join("") +
      "<div class='mini' style='--tint:var(" + M[M.length-1].css + ")'><div class='v'>" +
      peak[1].toFixed(1) + "°</div><div class='l'>hottest · " + fmtDay(peak[0]) + "</div></div>";

    var svg = el("svg", { viewBox: "0 0 " + EW + " " + EH, class: "chart chart-in",
      role: "img", "aria-label": T.city + " daily maximum and minimum temperature for " + yr });
    for (var v = Math.ceil(YMIN / 5) * 5; v <= YMAX; v += 5) {
      svg.appendChild(el("line", { class: "g", x1: EM.l, x2: EM.l + epw, y1: ey(v), y2: ey(v) }));
      svg.appendChild(txt(el("text", { class: "axn", x: EM.l - 7, y: ey(v) + 3, "text-anchor": "end" }), v + "°"));
    }
    for (var m2 = 0; m2 < 12; m2++) {
      if (m2 > 0) svg.appendChild(el("line", { class: "g", x1: ex(MSTART[m2]), x2: ex(MSTART[m2]),
        y1: EM.t, y2: EM.t + eph, "stroke-opacity": ".6" }));
      svg.appendChild(txt(el("text", { class: "ax", x: ex((MSTART[m2] + MSTART[m2+1]) / 2),
        y: EH - 9, "text-anchor": "middle" }), MABBR[m2]));
    }

    var top = "M " + ex(pts[0][0]) + " " + ey(pts[0][1]);
    pts.forEach(function (p) { top += " L " + ex(p[0]).toFixed(1) + " " + ey(p[1]).toFixed(1); });
    var bot = "";
    for (var i2 = pts.length - 1; i2 >= 0; i2--) {
      var p2 = pts[i2];
      bot += " L " + ex(p2[0]).toFixed(1) + " " + ey(p2[2] == null ? p2[1] : p2[2]).toFixed(1);
    }
    svg.appendChild(el("path", { d: top + bot + " Z", fill: "var(--ink)", "fill-opacity": ".08" }));

    /* Exceedance stems, each clipped to its own band, so a colour never bleeds
       past the threshold it marks: between the two day thresholds the stem is
       the first colour, and only above the second does it change. */
    var days = M.filter(function (m) { return m.series === "max"; });
    var nights = M.filter(function (m) { return m.series === "min"; });
    function stems(list, pick) {
      pts.forEach(function (p) {
        var val = pick(p);
        if (val == null) return;
        list.forEach(function (m, k) {
          if (val <= m.thr) return;
          var to = (k + 1 < list.length) ? Math.min(val, list[k+1].thr) : val;
          svg.appendChild(el("line", { x1: ex(p[0]), x2: ex(p[0]), y1: ey(to), y2: ey(m.thr),
            stroke: "var(" + m.css + ")", "stroke-width": 2.2, "stroke-opacity": ".55" }));
        });
      });
    }
    stems(days, function (p) { return p[1]; });
    stems(nights, function (p) { return p[2]; });

    var lowD = "", pen = false;
    pts.forEach(function (p) {
      if (p[2] == null) { pen = false; return; }
      lowD += (pen ? " L" : " M") + " " + ex(p[0]).toFixed(1) + " " + ey(p[2]).toFixed(1);
      pen = true;
    });
    if (lowD) svg.appendChild(el("path", { d: lowD.trim(), fill: "none",
      stroke: "var(" + nights[0].css + ")", "stroke-width": 1.8, "stroke-linejoin": "round" }));
    svg.appendChild(el("path", { d: top, fill: "none", stroke: "var(" + days[0].css + ")",
      "stroke-width": 1.8, "stroke-linejoin": "round" }));

    M.forEach(function (m) {
      svg.appendChild(el("line", { class: "thr-line", x1: EM.l, x2: EM.l + epw,
        y1: ey(m.thr), y2: ey(m.thr), stroke: "var(" + m.css + ")" }));
      svg.appendChild(txt(el("text", { class: "thr-lab", x: EM.l + 4, y: ey(m.thr) - 4,
        fill: "var(" + m.css + ")" }), m.thr + "°" + (m.series === "min" ? " night" : "")));
    });

    if (partial) {
      svg.appendChild(el("line", { class: "endmark", x1: ex(lastDoy), x2: ex(lastDoy), y1: EM.t, y2: EM.t + eph }));
      svg.appendChild(txt(el("text", { class: "end-lab", x: ex(lastDoy) + 5, y: EM.t + 12 }), "to " + fmtDay(lastDoy)));
    }

    var hair = el("line", { class: "hair", y1: EM.t, y2: EM.t + eph }); svg.appendChild(hair);
    var dotH = el("circle", { r: 4, fill: "var(" + days[0].css + ")", opacity: 0 }); svg.appendChild(dotH);
    var dotL = el("circle", { r: 3.5, fill: "var(" + nights[0].css + ")", opacity: 0 }); svg.appendChild(dotL);
    var over = el("rect", { x: EM.l, y: EM.t, width: epw, height: eph, fill: "transparent",
      style: "cursor:crosshair" }); svg.appendChild(over);
    over.addEventListener("mousemove", function (ev) {
      var r = svg.getBoundingClientRect();
      var dn = Math.round(((ev.clientX - r.left) / r.width * EW - EM.l) / epw * 364 + 1);
      if (curMax[dn] == null) {
        var best = null, bd = 999;
        for (var k in curMax) { var d2 = Math.abs(+k - dn); if (d2 < bd) { bd = d2; best = +k; } }
        if (best == null) return;
        dn = best;
      }
      var hi2 = curMax[dn], lo2 = curMin[dn];
      hair.setAttribute("x1", ex(dn)); hair.setAttribute("x2", ex(dn)); hair.style.opacity = .5;
      dotH.setAttribute("cx", ex(dn)); dotH.setAttribute("cy", ey(hi2)); dotH.style.opacity = 1;
      if (lo2 != null) { dotL.setAttribute("cx", ex(dn)); dotL.setAttribute("cy", ey(lo2)); dotL.style.opacity = 1; }
      else dotL.style.opacity = 0;
      var tags = M.filter(function (m) {
        var v2 = m.series === "max" ? hi2 : lo2;
        return v2 != null && v2 >= m.thr;
      }).map(function (m) { return m.sub; });
      showTip(ev, "<b>" + fmtDay(dn) + " " + yr + "</b>" +
        (tags.length ? " <span class='k'>" + tags.join(" · ") + "</span>" : "") +
        "<br>high <b>" + hi2.toFixed(1) + "°</b>" +
        (lo2 != null ? " · low <b>" + lo2.toFixed(1) + "°</b>" : ""));
    });
    over.addEventListener("mouseleave", function () {
      hideTip(); hair.style.opacity = 0; dotH.style.opacity = 0; dotL.style.opacity = 0;
    });

    var host = document.getElementById("tmYearChart");
    host.innerHTML = ""; host.appendChild(svg);
    document.getElementById("tmPrev").disabled = EYEARS.indexOf(yr) === 0;
    document.getElementById("tmNext").disabled = EYEARS.indexOf(yr) === EYEARS.length - 1;
  }

  var EYEARS = Object.keys(ALL).sort();

  /* ── wiring ───────────────────────────────────────────────────────────── */
  function renderRecord() { renderTiles(); renderCharts(); }
  function renderRankings() { renderStreaks(); renderMonths(); renderTable(); }

  document.getElementById("tmYtd").textContent = HIST.ytd;
  document.getElementById("tmSource").innerHTML = T.source;
  document.getElementById("tmYearLegend").innerHTML =
    M.map(function (m) {
      return "<span><i style='background:var(" + m.css + ")'></i>" + m.label + " " + m.sub + "</span>";
    }).join("") +
    "<span><i class='hatched' style='background:var(--ink-faint)'></i>part-year, counted only to " + HIST.ytd + "</span>";

  // Chrome behaviour is shared with the Beijing air page; see design.CHROME_JS.
  function showView(v, fromUrl) {
    var known = ["record", "rankings", "explorer"];
    if (known.indexOf(v) < 0) v = "record";
    [].forEach.call(document.querySelectorAll(".tm-views > section"), function (s) {
      s.hidden = s.dataset.view !== v;
    });
    // The counting window is the only thing in the overflow, and it means
    // nothing to the explorer, which draws whole years by construction.
    document.getElementById("tmMore").hidden = v === "explorer";
    var vs = document.getElementById("tmViewSel");
    if (vs && vs.value !== v) vs.value = v;
    if (!fromUrl) WX.setParam("view", v, "record");
    if (v === "rankings") renderRankings();
    if (v === "explorer") renderYear(sel.value);
    window.dispatchEvent(new Event("resize"));   // segmented thumbs re-measure
  }
  WX.picker("tmViewSel", function (v) { showView(v); });
  WX.overflow("tmMore", "tmMoreBtn", "tmMoreMenu");

  segment("tmWindow", function (d) {
    WIN = d.win;
    WX.setParam("win", d.win, "full");
    renderRecord();
    if (!document.querySelector("[data-view=rankings]").hidden) renderRankings();
  });
  segment("tmMonthMode", function (d) { MMODE = d.mm; renderMonths(); });

  [].forEach.call(document.querySelectorAll(".mcar button"), function (b) {
    b.addEventListener("click", function () {
      var next = MOFF + (+b.dataset.step) * 4;
      var anchor = (MON.ay - MON.years[0]) * 12 + (MON.am - 1);
      if (anchor + next - 3 < 0) return;
      if (next > 0) return;                       // never past the last finished month
      MOFF = next;
      renderMonths();
    });
  });

  var sel = document.getElementById("tmYear");
  EYEARS.slice().reverse().forEach(function (y) {
    var o = document.createElement("option"); o.value = y; o.textContent = y; sel.appendChild(o);
  });
  sel.value = EYEARS.indexOf(String(PARTIAL)) >= 0 ? String(PARTIAL) : EYEARS[EYEARS.length - 1];
  sel.addEventListener("change", function () {
    WX.setParam("year", sel.value, ""); renderYear(sel.value);
  });
  document.getElementById("tmPrev").addEventListener("click", function () {
    var i = EYEARS.indexOf(sel.value); if (i > 0) { sel.value = EYEARS[i-1]; renderYear(sel.value); }
  });
  document.getElementById("tmNext").addEventListener("click", function () {
    var i = EYEARS.indexOf(sel.value);
    if (i < EYEARS.length - 1) { sel.value = EYEARS[i+1]; renderYear(sel.value); }
  });

  // State from the URL before the first paint, so a linked-to view renders once
  // rather than showing the default and correcting itself.
  var wantYear = WX.param("year", "");
  if (EYEARS.indexOf(wantYear) >= 0) sel.value = wantYear;
  if (WX.param("win", "full") === "ytd") {
    var ytdBtn = document.querySelector('#tmWindow button[data-win="ytd"]');
    if (ytdBtn) ytdBtn.click();     // drive the control so its thumb follows
  }
  renderRecord();
  showView(WX.param("view", "record"), true);
})();
