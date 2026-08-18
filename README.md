# Weather

Long instrument records for two cities, rebuilt every morning and served as a
static site at **[weather.akguo.com](https://weather.akguo.com)**.

- **London** — hot days and warm nights at Heathrow since 1960, from the
  airport's own thermometer.
- **Beijing** — the same four counts against a hotter city's thresholds, plus
  **PM2.5** from the city's monitoring network, judged on both the US EPA and the
  Chinese scale, with a live map of every station.

Cloudflare Pages serves `public/` and deploys on every push to `main`. One
Pages Function, `/api/live`, gives the pages a current reading.

## The one command

```bash
python3 build.py
```

Downloads the latest of everything, recomputes every dataset, and regenerates
`public/`. No dependencies beyond the Python standard library, and **no API keys
anywhere** — every source is public and open, which is what lets the daily
GitHub Action run with no secrets at all.

| Flag | When |
|------|------|
| `--refresh-ecad` | KNMI republishes Heathrow. Monthly. |
| `--refresh-ghcn` | NOAA republishes Beijing. Monthly. |
| `--backfill-aq` | Rebuild the PM2.5 archive from 2013. Rare, and slow (~4,600 requests). |
| `--offline` | Build from cached data only. Fetch nothing. Use this while working on the design. |

`.github/workflows/refresh.yml` runs the daily build at 00:40 UTC and a second
pass at 13:25 UTC for Beijing readings that arrive late, then commits and lets
Pages redeploy.

## Data sources

Every one of them is keyless.

| What | Where | Caveat |
|------|-------|--------|
| London daily max/min | **ECA&D** (KNMI) blended series, Heathrow STAID 1860 | Authoritative; lags weeks to months |
| London recent days | **METAR** EGLL via Iowa Environmental Mesonet | Current to the hour; maxima run slightly low |
| Beijing daily max/min | **GHCN-Daily** station `CHM00054511` (Capital Airport) | Complete 1951–2012; then broken (see below) |
| Beijing recent + gaps | **METAR** ZBAA via Iowa Environmental Mesonet | Unbroken 1973–now; whole degrees only |
| Beijing PM2.5 history | **CNEMC** hourly publication, mirrored daily at `quotsoft.net` | 35 city stations, hourly, µg/m³, from Dec 2013 |
| Beijing PM2.5 live | **CNEMC** real-time feed, `air.cnemc.cn` | 23 stations with coordinates; drives the map |
| London live temperature | **Open-Meteo** | Only for the overview tile, not the record |

### Why Beijing's temperature is stitched

NOAA's Beijing series is complete and official to 2012, then collapses: 2013–2019
is almost entirely absent, and NOAA stopped receiving the station in August 2025.
So every day GHCN does not cover is filled from the same airport's METAR. The
stitch is per-day, not just at the tail.

The build measures the resulting bias instead of hand-waving at it. On the ~6,400
recent days where both sources report, METAR runs about 0.7 °C below the official
daily maximum and 1.1 °C below the official minimum, so the METAR-filled years
*undercount* every threshold — the page states the per-threshold figures it
computed. Nothing before 2013 is METAR, so the 1961–90 baseline the charts are
measured against is not itself mixed.

### Why not the obvious PM2.5 sources

Two were tried and rejected:

- **Copernicus CAMS** (via Open-Meteo) is keyless and easy, and models Beijing's
  annual mean at ~82 µg/m³ against a measured ~30. A factor of 2.7 would have
  made every number on the page wrong.
- **WAQI** publishes US-EPA *index* values, not concentrations. You cannot
  re-derive China's index from America's answer without the number both were
  computed from, so the scale toggle would have been impossible.

CNEMC is the city's own network, publishes µg/m³, and needs no key.

## The two AQI scales

The page never stores an index. It ships concentrations plus both breakpoint
tables and derives every AQI in the browser, so the toggle re-judges identical
numbers rather than swapping in a different measurement.

- **US EPA** — 40 CFR 58 Appendix G, as revised in 2024 (the Good/Moderate break
  moved from 12.0 to 9.0 µg/m³). Concentration is truncated to one decimal.
- **China** — HJ 633-2012, Table 1, 24-hour PM2.5. Concentration is used as an
  integer.

They disagree sharply and that gap is the point: 35 µg/m³ is simultaneously the
top of China's *best* band (AQI 50, 优) and the top of the US "Moderate" band
(AQI ~100). The default is the US scale, being the stricter of the two.
`weather/aqi.py` holds both tables and is the only place they are written down.

## Metrics

|  | London | Beijing |
|--|--------|---------|
| Hot day | max ≥ 25 °C | max ≥ 30 °C |
| Very hot day | max ≥ 30 °C | max ≥ **35 °C** |
| Warm night | min ≥ 15 °C | min ≥ 20 °C |
| Hot night | min ≥ 20 °C | min ≥ 25 °C |

Beijing's 35 °C is the China Meteorological Administration's own
high-temperature warning threshold, not a round number picked for symmetry.

## Repo layout

```
build.py                 the one command
weather/
├── design.py            design tokens, primitives, chrome — the whole visual system
├── render.py            fragment → real HTML document
├── aqi.py               the two breakpoint tables and the conversions
├── temps.py             every temperature aggregate, parameterised by threshold
├── png.py               a PNG writer, so icons need no dependency
├── sources/             fetch.py · temps.py (ECA&D, GHCN, METAR) · pm25.py (CNEMC)
└── pages/               city.py (temperature payload + prose) · air.py (air payload)
templates/               temp.{css,html,js} · air.{css,html,js} · the four page shells
data/                    the cached series — committed, and what the site is built from
functions/api/live.js    the Cloudflare Pages Function behind /api/live
assets/leaflet/          vendored Leaflet 1.9.4, copied into public/ at build
public/                  generated. Do not edit by hand.
```

`templates/temp.*` is one module rendered by both cities: it is handed four
metrics with thresholds, colours and labels, and knows nothing else about either
place. `templates/air.*` is Beijing-only for now.

## Design

The visual language is the one the budget app speaks — iOS 26 / macOS 26
"Liquid Glass": a tinted canvas with an ambient colour mesh, opaque cards for
resting content, translucent glass for chrome that floats over it, generous
radii, one interactive tint. What makes this a sibling rather than a clone is
the palette: **indigo `#5E5CE6` + teal `#30B0C7`** here against the budget's
blue + amber, a canvas with a violet cast rather than a cool grey one, and a
blue-black rather than pure black in the dark theme.

Everything traces to a token in `weather/design.py`. A raw hex in a template is
a bug.

Chart colour is kept clear of the accent entirely, so nothing in the chrome ever
competes with data: temperature uses hue for day-vs-night and depth within the
hue for how extreme the threshold is; air quality uses the six AQI categories,
retuned from the official EPA swatches to hold contrast on both themes.

## Renaming note

This repo was `london-heat`. The GitHub rename to `weather` is the one step that
has to be done by hand:

```bash
gh repo rename weather          # or Settings → Repository name on github.com
git remote set-url origin git@github.com:picrazy2/weather.git
```

GitHub redirects the old name, and Cloudflare Pages tracks the repo by ID, so
the deploy keeps working either way.
