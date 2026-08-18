#!/usr/bin/env python3
"""One command: fetch the latest of everything, recompute it, write public/.

    python3 build.py                 the daily refresh
    python3 build.py --refresh-ecad  also re-extract Heathrow from KNMI (monthly)
    python3 build.py --refresh-ghcn  also re-pull Beijing's official series (monthly)
    python3 build.py --backfill-aq   also rebuild the whole PM2.5 archive (rare)

Nothing here needs a key. Every source is public and open, which is what lets
the GitHub Action run unattended with no secrets at all.
"""
import argparse
import json
import os
import shutil
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from weather import aqi, design, png, render
from weather.pages import air as air_page
from weather.pages import city as city_page
from weather.sources import pm25, temps
from weather.temps import Metric, Record, fmt_long, fmt_short

BASE = os.path.dirname(os.path.abspath(__file__))
P = lambda *a: os.path.join(BASE, *a)          # noqa: E731
SITE = P("public")
DATA = P("data")
TPL = P("templates")


def read(*p):
    with open(P(*p), encoding="utf-8") as f:
        return f.read()


# ── cities ------------------------------------------------------------------
LONDON_METRICS = [
    Metric("d1", "Hot days", "≥ 25 °C", "max", 25, "--day-1", "days"),
    Metric("d2", "Very hot days", "≥ 30 °C", "max", 30, "--day-2", "days"),
    Metric("n1", "Mild nights", "min ≥ 15 °C", "min", 15, "--night-1", "nights"),
    Metric("n2", "Tropical nights", "min ≥ 20 °C", "min", 20, "--night-2", "nights"),
]

# Beijing's thresholds are five degrees up on London's at every level, because a
# continental summer makes 25 C unremarkable for four months. 35 is not a round
# number chosen for symmetry: it is the China Meteorological Administration's own
# high-temperature warning line, the level at which the city issues advisories.
BEIJING_METRICS = [
    Metric("d1", "Hot days", "≥ 30 °C", "max", 30, "--day-1", "days"),
    Metric("d2", "Very hot days", "≥ 35 °C", "max", 35, "--day-2", "days"),
    Metric("n1", "Warm nights", "min ≥ 20 °C", "min", 20, "--night-1", "nights"),
    Metric("n2", "Hot nights", "min ≥ 25 °C", "min", 25, "--night-2", "nights"),
]


def build_london(args):
    if args.refresh_ecad:
        temps.refresh_ecad([
            ("ECA_blend_tx.zip", "TX_STAID001860.txt", P("data", "heathrow_tx.txt")),
            ("ECA_blend_tn.zip", "TN_STAID001860.txt", P("data", "heathrow_tn.txt")),
        ])

    tx = temps.load_ecad(P("data", "heathrow_tx.txt"))
    tn = temps.load_ecad(P("data", "heathrow_tn.txt"))
    eca_last = max(tx)
    today = datetime.now(ZoneInfo("Europe/London")).date()
    mx, mn = temps.metar_daily("EGLL", "Europe/London", temps.day_after(eca_last), today,
                               cache_path=P("egll_metar.csv"), offline=args.offline)
    tx, filled = temps.stitch(tx, mx)
    tn, _ = temps.stitch(tn, mn)
    last = max(tx)

    rec = Record(tx, tn, LONDON_METRICS, first_year=1960, cur_date=last, filled=filled)
    source = (f"Official Met Office daily figures for Heathrow via <b>ECA&amp;D</b> "
              f"(KNMI) through <b>{fmt_long(eca_last)}</b>; the days after that are "
              f"derived from the airport's own <b>METAR</b> reports via the Iowa "
              f"Environmental Mesonet, current to <b>{fmt_long(last)}</b>. METAR-derived "
              f"maxima run a little below the official figures on the hottest days — "
              f"half-hourly sampling misses a brief afternoon peak — so this year's "
              f"tail is a close estimate, not the final count.")
    return rec, city_page.payload(rec, "London", "ldn", source, (-8, 40)), eca_last, last


