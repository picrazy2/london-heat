/* ── The air-quality module ────────────────────────────────────────────────
   Every index on this page is derived in the browser from a concentration in
   µg/m³, using breakpoint tables serialised out of the same Python the build
   trusts. Nothing stores an AQI. That is what lets the scale toggle be instant
   and, more importantly, honest: switching scales re-judges the same air rather
   than showing a different measurement. */
(function () {
  "use strict";
  var A = window.AIR;
  if (!A) return;

  var NS = "http://www.w3.org/2000/svg";
  var MABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var SCALE = "us";
  var tip = document.getElementById("tip");

  function el(n, a) {
    var e = document.createElementNS(NS, n);
    for (var k in a) if (a[k] != null) e.setAttribute(k, a[k]);
    return e;
  }
  function txt(e, s) { e.textContent = s; return e; }
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function showTip(ev, html) { tip.innerHTML = html; tip.style.opacity = 1; moveTip(ev); }
  function moveTip(ev) { tip.style.left = ev.clientX + "px"; tip.style.top = (ev.clientY - 12) + "px"; }
  function hideTip() { tip.style.opacity = 0; }

  /* ── the index, from the concentration ────────────────────────────────── */
  function aqi(conc, scale) {
    if (conc == null || isNaN(conc)) return null;
    var S = A.scales[scale || SCALE];
    var c = S.trunc ? Math.floor(conc * 10) / 10 : Math.round(conc);
    var bp = S.bp, top = bp[bp.length - 1];
    if (c >= top[1]) return { i: top[3], cat: top[4] };
    for (var k = 0; k < bp.length; k++) {
      var lo = bp[k][0], hi = bp[k][1], ilo = bp[k][2], ihi = bp[k][3];
      if (c <= hi) {
        var span = hi - lo;
        var frac = span <= 0 ? 0 : (c - lo) / span;
        return { i: Math.round(ilo + frac * (ihi - ilo)), cat: bp[k][4] };
      }
    }
    return { i: top[3], cat: top[4] };
  }
  function catOf(conc, scale) { var r = aqi(conc, scale); return r == null ? null : r.cat; }
  function catName(ci, scale) { return A.scales[scale || SCALE].cats[ci].name; }
  function catColor(ci) { return cssVar(A.scales.us.cats[ci].css); }
  function catToken(ci) { return "var(" + A.scales.us.cats[ci].css + ")"; }
  function catInk(ci) { return "var(" + A.scales.us.cats[ci].css + "-ink)"; }
  function catHatch(ci) { return "var(" + A.scales.us.cats[ci].css + "-hatch)"; }

  /* ── the two-scale ruler ──────────────────────────────────────────────
     Both scales are drawn against the same concentration axis, so the eye reads
     the disagreement directly: at 35 µg/m³ the US lane has already crossed into
     its second band while China's is still in its first. */
  var RULER_MAX = 250;                     // above this both scales agree it is bad
  function ruler(conc) {
    var host = document.getElementById("aqRuler");
    var pct = conc == null ? null : Math.min(100, conc / RULER_MAX * 100);
    var html = "";
    ["us", "cn"].forEach(function (s) {
      var S = A.scales[s];
      var lanes = "";
      var prev = 0;
      S.bp.forEach(function (b) {
        var hi = Math.min(b[1], RULER_MAX);
        if (hi <= prev) return;
        var w = (hi - prev) / RULER_MAX * 100;
        var label = S.cats[b[4]].name;
        // Only the wide bands can carry a word; the narrow ones stay clean.
        lanes += '<div class="b" style="width:' + w.toFixed(2) + '%;background:' +
          catToken(b[4]) + '">' + (w > 11 ? "<span>" + (s === "cn" && S.cats[b[4]].zh ?
          S.cats[b[4]].zh : label) + "</span>" : "") + "</div>";
        prev = hi;
      });
      var mark = pct == null ? "" : '<div class="needle" style="left:calc(' + pct.toFixed(2) + '% - 1.5px)"></div>';
      var r = conc == null ? null : aqi(conc, s);
      html += '<div><div class="lane-lab"><span>' + S.name + '</span><em>' +
        (r ? "AQI " + r.i + " · " + S.cats[r.cat].name : "") + '</em></div>' +
        '<div class="lane">' + lanes + mark + "</div></div>";
    });
    html += '<div class="scaleaxis"><span>0</span><span>50</span><span>100</span>' +
      '<span>150</span><span>200</span><span>250+ µg/m³</span></div>';
    host.innerHTML = html;
  }

  /* ── the live hero ────────────────────────────────────────────────────── */
  var LIVE = A.live || null;

  function renderNow() {
    var conc = LIVE && LIVE.city != null ? LIVE.city : null;
    var host = document.getElementById("aqNow");
    var r = aqi(conc);
    var other = SCALE === "us" ? "cn" : "us";
    var ro = aqi(conc, other);

    document.getElementById("aqNum").textContent = r ? r.i : "–";
    document.getElementById("aqScaleName").textContent =
      A.scales[SCALE].name + " AQI";
    var catEl = document.getElementById("aqCat");
    catEl.textContent = r ? catName(r.cat) +
      (SCALE === "cn" && A.scales.cn.cats[r.cat].zh ? " · " + A.scales.cn.cats[r.cat].zh : "")
      : "Live feed unavailable";
    host.style.setProperty("--tint", r ? catToken(r.cat) : "var(--ink-muted)");

    document.getElementById("aqConc").innerHTML = conc == null ? "" :
      "PM2.5 <b>" + conc.toFixed(1) + "</b> µg/m³, averaged over the last 24 hours" +
      (LIVE.hour != null ? " · <b>" + LIVE.hour.toFixed(0) + "</b> µg/m³ this hour" : "");
    document.getElementById("aqStamp").textContent = LIVE && LIVE.time
      ? LIVE.time + " Beijing time · " + (LIVE.n || 0) + " stations"
      : "";

    var o = document.getElementById("aqOther");
    if (ro && r) {
      o.hidden = false;
      o.style.setProperty("--other-tint", catColor(ro.cat));
      // The comparison is between the two scales, not between "this one" and
      // "the other one" — phrasing it relatively inverted the sentence whenever
      // China was the selected scale, and called the ordinary case unusual.
      var us = aqi(conc, "us"), cn = aqi(conc, "cn");
      var note = us.i === cn.i
        ? " The two scales happen to land on the same number at this level."
        : us.i > cn.i
          ? " The US scale is the stricter of the two at almost every level, and this is no exception."
          : " China's scale is reading higher here, which is unusual — the US scale is normally the stricter of the two.";
      o.innerHTML = "The same air is <b>AQI " + ro.i + "</b> on the " +
        A.scales[other].name + " scale — <span class='pill'>" +
        (other === "cn" && A.scales.cn.cats[ro.cat].zh
          ? A.scales.cn.cats[ro.cat].zh + " " + catName(ro.cat, other)
          : catName(ro.cat, other)) + "</span>." + note;
    } else {
      o.hidden = true;
    }
    ruler(conc);
  }

  /* ── the recent hourly trace ──────────────────────────────────────────── */
  function renderRecent() {
    var host = document.getElementById("aqRecent");
    var t = A.recent && A.recent.v || [];
    if (!t.length) { host.innerHTML = "<p class='footnote'>No recent data.</p>"; return; }
    var W = 460, H = 130, m = { t: 10, r: 8, b: 20, l: 30 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var max = Math.max(20, Math.max.apply(null, t.filter(function (v) { return v != null; })) * 1.15);
    var x = function (i) { return m.l + i / Math.max(1, t.length - 1) * pw; };
    var y = function (v) { return m.t + ph - v / max * ph; };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in",
      role: "img", "aria-label": "Beijing city-mean PM2.5 for the last three days" });

    // Category bands behind the trace: the reader sees which verdict the air was
    // in, not just a number going up and down.
    var S = A.scales[SCALE];
    var prev = 0;
    S.bp.forEach(function (b) {
      var hi = Math.min(b[1], max);
      if (hi <= prev) return;
      svg.appendChild(el("rect", { x: m.l, y: y(hi), width: pw, height: Math.max(0, y(prev) - y(hi)),
        fill: catToken(b[4]), "fill-opacity": ".13" }));
      prev = hi;
    });

    var gstep = [5, 10, 20, 25, 50, 100, 200].filter(function (s) { return max / s <= 5; })[0] || 250;
    for (var g = 0; g <= max; g += gstep) {
      svg.appendChild(el("line", { class: "gridline", x1: m.l, x2: m.l + pw, y1: y(g), y2: y(g) }));
      svg.appendChild(txt(el("text", { class: "tick", x: m.l - 5, y: y(g) + 3, "text-anchor": "end" }), g));
    }
    var d = "", pen = false;
    t.forEach(function (v, i) {
      if (v == null) { pen = false; return; }
      d += (pen ? " L" : " M") + " " + x(i).toFixed(1) + " " + y(v).toFixed(1);
      pen = true;
    });
    svg.appendChild(el("path", { d: d.trim(), fill: "none", stroke: "var(--accent)",
      "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

    (A.recent.marks || []).forEach(function (mk) {
      svg.appendChild(txt(el("text", { class: "tick", x: x(mk.i), y: H - 6, "text-anchor": "middle" }), mk.l));
    });

    var over = el("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent",
      style: "cursor:crosshair" });
    over.addEventListener("mousemove", function (ev) {
      var rect = svg.getBoundingClientRect();
      var i = Math.round(((ev.clientX - rect.left) / rect.width * W - m.l) / pw * (t.length - 1));
      i = Math.max(0, Math.min(t.length - 1, i));
      if (t[i] == null) return;
      var rr = aqi(t[i]);
      showTip(ev, "<span class='k'>" + A.recent.t[i] + "</span><br><b>" + t[i].toFixed(1) +
        "</b> µg/m³ · AQI <b>" + rr.i + "</b> " + catName(rr.cat));
    });
    over.addEventListener("mouseleave", hideTip);
    svg.appendChild(over);
    host.innerHTML = ""; host.appendChild(svg);
  }

  /* ── the station list ─────────────────────────────────────────────────── */
  function renderStations() {
    var host = document.getElementById("aqStations");
    var st = (LIVE && LIVE.stations || []).slice()
      .filter(function (s) { return s.pm25_24h != null || s.pm25 != null; });
    if (!st.length) { host.innerHTML = "<div class='row'><span class='footnote'>Station feed unavailable.</span></div>"; return; }
    st.sort(function (a, b) { return (b.pm25_24h != null ? b.pm25_24h : b.pm25) - (a.pm25_24h != null ? a.pm25_24h : a.pm25); });
    host.innerHTML = st.map(function (s) {
      var c = s.pm25_24h != null ? s.pm25_24h : s.pm25;
      var r = aqi(c);
      return "<div class='row'><span class='dotv' style='background:" + catToken(r.cat) + "'>" +
        r.i + "</span><span class='grow'><span class='nm'>" + (s.en || s.name) + "</span>" +
        (s.en && s.name !== s.en ? " <span class='zh'>" + s.name + "</span>" : "") +
        "</span><span class='val tnum'>" + c.toFixed(0) + "<small> µg/m³</small></span></div>";
    }).join("");
  }

  /* ── the map ──────────────────────────────────────────────────────────── */
  var map = null, layer = null, tiles = null, tileStyle = null, waitingForLeaflet = false;

  function isDark() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  function setBasemap() {
    if (!map) return;
    var want = isDark() ? "dark_nolabels" : "light_nolabels";
    if (want === tileStyle) return;
    tileStyle = want;
    if (tiles) map.removeLayer(tiles);
    tiles = L.tileLayer("https://{s}.basemaps.cartocdn.com/" + want + "/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd", maxZoom: 14, minZoom: 6,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(map);
    tiles.bringToBack();
  }

  function renderMap() {
    // Leaflet is loaded with `defer`, so it runs after this module does. The
    // first call can therefore find no L at all; retry once the page has
    // finished loading rather than silently leaving a grey box.
    if (typeof L === "undefined") {
      if (!waitingForLeaflet) {
        waitingForLeaflet = true;
        window.addEventListener("load", function () { renderMap(); }, { once: true });
      }
      return;
    }
    var st = (LIVE && LIVE.stations || []).filter(function (s) { return s.lat && s.lon; });
    document.getElementById("aqMapSub").textContent = st.length + " monitoring stations";
    if (!map) {
      map = L.map("aqMap", { zoomControl: true, scrollWheelZoom: false, attributionControl: true })
        .setView([40.02, 116.45], 8);
      setBasemap();
      // A light basemap under a dark page is the one thing that gives away a
      // map bolted onto a themed site, so the tiles follow the theme — both the
      // explicit toggle, which mutates data-theme, and the system setting.
      new MutationObserver(setBasemap).observe(document.documentElement,
        { attributes: true, attributeFilter: ["data-theme"] });
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(setBasemap);
    }
    if (layer) map.removeLayer(layer);
    layer = L.layerGroup().addTo(map);
    if (!st.length) return;
    st.forEach(function (s) {
      var c = s.pm25_24h != null ? s.pm25_24h : s.pm25;
      if (c == null) return;
      var r = aqi(c);
      // Area, not radius, carries the value — a radius-encoded circle at twice
      // the number looks four times as big, which overstates it.
      var rad = 7 + Math.sqrt(Math.max(0, c)) * 1.5;
      L.circleMarker([s.lat, s.lon], {
        radius: Math.min(30, rad), fillColor: catColor(r.cat), fillOpacity: .72,
        color: cssVar("--surface-1"), weight: 1.5,
      }).bindPopup("<div class='pn'>" + (s.en || s.name) + "</div>" +
        (s.en && s.name !== s.en ? "<div class='zh'>" + s.name + "</div>" : "") +
        "<div class='pv'>PM2.5 <b>" + c.toFixed(0) + "</b> µg/m³ · " +
        A.scales[SCALE].name + " AQI <b>" + r.i + "</b><br>" + catName(r.cat) + "</div>")
        .addTo(layer);
    });
    var b = L.latLngBounds(st.map(function (s) { return [s.lat, s.lon]; }));
    map.fitBounds(b.pad(0.15));
  }

  /* ── the long trend ───────────────────────────────────────────────────── */
  function renderAnnual() {
    var host = document.getElementById("aqAnnual");
    var Y = A.annual;
    var W = 980, H = 260, m = { t: 22, r: 106, b: 28, l: 36 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var max = Math.ceil(Math.max.apply(null, Y.map(function (y) { return y.mean; })) / 20) * 20 + 10;
    var x = function (i) { return m.l + (i + .5) / Y.length * pw; };
    var y = function (v) { return m.t + ph - v / max * ph; };
    var bw = Math.max(8, pw / Y.length - 8);
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in",
      role: "img", "aria-label": "Beijing annual mean PM2.5 by year" });

    for (var g = 0; g <= max; g += 20) {
      svg.appendChild(el("line", { class: "gridline", x1: m.l, x2: m.l + pw, y1: y(g), y2: y(g) }));
      svg.appendChild(txt(el("text", { class: "tick", x: m.l - 6, y: y(g) + 3, "text-anchor": "end" }), g));
    }
    Y.forEach(function (yr, i) {
      var r = aqi(yr.mean);
      var partial = yr.partial;
      var rect = el("rect", { class: "bar", x: x(i) - bw / 2, y: y(yr.mean), width: bw,
        height: y(0) - y(yr.mean), rx: 4, fill: catToken(r.cat),
        "fill-opacity": partial ? ".45" : "1" });
      if (partial) { rect.setAttribute("stroke", catToken(r.cat)); rect.setAttribute("stroke-width", "1.5"); }
      rect.addEventListener("mouseenter", function (ev) {
        var us = aqi(yr.mean, "us"), cn = aqi(yr.mean, "cn");
        showTip(ev, "<span class='k'>" + yr.y + (partial ? " · year in progress" : "") +
          "</span><br><b>" + yr.mean.toFixed(1) + "</b> µg/m³ annual mean<br>" +
          "<span style='opacity:.75'>US AQI " + us.i + " · China AQI " + cn.i + "</span>");
      });
      rect.addEventListener("mousemove", moveTip);
      rect.addEventListener("mouseleave", hideTip);
      svg.appendChild(rect);
      svg.appendChild(txt(el("text", { class: "tick", x: x(i), y: H - 8, "text-anchor": "middle" }),
        String(yr.y).slice(2)));
      svg.appendChild(txt(el("text", { class: "mark-lab", x: x(i), y: y(yr.mean) - 5,
        "text-anchor": "middle" }), yr.mean.toFixed(0)));
    });

    /* The reference lines are the argument of this chart. China's own annual
       standard and the WHO guideline are 7x apart, and Beijing now sits between
       them — past the target it set itself, nowhere near the one health
       research points at. */
    [{ v: A.scales.cnAnnual, l: "China's own|annual standard, 35", c: "var(--ink-muted)" },
     { v: A.scales.who.annual, l: "WHO guideline, 5", c: "var(--positive)" }].forEach(function (ref) {
      if (ref.v > max) return;
      svg.appendChild(el("line", { class: "ref", x1: m.l, x2: m.l + pw + 6, y1: y(ref.v), y2: y(ref.v),
        stroke: ref.c }));
      ref.l.split("|").forEach(function (line, k) {
        svg.appendChild(txt(el("text", { class: "ref-lab", x: m.l + pw + 10,
          y: y(ref.v) + 3 + k * 11, fill: ref.c }), line));
      });
    });
    host.innerHTML = ""; host.appendChild(svg);

    var first = Y[0], last = Y[Y.length - 1];
    var complete = Y.filter(function (y) { return !y.partial; });
    var lastFull = complete[complete.length - 1];
    document.getElementById("aqAnnualCap").innerHTML =
      "From <b>" + first.mean.toFixed(0) + " µg/m³ in " + first.y + "</b> to <b>" +
      lastFull.mean.toFixed(0) + " in " + lastFull.y + "</b> — a fall of " +
      Math.round((1 - lastFull.mean / first.mean) * 100) + "% in " + (lastFull.y - first.y) +
      " years. That is now inside China's own 35 µg/m³ annual standard and still <b>" +
      (lastFull.mean / A.scales.who.annual).toFixed(1) + "× the WHO guideline</b>.";
  }

  /* Days per year in each category — the chart the scale toggle changes most.
     On the US scale a year that China calls almost entirely clean is mostly
     yellow, and the reader can watch the verdict move without the air moving. */
  function renderBands() {
    var host = document.getElementById("aqBands");
    var years = A.byYear;
    var W = 940, H = 300, m = { t: 14, r: 20, b: 28, l: 36 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in",
      role: "img", "aria-label": "Days per year in each air quality category" });
    var bw = Math.max(10, pw / years.length - 8);

    var maxDays = Math.max.apply(null, years.map(function (y) { return y.d.length; }));
    var y0 = function (v) { return m.t + ph - v / maxDays * ph; };
    [0, 91, 183, 274, 365].forEach(function (g) {
      if (g > maxDays) return;
      svg.appendChild(el("line", { class: "gridline", x1: m.l, x2: m.l + pw, y1: y0(g), y2: y0(g) }));
      svg.appendChild(txt(el("text", { class: "tick", x: m.l - 6, y: y0(g) + 3, "text-anchor": "end" }), g));
    });

    years.forEach(function (yr, i) {
      var counts = [0, 0, 0, 0, 0, 0];
      yr.d.forEach(function (c) { var k = catOf(c); if (k != null) counts[k]++; });
      var x = m.l + (i + .5) / years.length * pw - bw / 2;
      var acc = 0;
      counts.forEach(function (n, k) {
        if (!n) return;
        var yTop = y0(acc + n), h = y0(acc) - y0(acc + n);
        var rect = el("rect", { x: x, y: yTop, width: bw, height: h, fill: catToken(k),
          class: "bar", rx: 1 });
        rect.addEventListener("mouseenter", function (ev) {
          showTip(ev, "<span class='k'>" + yr.y + "</span><br><b>" + n + "</b> days " +
            catName(k) + "<br><span style='opacity:.7'>" +
            Math.round(n / yr.d.length * 100) + "% of the year</span>");
        });
        rect.addEventListener("mousemove", moveTip);
        rect.addEventListener("mouseleave", hideTip);
        svg.appendChild(rect);
        acc += n;
      });
      svg.appendChild(txt(el("text", { class: "tick", x: x + bw / 2, y: H - 8, "text-anchor": "middle" }),
        String(yr.y).slice(2)));
    });
    host.innerHTML = ""; host.appendChild(svg);

    var S = A.scales[SCALE];
    document.getElementById("aqBandsSub").textContent = S.note;
    document.getElementById("aqBandKey").innerHTML = S.cats.map(function (c, k) {
      return "<span><i style='background:" + catToken(k) + "'></i>" +
        (SCALE === "cn" && c.zh ? c.zh + " " + c.name : c.name) + "</span>";
    }).join("");

    /* Two comparable years, in the scale currently selected. The comparison is
       against the last *complete* year: counting days in a year that is eight
       months old against a year that finished would understate the recent one
       purely because it has fewer days in it. */
    var complete = years.filter(function (yr) { return yr.d.length >= 300; });
    var f = years[0], l = complete[complete.length - 1] || years[years.length - 1];
    function goodPct(yr) {
      var n = yr.d.filter(function (c) { return catOf(c) === 0; }).length;
      return Math.round(n / yr.d.length * 100);
    }
    function badN(yr) {
      return yr.d.filter(function (c) { return catOf(c) >= 3; }).length;
    }
    document.getElementById("aqBandsCap").innerHTML =
      "On the " + S.name + " scale, <b>" + goodPct(f) + "% of " + f.y + "</b> fell in the best " +
      "band against <b>" + goodPct(l) + "% of " + l.y + "</b>. Days at " +
      catName(3).toLowerCase() + " or worse went from <b>" + badN(f) + "</b> to <b>" +
      badN(l) + "</b>. Switch the scale and the same days are re-judged — the air does " +
      "not change, the verdict does.";
  }

  function renderHeat() {
    var host = document.getElementById("aqHeat");
    var Mg = A.monthly;
    // A perceptual ramp keyed to the categories rather than a continuous
    // gradient: the colour a cell takes is the verdict that month's mean earns.
    var P = Mg.part;
    var html = "<div class='heat'><div class='hh'></div>" +
      MABBR.map(function (mn) { return "<div class='hh'>" + mn[0] + "</div>"; }).join("");
    Mg.years.forEach(function (yr, i) {
      html += "<div class='hl'>" + yr + "</div>";
      for (var m = 0; m < 12; m++) {
        var v = Mg.v[i][m];
        if (v == null) { html += "<div class='cell'></div>"; continue; }
        var r = aqi(v);
        // The month still running is hatched rather than faded: the same mark
        // the temperature charts give a part-year, so one reading of the legend
        // carries across both pages. Colour still says which band it is in.
        var part = P && P.y === yr && P.m === m;
        // The number is rounded for the cell and kept whole in the tooltip: a
        // month mean carries its decimal, but at this size the decimal is noise.
        html += "<div class='cell" + (part ? " part" : "") + "' data-v='" + v.toFixed(1) +
          "' data-y='" + yr + "' data-m='" + m + "' style='background-color:" + catToken(r.cat) +
          ";color:" + catInk(r.cat) + (part ? ";--hatch:" + catHatch(r.cat) : "") +
          "'><span>" + Math.round(v) + "</span></div>";
      }
    });
    html += "</div>";
    if (P && P.days) {
      html += "<div class='heatnote'><i class='hatch'></i>" + MABBR[P.m] + " " + P.y +
        " is still running — mean of its first <b>" + P.days +
        (P.days === 1 ? "</b> day, to " : "</b> days, to ") + P.through + ".</div>";
    }
    host.innerHTML = html;
    [].forEach.call(host.querySelectorAll(".cell[data-v]"), function (c) {
      c.addEventListener("mouseenter", function (ev) {
        var v = +c.dataset.v, r = aqi(v);
        showTip(ev, "<span class='k'>" + MABBR[+c.dataset.m] + " " + c.dataset.y +
          (c.classList.contains("part") ? " · part-month" : "") +
          "</span><br><b>" + v.toFixed(1) + "</b> µg/m³ · AQI <b>" + r.i + "</b><br>" +
          "<span style='opacity:.7'>" + catName(r.cat) +
          (c.classList.contains("part") ? " · " + Mg.part.days + " days, to " +
            Mg.part.through : "") + "</span>");
      });
      c.addEventListener("mousemove", moveTip);
      c.addEventListener("mouseleave", hideTip);
    });
  }

  /* ── rhythm ───────────────────────────────────────────────────────────── */
  function profileChart(hostId, values, labels, axisLabel, ariaLabel) {
    var host = document.getElementById(hostId);
    var W = 460, H = 190, m = { t: 14, r: 12, b: 26, l: 32 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var vals = values.filter(function (v) { return v != null; });
    var max = Math.ceil(Math.max.apply(null, vals) / 10) * 10 + 10;
    var x = function (i) { return m.l + (i + .5) / values.length * pw; };
    var y = function (v) { return m.t + ph - v / max * ph; };
    var bw = Math.max(4, pw / values.length - 4);
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in",
      role: "img", "aria-label": ariaLabel });
    for (var g = 0; g <= max; g += max > 80 ? 25 : 10) {
      svg.appendChild(el("line", { class: "gridline", x1: m.l, x2: m.l + pw, y1: y(g), y2: y(g) }));
      svg.appendChild(txt(el("text", { class: "tick", x: m.l - 5, y: y(g) + 3, "text-anchor": "end" }), g));
    }
    values.forEach(function (v, i) {
      if (v == null) return;
      var r = aqi(v);
      var rect = el("rect", { class: "bar", x: x(i) - bw / 2, y: y(v), width: bw,
        height: y(0) - y(v), rx: 3, fill: catToken(r.cat) });
      rect.addEventListener("mouseenter", function (ev) {
        showTip(ev, "<span class='k'>" + labels[i] + "</span><br><b>" + v.toFixed(1) +
          "</b> µg/m³ · AQI <b>" + r.i + "</b>");
      });
      rect.addEventListener("mousemove", moveTip);
      rect.addEventListener("mouseleave", hideTip);
      svg.appendChild(rect);
    });
    labels.forEach(function (l, i) {
      if (values.length > 13 && i % 3 !== 0) return;
      svg.appendChild(txt(el("text", { class: "tick", x: x(i), y: H - 8, "text-anchor": "middle" }), l));
    });
    host.innerHTML = ""; host.appendChild(svg);
  }

  function renderRhythm() {
    var rel = A.diurnal.rel;
    var hours = rel.map(function (_, i) { return i + "h"; });
    divergingChart("aqDiurnal", rel, hours,
      "PM2.5 by hour of day in Beijing, relative to each day's own average");
    var peak = rel.indexOf(Math.max.apply(null, rel));
    var trough = rel.indexOf(Math.min.apply(null, rel));
    document.getElementById("aqDiurnalCap").innerHTML =
      "Each hour against its own day's average, so the shape of a day shows through " +
      "instead of being buried by the difference between days. Dirtiest around <b>" +
      peak + ":00</b> (" + sign(rel[peak]) + "%), cleanest around <b>" + trough +
      ":00</b> (" + sign(rel[trough]) + "%). The whole daily swing is about <b>" +
      (Math.max.apply(null, rel) - Math.min.apply(null, rel)).toFixed(0) +
      " percentage points</b> — far less than the swing between seasons, which is why " +
      "a bad day in Beijing is usually a bad week.";

    profileChart("aqSeason", A.season, MABBR, "month", "Mean PM2.5 by month in Beijing");
    var worst = A.season.indexOf(Math.max.apply(null, A.season));
    var best = A.season.indexOf(Math.min.apply(null, A.season));
    document.getElementById("aqSeasonCap").innerHTML =
      "<b>" + MABBR[worst] + "</b> is the worst month and <b>" + MABBR[best] +
      "</b> the cleanest, a range of <b>" + (Math.max.apply(null, A.season) -
      Math.min.apply(null, A.season)).toFixed(0) + " µg/m³</b>. Winter heating and still, " +
      "cold air do most of that.";

    renderHist();
  }

  function sign(v) { return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(0); }

  /* Bars either side of a zero rule, coloured by direction rather than by
     magnitude — the bar's own length already says how big it is. */
  function divergingChart(hostId, values, labels, ariaLabel) {
    var host = document.getElementById(hostId);
    var W = 460, H = 190, m = { t: 16, r: 12, b: 26, l: 34 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var span = Math.max.apply(null, values.map(Math.abs)) * 1.2 || 1;
    var x = function (i) { return m.l + (i + .5) / values.length * pw; };
    var y = function (v) { return m.t + ph / 2 - v / span * (ph / 2); };
    var bw = Math.max(4, pw / values.length - 4);
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in",
      role: "img", "aria-label": ariaLabel });
    var stepG = span > 20 ? 20 : (span > 8 ? 10 : 5);
    for (var g = -Math.floor(span / stepG) * stepG; g <= span; g += stepG) {
      svg.appendChild(el("line", { class: g === 0 ? "axisline" : "gridline",
        x1: m.l, x2: m.l + pw, y1: y(g), y2: y(g) }));
      svg.appendChild(txt(el("text", { class: "tick", x: m.l - 5, y: y(g) + 3,
        "text-anchor": "end" }), (g > 0 ? "+" : "") + g + "%"));
    }
    values.forEach(function (v, i) {
      if (v == null) return;
      var up = v >= 0;
      var rect = el("rect", { class: "bar", x: x(i) - bw / 2,
        y: up ? y(v) : y(0), width: bw, height: Math.abs(y(v) - y(0)), rx: 2,
        fill: up ? "var(--aqi-4)" : "var(--aqi-1)" });
      rect.addEventListener("mouseenter", function (ev) {
        showTip(ev, "<span class=\'k\'>" + labels[i] + "</span><br><b>" + sign(v) +
          "%</b> against the day\'s own average");
      });
      rect.addEventListener("mousemove", moveTip);
      rect.addEventListener("mouseleave", hideTip);
      svg.appendChild(rect);
    });
    labels.forEach(function (l, i) {
      if (values.length > 13 && i % 3 !== 0) return;
      svg.appendChild(txt(el("text", { class: "tick", x: x(i), y: H - 8,
        "text-anchor": "middle" }), l));
    });
    host.innerHTML = ""; host.appendChild(svg);
  }

  function renderHist() {
    var host = document.getElementById("aqHist");
    var all = A.allDaily;
    var W = 900, H = 220, m = { t: 14, r: 14, b: 30, l: 38 };
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var BIN = 10, NB = 26;                       // 0-250+, in 10 µg/m³ bins
    var bins = new Array(NB).fill(0);
    all.forEach(function (v) { bins[Math.min(NB - 1, Math.floor(v / BIN))]++; });
    var max = Math.max.apply(null, bins);
    var x = function (i) { return m.l + i / NB * pw; };
    var y = function (v) { return m.t + ph - v / max * ph; };
    var bw = pw / NB - 2;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "chart chart-in",
      role: "img", "aria-label": "Distribution of daily mean PM2.5 in Beijing" });
    bins.forEach(function (n, i) {
      var mid = i * BIN + BIN / 2;
      var r = aqi(mid);
      var rect = el("rect", { class: "bar", x: x(i) + 1, y: y(n), width: bw,
        height: y(0) - y(n), rx: 2, fill: catToken(r.cat) });
      rect.addEventListener("mouseenter", function (ev) {
        showTip(ev, "<span class='k'>" + (i * BIN) + "–" + ((i + 1) * BIN) +
          (i === NB - 1 ? "+" : "") + " µg/m³</span><br><b>" + n + "</b> days · " +
          (n / all.length * 100).toFixed(1) + "% of the record<br>" +
          "<span style='opacity:.7'>" + catName(r.cat) + "</span>");
      });
      rect.addEventListener("mousemove", moveTip);
      rect.addEventListener("mouseleave", hideTip);
      svg.appendChild(rect);
      if (i % 3 === 0) svg.appendChild(txt(el("text", { class: "tick", x: x(i) + bw / 2,
        y: H - 9, "text-anchor": "middle" }), i * BIN));
    });
    // The WHO daily guideline, drawn where it actually falls: in the second bin.
    var wx = m.l + A.scales.who.daily / (NB * BIN) * pw;
    svg.appendChild(el("line", { x1: wx, x2: wx, y1: m.t, y2: m.t + ph,
      stroke: "var(--positive)", "stroke-width": 1.5, "stroke-dasharray": "4 3" }));
    svg.appendChild(txt(el("text", { class: "ref-lab", x: wx + 5, y: m.t + 11,
      fill: "var(--positive)" }), "WHO 24-hour guideline, 15"));
    host.innerHTML = ""; host.appendChild(svg);

    var under = all.filter(function (v) { return v <= A.scales.who.daily; }).length;
    var S = A.scales[SCALE];
    var best = all.filter(function (v) { return catOf(v) === 0; }).length;
    document.getElementById("aqHistCap").innerHTML =
      "Across " + all.length.toLocaleString() + " days, <b>" +
      Math.round(under / all.length * 100) + "%</b> met the WHO 24-hour guideline of 15 µg/m³. " +
      "On the " + S.name + " scale <b>" + Math.round(best / all.length * 100) +
      "%</b> of days fell in the best band. The long tail to the right is what a " +
      "Beijing winter used to look like as a matter of routine.";
  }

  /* ── segmented controls ───────────────────────────────────────────────── */
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
        place(); onChange(b.dataset);
      });
    });
    place();
    window.addEventListener("resize", place);
    return place;
  }

  var VIEW = "now";
  function renderView() {
    if (VIEW === "now") { renderNow(); renderRecent(); renderStations(); renderMap(); }
    if (VIEW === "trend") { renderAnnual(); renderBands(); renderHeat(); }
    if (VIEW === "rhythm") renderRhythm();
  }

  segment("aqViews", function (d) {
    VIEW = d.view;
    [].forEach.call(document.querySelectorAll("#aq > section"), function (s) {
      s.hidden = s.dataset.view !== d.view;
    });
    renderView();
    // Leaflet measures its container on creation; a map built while hidden has
    // zero size and renders as a grey box until told to look again.
    if (VIEW === "now" && map) setTimeout(function () { map.invalidateSize(); }, 30);
  });
  segment("aqScale", function (d) { SCALE = d.scale; renderView(); });

  document.getElementById("aqSource").innerHTML = A.source;
  document.getElementById("aqMapNote").innerHTML = A.mapNote;

  renderView();

  /* ── the live refresh ──────────────────────────────────────────────────
     The build bakes in a snapshot so the page is never empty, then asks the
     edge function for the current hour. A failure here is silent on purpose:
     the baked snapshot is still a real reading, just an older one. */
  // Station coordinates and English names from the build-time snapshot, keyed by
  // the Chinese name. The endpoint's fallback path reads an hourly mirror that
  // carries readings but no positions, so the map is joined back together here
  // rather than losing itself whenever the primary feed is unreachable.
  var BOOK = (A.live && A.live.stations || []).filter(function (s) { return s.name; });

  /* The two feeds name the same station differently: the monitoring centre
     publishes 东四, the mirror publishes 东城东四 with the district in front. So
     the join is on the longest name that is a suffix of the other, not on
     equality, which would have matched almost nothing. */
  function lookup(name) {
    if (!name) return null;
    var best = null;
    for (var i = 0; i < BOOK.length; i++) {
      var b = BOOK[i].name;
      var hit = b === name ||
        (name.length > b.length && name.slice(-b.length) === b) ||
        (b.length > name.length && b.slice(-name.length) === name);
      if (hit && (!best || best.name.length < b.length)) best = BOOK[i];
    }
    return best;
  }

  function refreshLive() {
    fetch("/api/live", { headers: { accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.beijing || j.beijing.city == null) return;
        var b = j.beijing;
        b.stations = (b.stations || []).map(function (s) {
          var known = lookup(s.name);
          if (!known) return s;
          return {
            code: s.code || known.code, name: s.name, en: s.en || known.en,
            lat: s.lat != null ? s.lat : known.lat,
            lon: s.lon != null ? s.lon : known.lon,
            pm25: s.pm25, pm25_24h: s.pm25_24h,
            pm10: s.pm10, o3: s.o3, no2: s.no2, so2: s.so2, co: s.co,
          };
        });
        LIVE = b;
        if (VIEW === "now") { renderNow(); renderStations(); renderMap(); }
      })
      .catch(function () {});
  }
  refreshLive();
  setInterval(refreshLive, 10 * 60 * 1000);
})();
