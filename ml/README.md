# PM2.5 model

A weather-only model of Beijing's hourly PM2.5, kept apart from the site build
(which stays dependency-free). Everything runs from a local venv:

```bash
cd ml
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python numpy pandas scikit-learn lightgbm torch matplotlib pyarrow
# LightGBM needs libomp; torch ships one, so if brew is unavailable:
mkdir -p .venv/lib/omp && ln -sf "$PWD/.venv/lib/python3.12/site-packages/torch/lib/libomp.dylib" .venv/lib/omp/libomp.dylib
install_name_tool -add_rpath "$PWD/.venv/lib/omp" .venv/lib/python3.12/site-packages/lightgbm/lib/lib_lightgbm.dylib

.venv/bin/python fetch_metar.py     # ZBAA METAR with every field, Beijing time
.venv/bin/python fetch_era5.py      # ERA5 hourly via Open-Meteo, pinned to models=era5
.venv/bin/python train.py           # forward split: train <=2022, val 2023, test 2024+
.venv/bin/python cv.py              # blocked month-holdout CV across all years
.venv/bin/python analyze.py         # counterfactuals -> out/analysis.json
```

`dataset.py` joins `../data/beijing_pm25_hourly.csv` to the two downloads and
builds the features. `report.html` is the write-up; `out/report_data.json` is
injected at `__DATA__` to make `out/report.html`.

Things that bit, so they are not repeated:

- A raw `year` input makes the neural nets extrapolate the 2013–22 decline. The
  trailing-365-day mean (lagged a month) replaces it.
- Open-Meteo's default archive blends models; ERA5 100 m wind stepped from 3.5
  to 4.7 m/s in 2017 and back in 2025. `models=era5` fixes it. Boundary-layer
  height is missing Jan–Jun 2024 regardless.
- METAR cloud fields leak visibility (`CAVOK` implies >=10 km), and were the
  third most important feature until removed. Visibility and haze codes are out
  for the same reason.
- Chinese METARs carry no precipitation amounts; `p01i` is always 0. Amounts
  come from ERA5, presence and intensity from the weather codes.

## Forecasting

```bash
.venv/bin/python fetch_cities.py     # 20 surrounding cities, hourly PM2.5/PM10, ~70 min first time
.venv/bin/python merge_cities.py
.venv/bin/python parse_igra.py       # after downloading CHM00054511-data.txt.zip into data/igra/
.venv/bin/python train_lead.py       # weather model + lead-aware residual model, skill by lead (ERA5 as forecast)
.venv/bin/python fetch_prev_runs.py  # archived 1-7 day forecasts, 2024-
.venv/bin/python eval_realfc.py      # real-forecast vs perfect-forecast skill by lead
.venv/bin/python forecast.py         # this week's outlook -> out/forecast.json
```

`forecast.py` fits the deployment models once (cached in `out/`), then each
run fetches the current Open-Meteo forecast (7 days back for the history
features, 7 ahead, with 925/850/700 hPa levels for the sounding features), the
last week of CNEMC readings, and the upwind cities, and writes the outlook.

More things that bit:

- A lead-aware model with raw `pm25_last` and `lead` as inputs learns
  nothing: `lead` has no marginal gain, so boosting never finds the
  interaction. Modelling the *residual* of the weather model, with the
  residual at issue time as input, works (persistence at 1 h, weather-only by
  48 h).
- Open-Meteo's previous-runs archive has no boundary-layer height or pressure
  levels, so the real-forecast evaluation uses a slightly reduced model.
- The `china_cities_*.csv` archive starts 2014-05-13.
