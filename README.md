# Heathrow temperature charts

Interactive charts of hot days / warm nights at **London Heathrow**, 1960–present,
built from genuine thermometer observations.

Live at **[london-heat.akguo.com](https://london-heat.akguo.com)** — Cloudflare Pages
serves the `public/` directory, deploying on every push to `main`.

## Refresh (one command)

```bash
python3 build_charts.py
```

This downloads the latest data, recomputes every dataset, and regenerates the three
pages in `public/` with all dates/values current. Commit and push to publish.

Add `--refresh-ecad` to also re-extract the official ECA&D daily series from KNMI
(only needed every few months, when they publish an update):

```bash
python3 build_charts.py --refresh-ecad
```

## Data sources

- **ECA&D** (KNMI) blended daily series for Heathrow (STAID 1860) — the official
  Met Office observations. Cached in `heathrow_tx.txt` / `heathrow_tn.txt`.
  Authoritative but lags real time by weeks–months.
- **METAR** via the Iowa Environmental Mesonet (station EGLL) — keyless, current
  to the last hour. Used to top up the days after the ECA&D cutoff.

The build stitches them: ECA&D up to its last date, METAR after. METAR-derived
daily maxima run slightly below the official figures on the hottest days (30-min
sampling misses brief afternoon peaks), so the current-year tail is a close
estimate, not the final official count.

## Files

| File | Role |
|------|------|
| `build_charts.py` | the one-command refresh + generator |
| `*.tmpl.html` | HTML templates with `__TOKEN__` data placeholders |
| `heathrow_tx.txt` / `heathrow_tn.txt` | cached ECA&D daily max / min |
| `public/` | generated — the deployed site (do not edit by hand) |
| `public/index.html` | generated — landing page |
| `public/year_explorer.html` | generated — daily explorer with year picker + decade mode |
| `public/heathrow_heat.html` | generated — annual counts + seasonal timing |
| `egll_metar.csv` | downloaded each run (git-ignored) |

The templates are bare fragments (they began life as Claude artifacts, which supplied
the document skeleton); `build_charts.py` wraps each one in a real `<!doctype>` /
`<head>` with a charset and viewport before writing it to `public/`.

## Metrics

- Hot day: daily max ≥ 25 °C · Very hot day: ≥ 30 °C
- Mild night: daily min ≥ 15 °C · Tropical night: ≥ 20 °C