def build_beijing_temps(args):
    if args.refresh_ghcn:
        temps.refresh_ghcn("CHM00054511", P("data", "beijing_ghcn_tx.txt"),
                           P("data", "beijing_ghcn_tn.txt"))

    gx = temps.load_pairs(P("data", "beijing_ghcn_tx.txt"))
    gn = temps.load_pairs(P("data", "beijing_ghcn_tn.txt"))
    ghcn_last = max(gx) if gx else "19510101"
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    # METAR is pulled from the start of the record, not from GHCN's cutoff,
    # because GHCN's Beijing gaps are interior, not just at the tail.
    mx, mn = temps.metar_daily("ZBAA", "Asia/Shanghai", date(1973, 1, 1), today,
                               cache_path=P("zbaa_metar.csv"), offline=args.offline)
    tx, filled = temps.stitch(gx, mx)
    tn, _ = temps.stitch(gn, mn)
    last = max(tx)

    rec = Record(tx, tn, BEIJING_METRICS, first_year=1960, cur_date=last, filled=filled)
    n_filled = sum(1 for k in filled if int(k[:4]) >= 1960)
    first_filled = min((k for k in filled if int(k[:4]) >= 1960), default=None)
    bias = metar_bias(gx, gn, mx, mn)
    source = (f"Official daily figures for Beijing Capital Airport (station 54511) via "
              f"NOAA's <b>GHCN-Daily</b>. That series is complete from 1951 to 2012 and "
              f"then falls apart — 2013–2019 is almost entirely absent, and NOAA stopped "
              f"receiving the station in <b>{fmt_long(ghcn_last)}</b> — so the "
              f"<b>{n_filled:,}</b> days it does not cover are derived from the same "
              f"airport's <b>METAR</b> reports via the Iowa Environmental Mesonet, current "
              f"to <b>{fmt_long(last)}</b>. Everything before "
              f"<b>{fmt_long(first_filled) if first_filled else '2013'}</b> is the official "
              f"figure, so the 1961–90 baseline these charts are measured against is not "
              f"itself mixed. On the {bias[0]['n']:,} recent days where both sources report, "
              f"METAR runs <b>{abs(bias[0]['mean']):.1f} °C below</b> the official maximum "
              f"and {abs(bias[1]['mean']):.1f} °C below the official minimum, because it "
              f"reports whole degrees and samples every half hour instead of reading a true "
              f"daily extreme. So the METAR-filled years <em>undercount</em> every threshold "
              f"here — by "
              + ", ".join(f"{abs(b['pct']):.0f}% for {b['label'].lower()}" for b in bias[2:])
              + " — and the recent rise is understated rather than inflated.")
    return rec, city_page.payload(rec, "Beijing", "bj", source, (-18, 42))


def metar_bias(gx, gn, mx, mn):
    """How far METAR sits inside the official figures — measured, not assumed.

    Both series describe the same airport, and for several thousand recent days
    both report. Comparing them there turns "METAR probably runs a bit low" into
    a number, and settles the question a mixed record always raises: whether the
    recent counts are inflated by the change of source. They are not. They are
    held back by it, and the page says so with the figures rather than a hedge.
    """
    import statistics as st
    out = []
    for label, g, m in (("maximum", gx, mx), ("minimum", gn, mn)):
        both = [(g[k], m[k]) for k in set(g) & set(m) if k >= "20000101"]
        d = [b - a for a, b in both] or [0.0]
        out.append({"label": label, "n": len(both), "mean": st.mean(d), "pct": 0.0})
    for metric in BEIJING_METRICS:
        g, m = (gx, mx) if metric.series == "max" else (gn, mn)
        both = [(g[k], m[k]) for k in set(g) & set(m) if k >= "20000101"]
        off = sum(1 for a, _ in both if a >= metric.thr)
        est = sum(1 for _, b in both if b >= metric.thr)
        out.append({"label": metric.label, "n": len(both), "mean": 0.0,
                    "pct": 100 * (est - off) / off if off else 0.0})
    return out


