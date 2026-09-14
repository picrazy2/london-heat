"""How good is the forecast really, and whose fault are the misses?

For each lead of 1..7 days over 2024-Sep 2026, the same weather model is run
twice on the same hours: once on the forecast that was actually issued that
many days earlier, once on ERA5 reanalysis (a perfect forecast). Against the
measured PM2.5, the gap between the two is the weather forecast's error; the
rest is the model's. The residual (nowcast) correction is applied on top in
both cases, from Beijing's and the upwind cities' readings at issue time.
"""
import json, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import r2_score
import dataset, train, train_lead

df = dataset.build()
# archive-compatible weather inputs: no boundary layer, no low cloud, no soundings
DROP = ("boundary_layer", "cloud_cover_low", "blh_missing", "soil", "et0")
cols_w = [c for c in dataset.feature_sets(df)["forecastable"] if c != "year_frac" and not c.startswith("s_") and not any(k in c for k in DROP)] + ["level365"]
tr, va, te = train.split(df); y = np.log1p(df["pm25"])
wpred = train_lead.oof_weather(df, cols_w, tr | va)
_, pt, mw = train.fit_lgb(df.loc[tr, cols_w], y[tr], df.loc[va, cols_w], y[va], df.loc[te, cols_w])
wpred[te] = pt; resid = (y - wpred).to_numpy()
print(f"archive-compatible weather model, ERA5-driven, test r2_log {r2_score(y[te], wpred[te]):.3f}")
mr, cols_r = train_lead.fit_resid(df, resid, wpred, tr, va)

prev = pd.read_csv("data/prev_runs.csv", index_col=0); prev.index = pd.to_datetime(prev.index)
SURF = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation", "rain", "snowfall", "pressure_msl", "surface_pressure",
        "cloud_cover", "wind_speed_10m", "wind_gusts_10m", "wind_speed_100m", "shortwave_radiation", "vapour_pressure_deficit"]

def forecast_frame(d):
    f = prev[[c for c in prev.columns if c.endswith(f"|{d}")]].copy(); f.columns = [c.split("|")[0] for c in f.columns]
    f["rain"] = f["rain"].fillna(f["precipitation"] - f["snowfall"].fillna(0))
    f = f.interpolate(limit=6, limit_direction="both")
    e = pd.DataFrame(index=f.index)
    for c in SURF: e["e_" + c] = f[c]
    a10, a100 = np.deg2rad(f["wind_direction_10m"]), np.deg2rad(f["wind_direction_100m"])
    e["e_v_north"] = f["wind_speed_10m"] * np.cos(a10); e["e_u_east"] = f["wind_speed_10m"] * np.sin(a10)
    e["e_v_north100"] = f["wind_speed_100m"] * np.cos(a100); e["e_u_east100"] = f["wind_speed_100m"] * np.sin(a100)
    e["e_boundary_layer_height"] = np.nan; e["e_cloud_cover_low"] = np.nan; e["e_snowfall"] = f["snowfall"]
    X = dataset.engineer(e); X["level365"] = df["level365"].reindex(X.index)
    return X.reindex(df.index[te])

rows = []
for d in range(1, 8):
    L = 24 * d
    Xf = forecast_frame(d)
    w_fc = pd.Series(mw.predict(Xf[cols_w], num_iteration=mw.best_iteration), index=Xf.index)
    w_era = wpred[te]
    # residual correction from what was known at issue time (identical in both runs)
    F = train_lead.resid_frame(df, resid, wpred, np.full(len(df), L))[cols_r].loc[te]
    F_fc = F.copy(); F_fc["w_now"] = w_fc          # the residual model sees the forecast-driven W for the target hour
    corr_era = mr.predict(F, num_iteration=mr.best_iteration); corr_fc = mr.predict(F_fc, num_iteration=mr.best_iteration)
    ok = te[te] & Xf["e_temperature_2m"].notna() & F["r_last"].notna() & y[te].notna()
    yt = y[te][ok]
    def sc(p): p = p[ok]; return r2_score(yt, p), float(np.abs(np.expm1(yt) - np.expm1(p)).mean())
    r = {"lead_h": L, "n": int(ok.sum()),
         "perfect_fc": sc(w_era), "real_fc": sc(w_fc), "perfect_fc+nowcast": sc(w_era + corr_era), "real_fc+nowcast": sc(w_fc + corr_fc),
         "climatology": sc(pd.Series(y[tr].groupby([df.index[tr].month, df.index[tr].hour]).mean().reindex(list(zip(df.index[te].month, df.index[te].hour))).to_numpy() + (df["level365"][te] - y[tr].mean()).to_numpy() * 0, index=df.index[te]))}
    rows.append(r)
    print(f"lead {d}d: R2/MAE  perfect-fc {r['perfect_fc'][0]:.3f}/{r['perfect_fc'][1]:.1f}  real-fc {r['real_fc'][0]:.3f}/{r['real_fc'][1]:.1f}   +nowcast: perfect {r['perfect_fc+nowcast'][0]:.3f}/{r['perfect_fc+nowcast'][1]:.1f}  real {r['real_fc+nowcast'][0]:.3f}/{r['real_fc+nowcast'][1]:.1f}   climatology {r['climatology'][0]:.3f}/{r['climatology'][1]:.1f}", flush=True)
json.dump(rows, open(train.OUT / "realfc_skill.json", "w"))
# daily means, the number a person actually wants
print("\nDaily-mean skill, real forecast + nowcast:")
for d in (1, 2, 3, 5, 7):
    L = 24 * d; Xf = forecast_frame(d)
    w_fc = pd.Series(mw.predict(Xf[cols_w], num_iteration=mw.best_iteration), index=Xf.index)
    F = train_lead.resid_frame(df, resid, wpred, np.full(len(df), L))[cols_r].loc[te]; F["w_now"] = w_fc
    p = np.expm1(w_fc + mr.predict(F, num_iteration=mr.best_iteration)); a = df["pm25"][te]
    ok = p.notna() & a.notna() & F["r_last"].notna()
    pdm, adm = p[ok].resample("D").mean(), a[ok].resample("D").mean()
    print(f"  {d}d ahead: daily R2 {r2_score(adm, pdm):.3f}  MAE {np.abs(adm - pdm).mean():.1f}   |  hit rate for 'day > 35 ug/m3': {((pdm > 35) == (adm > 35)).mean():.2f}")
