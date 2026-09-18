"""Hourly forecast error by lead, for the confidence band on the charts.

log(actual / forecast) percentiles for every hour of 2024-26 at each lead:
1-23 h from the reanalysis-driven run (a one-day weather forecast is close
to perfect at that range), 24-168 h from the forecasts actually issued.
Writes intervals_h into data/pm25_analysis.json."""
import json, numpy as np, pandas as pd, lightgbm as lgb
import dataset, train, train_lead

df = dataset.build()
cols_w = [c for c in dataset.feature_sets(df)["forecastable"] if c != "year_frac"] + ["level365"]
tr, va, te = train.split(df); y = np.log1p(df["pm25"])
wpred = train_lead.oof_weather(df, cols_w, tr | va)
_, pt, mw = train.fit_lgb(df.loc[tr, cols_w], y[tr], df.loc[va, cols_w], y[va], df.loc[te, cols_w]); wpred[te] = pt
resid = (y - wpred).to_numpy(); mr, cols_r = train_lead.fit_resid(df, resid, wpred, tr, va)
pct = [10, 25, 50, 75, 90]; out = {"leads": [], "pct": pct, "log_err": []}
# short leads: ERA5 as the forecast
for L in (1, 2, 3, 6, 9, 12, 18):
    F = train_lead.resid_frame(df, resid, wpred, np.full(len(df), L))[cols_r]
    p = wpred + mr.predict(F, num_iteration=mr.best_iteration); ok = te & F["r_last"].notna() & y.notna()
    e = (y[ok] - p[ok]); out["leads"].append(L); out["log_err"].append([round(float(np.percentile(e, q)), 4) for q in pct])
    print(f"lead {L:3d} h: 80% band x{np.exp(np.percentile(e, 10)):.2f} – x{np.exp(np.percentile(e, 90)):.2f}")
# day leads: the real forecast, archive-compatible model (as eval_realfc.py)
DROP = ("boundary_layer", "cloud_cover_low", "blh_missing", "soil", "et0")
cols_a = [c for c in cols_w if not c.startswith("s_") and not any(k in c for k in DROP)]
wa = train_lead.oof_weather(df, cols_a, tr | va); _, pa, ma = train.fit_lgb(df.loc[tr, cols_a], y[tr], df.loc[va, cols_a], y[va], df.loc[te, cols_a]); wa[te] = pa
ra = (y - wa).to_numpy(); mra, cols_ra = train_lead.fit_resid(df, ra, wa, tr, va)
prev = pd.read_csv("data/prev_runs.csv", index_col=0); prev.index = pd.to_datetime(prev.index)
SURF = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation", "rain", "snowfall", "pressure_msl", "surface_pressure", "cloud_cover", "wind_speed_10m", "wind_gusts_10m", "wind_speed_100m", "shortwave_radiation", "vapour_pressure_deficit"]
def frame(d):
    f = prev[[c for c in prev.columns if c.endswith(f"|{d}")]].copy(); f.columns = [c.split("|")[0] for c in f.columns]
    f["rain"] = f["rain"].fillna(f["precipitation"] - f["snowfall"].fillna(0)); f = f.interpolate(limit=6, limit_direction="both")
    e = pd.DataFrame(index=f.index)
    for c in SURF: e["e_" + c] = f[c]
    a10, a100 = np.deg2rad(f["wind_direction_10m"]), np.deg2rad(f["wind_direction_100m"])
    e["e_v_north"] = f["wind_speed_10m"] * np.cos(a10); e["e_u_east"] = f["wind_speed_10m"] * np.sin(a10)
    e["e_v_north100"] = f["wind_speed_100m"] * np.cos(a100); e["e_u_east100"] = f["wind_speed_100m"] * np.sin(a100)
    e["e_boundary_layer_height"] = np.nan; e["e_cloud_cover_low"] = np.nan; e["e_snowfall"] = f["snowfall"]
    X = dataset.engineer(e); X["level365"] = df["level365"].reindex(X.index); return X.reindex(df.index[te])
for d in range(1, 8):
    L = 24 * d; Xf = frame(d); w_fc = pd.Series(ma.predict(Xf[cols_a], num_iteration=ma.best_iteration), index=Xf.index)
    F = train_lead.resid_frame(df, ra, wa, np.full(len(df), L))[cols_ra].loc[te]; F["w_now"] = w_fc
    p = w_fc + mra.predict(F, num_iteration=mra.best_iteration); ok = Xf["e_temperature_2m"].notna() & F["r_last"].notna() & y[te].notna()
    e = (y[te][ok] - p[ok]); out["leads"].append(L); out["log_err"].append([round(float(np.percentile(e, q)), 4) for q in pct])
    print(f"lead {L:3d} h: 80% band x{np.exp(np.percentile(e, 10)):.2f} – x{np.exp(np.percentile(e, 90)):.2f}")
a = json.load(open("../data/pm25_analysis.json")); a["intervals_h"] = out
json.dump(a, open("../data/pm25_analysis.json", "w"), separators=(",", ":")); print("written")