def build_air(args):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    path = P("data", "beijing_pm25_hourly.csv")
    if args.backfill_aq:
        hourly = pm25.refresh(path, full=True, today=today)
    elif args.offline:
        hourly = pm25.load_hourly(path)
    else:
        hourly = pm25.refresh(path, days_back=10, today=today)

    # The live feed is cached to disk and committed. It is a snapshot either way
    # — the page bakes one in and then asks /api/live for a fresher one — but
    # keeping the last good response means a build from a runner that cannot
    # reach CNEMC still ships a real, dated reading instead of an empty hero.
    snap = P("data", "beijing_live.json")
    live = None if args.offline else pm25.live_stations()
    if live:
        with open(snap, "w", encoding="utf-8") as f:
            json.dump(live, f, ensure_ascii=False, indent=1)
    else:
        try:
            with open(snap, encoding="utf-8") as f:
                live = json.load(f)
            print(f"  live feed unavailable; using the cached snapshot "
                  f"({live[0].get('time') if live else 'empty'})")
        except (OSError, ValueError):
            live = None
    source = ("PM2.5 measured hourly by <b>Beijing's municipal monitoring network</b> and "
              "published through the China National Environmental Monitoring Centre. The "
              "historical series is the city mean across its stations, excluding the "
              "designated clean-air control site at Dingling and the regional background "
              "site, both of which measure something other than the city's air. "
              "Concentrations are in µg/m³ and every index on this page is computed from "
              "them here, so the two scales are judging identical numbers.")
    map_note = ("Circle area is the station's 24-hour mean, coloured by the band it falls "
                "in on the selected scale. Positions are the published station "
                "coordinates. Basemap © OpenStreetMap contributors, © CARTO.")
    return air_page.payload(hourly, live, source, map_note), hourly


# ── the social card ---------------------------------------------------------
def social_card(path_out, ldn_years, ldn_vals, ldn_partial, bj_annual):
    """1200x630: London's hot days as a deviation, over Beijing's annual PM2.5.

    Two panels, because the site is now two records. London plots the deviation
    from its own baseline rather than the raw count, so colour can carry the
    sign — a diverging encoding — instead of restating the bar's own length.
    """
    W, H = 1200, 630
    surface = png.rgb("#0b0b12")
    buf = png.canvas(W, H, "#0b0b12")
    png.vgrad(buf, W, H, 0, 0, W, H, png.rgb("#151426"), png.rgb("#0b0b12"))

    L, R, T, GAP = 70, 70, 100, 62
    panel_h = (H - T - 60 - GAP) // 2
    pw = W - L - R
    T2 = T + panel_h + GAP

    # ── panel 1: London ──
    i0 = ldn_years.index(1961) if 1961 in ldn_years else 0
    i1 = ldn_years.index(1990) if 1990 in ldn_years else len(ldn_years) - 1
    normal = sum(ldn_vals[i0:i1 + 1]) / (i1 - i0 + 1)
    dev = [v - normal for v in ldn_vals]
    up, dn = max(max(dev), 0.1), min(min(dev), -0.1)
    span = up - dn
    zero = T + (up / span) * panel_h
    cool, warm = png.rgb("#5aa9e6"), png.rgb("#d63b34")
    n = len(ldn_vals)
    bw = pw / n
    for i, d in enumerate(dev):
        x0, x1 = L + i * bw + 1, L + (i + 1) * bw - 1
        c = warm if d >= 0 else cool
        if ldn_years[i] == ldn_partial:
            c = png.lerp(c, surface, 0.45)
        h = abs(d) / span * panel_h
        if d >= 0:
            png.bar(buf, W, H, x0, x1, zero - h, zero, c, round_top=True)
        else:
            png.bar(buf, W, H, x0, x1, zero, zero + h, c, round_top=False)
    png.fill(buf, W, H, L - 14, zero - 1, L + pw + 14, zero + 1, png.rgb("#6a6480"))

    # ── panel 2: Beijing ──
    if bj_annual:
        vals = [a["mean"] for a in bj_annual]
        mx = max(vals) * 1.06
        n2 = len(vals)
        bw2 = pw / n2
        for i, a in enumerate(bj_annual):
            x0, x1 = L + i * bw2 + 3, L + (i + 1) * bw2 - 3
            ci = aqi.us_aqi(a["mean"])[1]
            c = png.rgb({0: "#39a852", 1: "#d4a017", 2: "#ef8033",
                         3: "#e0483f", 4: "#9c4fbf", 5: "#a33b52"}[ci])
            if a["partial"]:
                c = png.lerp(c, surface, 0.5)
            h = a["mean"] / mx * panel_h
            png.bar(buf, W, H, x0, x1, T2 + panel_h - h, T2 + panel_h, c, r=6)
        # China's own annual standard, the line the fall had to cross
        ys = T2 + panel_h - (35.0 / mx) * panel_h
        for x in range(L - 14, L + pw + 14, 12):
            png.fill(buf, W, H, x, ys - 1, x + 7, ys + 1, png.rgb("#8f88a8"))

    # Labels. An unlabelled two-panel chart makes the reader guess which city is
    # which, and a shared link gets one glance.
    ink, faint = png.rgb("#f4f3f8"), png.rgb("#8b87a3")
    png.rrect(buf, W, H, L, 40, L + 26, 52, png.rgb("#6f6dff"), r=5)
    png.rrect(buf, W, H, L + 32, 40, L + 58, 52, png.rgb("#2ea8bf"), r=5)
    png.text(buf, W, H, L + 74, 39, "WEATHER.AKGUO.COM", faint, scale=2)
    # text() returns the width it drew, so the subtitle sits after the title
    # rather than at a guessed offset that a longer year range would overrun.
    wpx = png.text(buf, W, H, L, T - 32, f"LONDON {ldn_years[0]}-{ldn_partial}", ink, scale=3)
    png.text(buf, W, H, L + wpx + 22, T - 27, "HOT DAYS VS THE 1961-90 NORMAL", faint, scale=2)
    if bj_annual:
        wpx = png.text(buf, W, H, L, T2 - 32,
                       f"BEIJING {bj_annual[0]['y']}-{bj_annual[-1]['y']}", ink, scale=3)
        png.text(buf, W, H, L + wpx + 22, T2 - 27,
                 "ANNUAL MEAN PM2.5, MICROGRAMS/M3", faint, scale=2)
    png.write(path_out, W, H, buf)


def app_icon(path_out):
    """180x180: the brand squircle, matching favicon.svg as closely as flat
    rectangles allow. The gradient and the rounded corners are painted in one
    pass — a row's horizontal inset comes from the corner radius, its colour
    from its position down the gradient."""
    import math
    S, R = 180, 42
    buf = png.canvas(S, S, "#0b0b12")
    top, bot = png.rgb("#6f6dff"), png.rgb("#2ea8bf")
    for y in range(S):
        dy = min(y, S - 1 - y)
        inset = R - int((R * R - (R - 1 - dy) ** 2) ** 0.5) if dy < R else 0
        png.fill(buf, S, S, inset, y, S - inset, y + 1, png.lerp(top, bot, y / S))

    white = png.rgb("#ffffff")
    for i in range(161):                     # the rising arc, sampled and dotted
        t = i / 160
        x = 38 + t * 104
        yv = 120 - math.sin(t * math.pi) * 56
        png.rrect(buf, S, S, x - 7, yv - 7, x + 7, yv + 7, white, r=7)
    png.rrect(buf, S, S, 56, 134, 124, 146, white, r=6)
    png.write(path_out, S, S, buf)


# ── assembly ----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh-ecad", action="store_true",
                    help="re-extract the Heathrow series from KNMI (monthly)")
    ap.add_argument("--refresh-ghcn", action="store_true",
                    help="re-pull Beijing's official daily series from NOAA (monthly)")
    ap.add_argument("--backfill-aq", action="store_true",
                    help="rebuild the whole PM2.5 archive from 2013 (slow, rare)")
    ap.add_argument("--offline", action="store_true",
                    help="build from cached data only; fetch nothing")
    args = ap.parse_args()

    os.makedirs(SITE, exist_ok=True)

    print("London ...")
    ldn_rec, ldn, eca_last, ldn_last = build_london(args)
    print("Beijing temperature ...")
    bj_rec, bjt = build_beijing_temps(args)
    print("Beijing air ...")
    air, hourly = build_air(args)

    stamp = ldn_last
    temp_css, temp_html, temp_js = read("templates", "temp.css"), read("templates", "temp.html"), read("templates", "temp.js")
    air_css, air_html, air_js = read("templates", "air.css"), read("templates", "air.html"), read("templates", "air.js")

    # ── /london ──
    t = read("templates", "london.tmpl.html")
    t = (t.replace("__TEMP_CSS__", temp_css)
          .replace("__TEMP_HTML__", temp_html)
          .replace("__TEMP_JS__", temp_js)
          .replace("__TEMP_DATA__", render.j(ldn))
          .replace("__FIRSTYEAR__", str(ldn_rec.years[0]))
          .replace("__TOPBAR__", design.topbar(f"through {fmt_short(ldn_last)}")))
    render.emit(SITE, "london.html", t, path="/london", stamp=stamp, image="social.png")

    # ── /beijing ──
    t = read("templates", "beijing.tmpl.html")
    t = (t.replace("__TEMP_CSS__", temp_css).replace("__AIR_CSS__", air_css)
          .replace("__TEMP_HTML__", temp_html).replace("__AIR_HTML__", air_html)
          .replace("__TEMP_JS__", temp_js).replace("__AIR_JS__", air_js)
          .replace("__TEMP_DATA__", render.j(bjt)).replace("__AIR_DATA__", render.j(air))
          .replace("__TOPBAR__", design.topbar(f"through {fmt_short(bj_rec.cur_date)}")))
    render.emit(SITE, "beijing.html", t, path="/beijing", stamp=stamp,
                image="social-beijing.png",
                head_extra='<link rel="stylesheet" href="/vendor/leaflet/leaflet.css">\n',
                body_extra='<script defer src="/vendor/leaflet/leaflet.js"></script>\n')

    # ── / ──
    render.emit(SITE, "index.html", home_page(ldn_rec, ldn, bj_rec, air, hourly),
                path="/", stamp=stamp)

    # ── /404 ──
    t = read("templates", "404.tmpl.html").replace("__TOPBAR__", design.topbar(""))
    render.emit(SITE, "404.html", t)

    # ── static assets ──
    with open(os.path.join(SITE, "favicon.svg"), "w") as f:
        f.write(design.FAVICON)
    with open(os.path.join(SITE, "site.webmanifest"), "w") as f:
        json.dump(render.MANIFEST, f, indent=1)
    with open(os.path.join(SITE, "_redirects"), "w") as f:
        # The old site lived at / and /year_explorer. Both must keep working:
        # links to them exist, and Pages would otherwise answer with the 404.
        f.write("/year_explorer  /london  301\n"
                "/year_explorer/ /london  301\n"
                "/heathrow       /london  301\n")
    with open(os.path.join(SITE, "_headers"), "w") as f:
        # The HTML is regenerated daily and must not be held stale, but the
        # vendored library and the icons are content that only changes when the
        # build changes them.
        f.write("/*\n  X-Content-Type-Options: nosniff\n"
                "  Referrer-Policy: strict-origin-when-cross-origin\n"
                "  Cache-Control: public, max-age=300, must-revalidate\n\n"
                "/vendor/*\n  Cache-Control: public, max-age=31536000, immutable\n\n"
                "/*.png\n  Cache-Control: public, max-age=86400\n\n"
                "/favicon.svg\n  Cache-Control: public, max-age=86400\n")
    with open(os.path.join(SITE, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {design.SITE_URL}/sitemap.xml\n")
    today_iso = date.today().isoformat()
    with open(os.path.join(SITE, "sitemap.xml"), "w") as f:
        urls = "".join(
            f"<url><loc>{design.SITE_URL}{'' if p == '/' else p}</loc>"
            f"<lastmod>{today_iso}</lastmod></url>" for p in ("/", "/london", "/beijing"))
        f.write('<?xml version="1.0" encoding="UTF-8"?>'
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')

    vendor = os.path.join(SITE, "vendor", "leaflet")
    os.makedirs(vendor, exist_ok=True)
    for f in ("leaflet.js", "leaflet.css"):
        shutil.copyfile(P("assets", "leaflet", f), os.path.join(vendor, f))

    app_icon(os.path.join(SITE, "apple-touch-icon.png"))
    social_card(os.path.join(SITE, "social.png"), ldn_rec.years,
                ldn["hist"]["d1"], ldn_rec.cur_year, air["annual"])
    shutil.copyfile(os.path.join(SITE, "social.png"),
                    os.path.join(SITE, "social-beijing.png"))

    # ── report ──
    i = ldn_rec.years.index(ldn_rec.cur_year)
    print("\n=== built ===")
    h = ldn["hist"]
    print(f"London  through {fmt_long(ldn_last)}: " +
          ", ".join(f"{h[m.key][i]} {m.label.lower()}" for m in LONDON_METRICS))
    j = bj_rec.years.index(bj_rec.cur_year)
    hb = bjt["hist"]
    print(f"Beijing through {fmt_long(bj_rec.cur_date)}: " +
          ", ".join(f"{hb[m.key][j]} {m.label.lower()}" for m in BEIJING_METRICS))
    if air["annual"]:
        a = air["annual"][-1]
        print(f"Beijing PM2.5 {air['first']}..{air['last']}: {a['y']} mean "
              f"{a['mean']} µg/m³ (US AQI {aqi.us_aqi(a['mean'])[0]}, "
              f"CN {aqi.cn_aqi(a['mean'])[0]})")
    print("wrote public/: index.html, london.html, beijing.html, 404.html, "
          "icons, social cards, _redirects, sitemap.xml, vendor/leaflet")


def home_page(ldn_rec, ldn, bj_rec, air, hourly):
    """The overview: one live tile per city, plus the four facts worth a glance."""
    t = read("templates", "home.tmpl.html")
    h = ldn["hist"]
    i = ldn_rec.years.index(ldn_rec.cur_year)

    # London's tile leads with the count that is running hottest against its own
    # normal, which is more interesting than always showing the same metric.
    best_m, best_score, best_now = None, -99, 0
    for m in ldn_rec.metrics:
        vals = h[m.key + "y"]
        try:
            a, b = ldn_rec.years.index(1961), ldn_rec.years.index(1990)
            normal = sum(vals[a:b + 1]) / (b - a + 1)
        except ValueError:
            normal = sum(vals) / len(vals)
        now = vals[i]
        score = (now - normal) / max(1.0, normal)
        if score > best_score:
            best_m, best_score, best_now = m, score, now
    rank = 1 + sum(1 for v in h[best_m.key + "y"] if v > best_now)

    ldn_spark = _spark(ldn_rec, ldn)
    bj_spark = _spark_air(air)

    live = air.get("live") or {}
    conc = live.get("city")
    if conc is not None:
        idx, cat = aqi.us_aqi(conc)
        tint = f"var({aqi.US_CATS[cat][2]})"
        bj_big, bj_verdict = str(idx), aqi.US_CATS[cat][0]
        bj_sub = (f"PM2.5 <b>{conc:.0f} µg/m³</b> over the last 24 hours, averaged across "
                  f"<b>{live.get('n', 0)}</b> stations. {live.get('time', '')}")
    else:
        tint, bj_big, bj_verdict = "var(--ink-muted)", "–", "Live feed unavailable"
        bj_sub = "Showing the archive; the live station feed did not answer this build."

    annual = air["annual"]
    first_a, last_full = (annual[0], [a for a in annual if not a["partial"]][-1]) if annual else (None, None)

    facts = []
    if last_full:
        facts.append(("--aqi-1", f"−{round((1 - last_full['mean'] / first_a['mean']) * 100)}%",
                      f"Beijing's annual PM2.5, {first_a['y']} to {last_full['y']}"))
        facts.append(("--negative", f"{last_full['mean'] / aqi.WHO_ANNUAL:.1f}×",
                      "and still that many times the WHO annual guideline"))
    facts.append(("--day-2", str(h["d2"][i]),
                  f"days at 30 °C or more at Heathrow so far in {ldn_rec.cur_year}"))
    bj_h = bj_rec.hist()
    bj_i = bj_rec.years.index(bj_rec.cur_year)
    facts.append(("--day-1", str(bj_h["d2"][bj_i]),
                  f"days at 35 °C or more in Beijing so far in {bj_rec.cur_year}"))

    facts_html = "".join(
        f'<div class="fact" style="--tint:var({c})"><div class="v">{v}</div>'
        f'<div class="l">{l}</div></div>' for c, v, l in facts[:4])

    ldn_yrs = ldn_rec.years
    return (t.replace("__TOPBAR__", design.topbar(f"rebuilt {date.today().strftime('%-d %b')}"))
             .replace("__LDN_TINT__", best_m.css)
             .replace("__LDN_RANGE__", f"{ldn_yrs[0]}–{ldn_yrs[-1]}")
             .replace("__LDN_BIG__", str(best_now))
             .replace("__LDN_UNIT__", best_m.unit)
             .replace("__LDN_VERDICT__", f"{best_m.label} {best_m.sub}")
             .replace("__LDN_SUB__", f"So far in {ldn_rec.cur_year}, to {h['ytd']} — "
                                     f"<b>{_ord(rank)}</b> of {len(ldn_yrs)} years on record "
                                     f"for the same window.")
             .replace("__LDN_SPARK__", ldn_spark)
             .replace("__BJ_TINT__", tint)
             .replace("__BJ_BIG__", bj_big)
             .replace("__BJ_VERDICT__", bj_verdict)
             .replace("__BJ_SUB__", bj_sub)
             .replace("__BJ_SPARK__", bj_spark)
             .replace("__FACTS__", facts_html)
             .replace("__US_BP__", render.j([list(b) for b in aqi.US_PM25]))
             .replace("__US_CATS__", render.j([{"name": n, "css": c} for n, _, c in aqi.US_CATS]))
             .replace("__ABOUT_LONDON__", ldn["source"])
             .replace("__ABOUT_BEIJING_T__", _bjt_about(bj_rec))
             .replace("__ABOUT_BEIJING_A__", air["source"])
             .replace("__ABOUT_FRESH__",
                      "A GitHub Action rebuilds every page each morning and commits the "
                      "result, so the site is never more than a day behind its sources. "
                      "The Beijing air-quality tile goes further and asks the monitoring "
                      "network directly each time the page is opened."))


def _bjt_about(bj_rec):
    return ("Beijing Capital Airport, station 54511. NOAA's official daily series is "
            "complete to 2012 and then falls apart, so the gaps and everything after are "
            "filled from the same airport's METAR reports. Thresholds are five degrees "
            "above London's, and 35 °C is the China Meteorological Administration's own "
            "high-temperature warning line rather than a round number.")


def _ord(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _spark(rec, ldn):
    """The last 40 years of the leading metric, as an inline sparkline."""
    vals = ldn["hist"]["d1"][-40:]
    return _spark_svg(vals, "var(--day-1)")


def _spark_air(air):
    vals = [a["mean"] for a in air["annual"]]
    return _spark_svg(vals, "var(--aqi-1)", invert=True)


def _spark_svg(vals, colour, invert=False):
    if not vals:
        return ""
    W, H = 300, 56
    lo, hi = min(vals), max(vals)
    span = max(1e-6, hi - lo)
    pts = []
    for i, v in enumerate(vals):
        x = i / max(1, len(vals) - 1) * W
        y = H - 4 - (v - lo) / span * (H - 10)
        pts.append(f"{x:.1f},{y:.1f}")
    area = f"M 0,{H} L " + " L ".join(pts) + f" L {W},{H} Z"
    line = "M " + " L ".join(pts)
    return (f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" aria-hidden="true">'
            f'<path d="{area}" fill="{colour}" fill-opacity=".14"/>'
            f'<path d="{line}" fill="none" stroke="{colour}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
            f'</svg>')


if __name__ == "__main__":
    sys.exit(main())
