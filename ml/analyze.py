"""What the model thinks drives Beijing PM2.5.

Fits the best feature set on the whole record (effects, not forecasts) and asks
it counterfactual questions. Also runs model-free checks on the raw data so the
model's answers can be judged against something.
"""
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import r2_score

import dataset, train

OUT = train.OUT
df = dataset.build()
sets = dataset.feature_sets(df)
cols = [c for c in sets["metar_era5"] if c != "year_frac"] + ["level365"]
ok = df["pm25"].notna() & df["level365"].notna()
y = np.log1p(df["pm25"])

# early-stopping set: a random 10% of months
rng = np.random.default_rng(1)
ym = df.index.year * 12 + df.index.month
months = np.array(sorted(set(ym[ok])))
va_m = rng.choice(months, size=len(months) // 10, replace=False)
va = ok & pd.Series(np.isin(ym, va_m), index=df.index)
tr = ok & ~va
X = df[cols]
_, _, model = train.fit_lgb(X[tr], y[tr], X[va], y[va], X[va].iloc[:1])
print("fit on", tr.sum(), "hours; val r2_log", round(r2_score(y[va], model.predict(X[va], num_iteration=model.best_iteration)), 3))
model.save_model(str(OUT / "lgb_final.txt"))
json.dump(cols, open(OUT / "lgb_final_cols.json", "w"))

def predict(Xd):
    return model.predict(Xd[cols], num_iteration=model.best_iteration)

res = {}

# ── 1. importance ─────────────────────────────────────────────────────────────
imp = pd.Series(model.feature_importance("gain"), index=cols)
imp = (imp / imp.sum()).sort_values(ascending=False)
print("\nTop 25 features by gain share:\n", imp.head(25).round(3).to_string())
res["importance"] = imp.round(4).to_dict()

# grouped importance
groups = {"wind (now)": ["wspd", "u_east", "v_north", "gust", "e_wind_speed_10m", "e_wind_gusts_10m", "e_wind_speed_100m", "e_v_north", "e_u_east", "e_v_north100", "e_u_east100"],
          "wind (history)": [c for c in cols if any(c.startswith(p) for p in ("v_north_", "u_east_", "wspd_", "e_v_north", "e_wind_speed")) and c[-1].isdigit()] + ["hrs_since_strong_n", "strong_n_hours24", "strong_n_hours48"],
          "humidity": ["rh", "dewpt", "dewpt_dep", "rh_m6", "rh_m24", "e_relative_humidity_2m", "e_vapour_pressure_deficit"],
          "precip": [c for c in cols if any(c.startswith(p) for p in ("precip_int", "rain", "snow", "e_precipitation", "e_snowfall"))],
          "boundary layer": [c for c in cols if "boundary_layer" in c or c == "e_blh_missing"],
          "temperature/pressure": ["temp", "temp_m24", "temp_d24", "pres", "pres_d3", "pres_d24", "e_temperature_2m", "e_pressure_msl"],
          "cloud/radiation": ["cloud", "cloud_reported", "e_cloud_cover", "e_cloud_cover_low", "e_shortwave_radiation"],
          "dust": [c for c in cols if c.startswith("dust")],
          "time of day": ["hour", "hour_sin", "hour_cos"], "season": ["month", "doy", "doy_sin", "doy_cos"],
          "week": ["dow", "dow_sin", "dow_cos", "weekend"], "CNY": ["cny_window", "cny_night"],
          "emissions level": ["level365"]}
gi = {g: float(imp.reindex(c).fillna(0).sum()) for g, c in groups.items()}
print("\nGrouped gain share:\n", pd.Series(gi).sort_values(ascending=False).round(3).to_string())
res["importance_grouped"] = gi

# ── 2. wind event study ───────────────────────────────────────────────────────
# Onset = first hour of a strong north wind (>= 5 m/s from 315-45deg) after
# 12+ hours without one. Composite of actual PM2.5 from -24h to +48h.
strong = ((df["v_north"] >= 5 * np.cos(np.deg2rad(45))) & (df["wdir"].between(315, 360) | df["wdir"].between(0, 45))).astype(int)
quiet12 = strong.shift(1).rolling(12, min_periods=12).sum() == 0
onset = (strong == 1) & quiet12
season = df.index.month.map(lambda m: "DJF" if m in (12, 1, 2) else "MAM" if m in (3, 4, 5) else "JJA" if m in (6, 7, 8) else "SON")
pm = df["pm25"].to_numpy()
lags = np.arange(-24, 49)
ev = {}
for s in ("DJF", "MAM", "JJA", "SON"):
    pos = np.where(onset.to_numpy() & (season == s))[0]
    pos = pos[(pos >= 24) & (pos + 48 < len(df))]
    mat = np.stack([pm[p + lags] for p in pos])
    ev[s] = {"n": int(len(pos)), "mean": np.nanmean(mat, axis=0).round(1).tolist(),
             "median": np.nanmedian(mat, axis=0).round(1).tolist()}
    print(f"\nnorth-wind onset {s}: n={len(pos)}  PM2.5 at -12h {ev[s]['mean'][12]:.0f}  0h {ev[s]['mean'][24]:.0f}  +6h {ev[s]['mean'][30]:.0f}  +12h {ev[s]['mean'][36]:.0f}  +24h {ev[s]['mean'][48]:.0f}  +48h {ev[s]['mean'][72]:.0f}")
res["wind_onset"] = {"lags": lags.tolist(), "seasons": ev}

# Dust days: PM2.5 around a spring strong-N onset with vs without dust codes in the next 24h
dust24 = df["dust"].rolling(24, min_periods=1).sum().shift(-23)     # dust reported in the coming 24h
pos = np.where(onset.to_numpy() & (season == "MAM"))[0]; pos = pos[(pos >= 24) & (pos + 48 < len(df))]
d = dust24.to_numpy()[pos] > 0
for lab, sel in (("with dust", d), ("no dust", ~d)):
    mat = np.stack([pm[p + lags] for p in pos[sel]])
    res["wind_onset"][f"MAM_{lab.replace(' ', '_')}"] = {"n": int(sel.sum()), "mean": np.nanmean(mat, axis=0).round(1).tolist()}
    print(f"spring onset {lab}: n={sel.sum()}  -12h {np.nanmean(mat[:,12]):.0f}  +6h {np.nanmean(mat[:,30]):.0f}  +24h {np.nanmean(mat[:,48]):.0f}")

# ── 3. wind partial dependence: predicted PM2.5 vs hours since strong north wind, by season
sub = df[ok].sample(20000, random_state=0)
def pdp(col, grid, sub=sub, extra=None):
    out = []
    for g in grid:
        Xc = sub.copy(); Xc[col] = g
        if extra:
            for k, v in extra(g).items(): Xc[k] = v
        out.append(float(np.expm1(predict(Xc)).mean()))
    return out

# wind direction x speed: predicted PM2.5 for a steady wind of given direction/speed for 24h
dirs = list(range(0, 360, 30)); spds = [1, 3, 6, 9]
def wind_rose(sub):
  grid_ds = {}
  for spd in spds:
    row = []
    for d_ in dirs:
        Xc = sub.copy()
        u, v = spd * np.sin(np.deg2rad(d_)), spd * np.cos(np.deg2rad(d_))
        for c in Xc.columns:
            if c.startswith("v_north") or c.startswith("e_v_north_") or c == "e_v_north": Xc[c] = v
            elif c.startswith("e_v_north100"): Xc[c] = 1.6 * v
            elif c.startswith("u_east") or c == "e_u_east": Xc[c] = u
            elif c == "e_u_east100": Xc[c] = 1.6 * u
            elif c.startswith("wspd") or c.startswith("e_wind_speed_10m"): Xc[c] = spd
            elif c.startswith("e_wind_speed_100m"): Xc[c] = 1.6 * spd
            elif c == "gust" or c == "e_wind_gusts_10m": Xc[c] = 1.5 * spd
        Xc["wdir"] = d_
        Xc["hrs_since_strong_n"] = 0 if (spd >= 5 and (d_ >= 315 or d_ <= 45)) else 48
        Xc["strong_n_hours24"] = 24 if (spd >= 5 and (d_ >= 315 or d_ <= 45)) else 0
        row.append(float(np.expm1(predict(Xc)).mean()))
    grid_ds[spd] = row
  return grid_ds
res["pdp_wind_rose"] = {"dirs": dirs, "all": wind_rose(sub)}
sub_season = season[df.index.get_indexer(sub.index)]
for s_ in ("DJF", "MAM", "JJA", "SON"):
    res["pdp_wind_rose"][s_] = wind_rose(sub[sub_season == s_])
print("PDP wind rose (24h steady wind), rows=speed m/s, cols=dir from 0 by 30:")
for s_ in ("all", "DJF", "MAM", "JJA", "SON"):
    print(" ", s_)
    for spd in spds: print(f"    {spd} m/s:", [round(v) for v in res["pdp_wind_rose"][s_][spd]])

# ── 4. precipitation ──────────────────────────────────────────────────────────
PRECIP_COLS = [c for c in cols if any(c.startswith(p) for p in ("precip_int", "rain", "snow", "e_precipitation", "e_snowfall"))]
HUMID_COLS = ["rh", "dewpt", "dewpt_dep", "rh_m6", "rh_m24", "e_relative_humidity_2m", "e_vapour_pressure_deficit", "cloud", "e_cloud_cover", "e_cloud_cover_low"]

# (a) counterfactual: hours where it rained in the past 24h; predict with rain
# kept vs every precipitation feature zeroed. Everything else (wind, RH, BLH,
# season, hour, level) held at its observed value.
wet = ok & (df["e_precipitation_s24"] > 0.5)
Xw = df.loc[wet, cols]
p_obs = np.expm1(predict(Xw))
Xz = Xw.copy(); Xz[PRECIP_COLS] = 0
p_dry = np.expm1(predict(Xz))
amt = df.loc[wet, "e_precipitation_s24"]
bins = [0.5, 2, 5, 10, 20, 50, 1000]
cf = pd.DataFrame({"obs": p_obs, "dry": p_dry, "amt": amt.to_numpy(), "actual": df.loc[wet, "pm25"].to_numpy(),
                   "month": df.index[wet].month, "rh": df.loc[wet, "rh"].to_numpy()})
cf["bin"] = pd.cut(cf["amt"], bins)
tab = cf.groupby("bin", observed=True).apply(lambda g: pd.Series({"n": len(g), "actual": g.actual.mean(), "pred_with_rain": g.obs.mean(),
        "pred_no_rain": g.dry.mean(), "effect_ug": (g.obs - g.dry).mean(), "effect_pct": 100 * (np.log(g.obs / g.dry)).mean()}))
print("\nCounterfactual: remove the rain, keep everything else (incl. humidity):\n", tab.round(1).to_string())
res["precip_counterfactual"] = tab.reset_index().assign(bin=lambda t: t["bin"].astype(str)).to_dict("records")

# (b) same, but also let humidity revert to a dry-day value: sets RH-type
# features to their monthly-hour median over dry hours. This is the total
# effect of "a rainy day vs a dry day", washout plus the humidity that comes
# with rain.
dry_ref = df.loc[ok & (df["e_precipitation_s48"] == 0), HUMID_COLS + ["month", "hour"]].groupby(["month", "hour"]).median()
Xz2 = Xz.copy()
ref = dry_ref.reindex(pd.MultiIndex.from_arrays([Xz2.index.month, Xz2.index.hour]))
for c in HUMID_COLS:
    Xz2[c] = ref[c].to_numpy()
p_dry2 = np.expm1(predict(Xz2))
cf["dry2"] = p_dry2
tab2 = cf.groupby("bin", observed=True).apply(lambda g: pd.Series({"n": len(g), "pred_with_rain": g.obs.mean(), "pred_dry_day": g.dry2.mean(),
        "effect_ug": (g.obs - g.dry2).mean(), "effect_pct": 100 * (np.log(g.obs / g.dry2)).mean()}))
print("\nCounterfactual: remove the rain AND its humidity (a dry day instead):\n", tab2.round(1).to_string())
res["precip_counterfactual_dry_day"] = tab2.reset_index().assign(bin=lambda t: t["bin"].astype(str)).to_dict("records")

# (c) by season, washout-only effect
tab3 = cf.assign(season=cf.month.map(lambda m: "DJF" if m in (12, 1, 2) else "MAM" if m in (3, 4, 5) else "JJA" if m in (6, 7, 8) else "SON")).groupby("season").apply(
    lambda g: pd.Series({"n": len(g), "effect_ug": (g.obs - g.dry).mean(), "effect_pct": 100 * np.log(g.obs / g.dry).mean(),
                         "total_effect_pct": 100 * np.log(g.obs / g.dry2).mean()}))
print("\nRain effect by season (washout-only, and total incl. humidity):\n", tab3.round(1).to_string())
res["precip_by_season"] = tab3.reset_index().to_dict("records")

# (d) timing: effect of rain as a function of when it fell. Take hours with
# exactly one rainy 6h block in the past 72h and compare by its lag.
e6 = (df["e_precipitation"].rolling(6, min_periods=1).sum() > 0.5).astype(int)
timing = {}
for lag in (0, 6, 12, 18, 24, 36, 48):
    sel = ok & (e6.shift(lag).fillna(0) == 1)
    Xs = df.loc[sel, cols]; Xs2 = Xs.copy(); Xs2[PRECIP_COLS] = 0
    timing[lag] = {"n": int(sel.sum()), "effect_pct": float(100 * (predict(Xs) - predict(Xs2)).mean())}
print("\nRain effect by hours since the rainy 6h block ended (model, washout-only):", {k: round(v["effect_pct"], 1) for k, v in timing.items()})
res["precip_timing"] = timing

# (e) model-free: stratified comparison. Within each (month, wind sector, wind
# speed tercile, hour block) cell, compare mean log PM2.5 for hours with >=2mm
# rain in the past 24h vs none in the past 48h. Average over cells weighted by
# the wet count.
d = df[ok].copy()
d["logpm"] = np.log1p(d["pm25"])
d["wet"] = np.where(d["e_precipitation_s24"] >= 2, 1, np.where(d["e_precipitation_s48"] == 0, 0, np.nan))
d = d[d["wet"].notna()]
d["sector"] = (d["wdir"].fillna(-45) // 90).astype(int)      # -1 calm, 0..3
d["spd_bin"] = pd.qcut(d["wspd_m24"], 3, labels=False)
d["hblock"] = d.index.hour // 6
d["yr_bin"] = (d.index.year >= 2019).astype(int)
cell = d.groupby(["month", "sector", "spd_bin", "hblock", "yr_bin", "wet"])["logpm"].agg(["mean", "size"]).unstack("wet")
cell = cell.dropna()
w = cell[("size", 1.0)]
diff = ((cell[("mean", 1.0)] - cell[("mean", 0.0)]) * w).sum() / w.sum()
print(f"\nModel-free stratified estimate (>=2mm in 24h vs dry 48h, within month x wind sector x wind speed x hour x era): {100*diff:+.1f}%  over {len(cell)} cells")
res["precip_stratified_pct"] = float(100 * diff)
by_m = d.groupby(["month", "sector", "spd_bin", "hblock", "yr_bin", "wet"])["logpm"].agg(["mean", "size"]).unstack("wet").dropna()
by_m = by_m.groupby(level="month").apply(lambda c: ((c[("mean", 1.0)] - c[("mean", 0.0)]) * c[("size", 1.0)]).sum() / c[("size", 1.0)].sum())
print("  by month:", {int(k): round(100 * v, 1) for k, v in by_m.items()})
res["precip_stratified_by_month_pct"] = {int(k): float(100 * v) for k, v in by_m.items()}

# ── 5. season, hour, weekday, boundary layer, humidity PDPs ──────────────────
res["pdp_month"] = {"grid": list(range(1, 13)), "pred": pdp("doy", [15 + 30.4 * (m - 1) for m in range(1, 13)],
                    extra=lambda g: {"doy_sin": np.sin(2 * np.pi * g / 365.25), "doy_cos": np.cos(2 * np.pi * g / 365.25), "month": int(g // 30.4) + 1})}
res["pdp_hour"] = {"grid": list(range(24)), "pred": pdp("hour", list(range(24)),
                   extra=lambda g: {"hour_sin": np.sin(2 * np.pi * g / 24), "hour_cos": np.cos(2 * np.pi * g / 24)})}
res["pdp_dow"] = {"grid": list(range(7)), "pred": pdp("dow", list(range(7)),
                  extra=lambda g: {"dow_sin": np.sin(2 * np.pi * g / 7), "dow_cos": np.cos(2 * np.pi * g / 7), "weekend": int(g >= 5)})}
blh_grid = [25, 50, 100, 200, 400, 800, 1200, 1800, 2500]
res["pdp_blh"] = {"grid": blh_grid, "pred": pdp("e_boundary_layer_height", blh_grid, sub[sub.e_blh_missing == 0],
                  extra=lambda g: {"e_boundary_layer_height_m6": g, "e_boundary_layer_height_m24": g})}
rh_grid = list(range(10, 101, 10))
res["pdp_rh"] = {"grid": rh_grid, "pred": pdp("rh", rh_grid, extra=lambda g: {"rh_m6": g, "rh_m24": g, "e_relative_humidity_2m": g, "dewpt_dep": (100 - g) / 5})}
ws_grid = [0, 1, 2, 3, 4, 6, 8, 10]
res["pdp_wspd24"] = {"grid": ws_grid, "pred": pdp("wspd_m24", ws_grid, extra=lambda g: {"wspd": g, "wspd_m3": g, "wspd_m6": g, "wspd_m12": g, "wspd_m48": g, "e_wind_speed_10m": g, "e_wind_speed_10m_m12": g, "e_wind_speed_10m_m24": g, "e_wind_speed_10m_m48": g, "e_wind_speed_100m": 1.6 * g, "e_wind_speed_100m_m12": 1.6 * g, "e_wind_speed_100m_m24": 1.6 * g})}
print("\nPDP month:", [round(v) for v in res["pdp_month"]["pred"]])
print("PDP hour:", [round(v) for v in res["pdp_hour"]["pred"]])
print("PDP dow:", [round(v) for v in res["pdp_dow"]["pred"]])
print("PDP BLH:", dict(zip(blh_grid, [round(v) for v in res["pdp_blh"]["pred"]])))
print("PDP RH:", dict(zip(rh_grid, [round(v) for v in res["pdp_rh"]["pred"]])))
print("PDP 24h wind speed:", dict(zip(ws_grid, [round(v) for v in res["pdp_wspd24"]["pred"]])))

# ── 6. the year trend: actual annual mean vs what the weather alone predicts
# holding the emissions level fixed at 2014's — i.e. "what if the weather of
# each year had happened to the 2014 city".
X14 = df.loc[ok, cols].copy(); X14["level365"] = df.loc[ok & (df.index.year == 2014), "level365"].mean()
p14 = pd.Series(np.expm1(predict(X14)), index=df.index[ok])
annual = pd.DataFrame({"actual": df.loc[ok, "pm25"].groupby(df.index[ok].year).mean(),
                       "weather_only_2014_city": p14.groupby(p14.index.year).mean()}).round(1)
print("\nAnnual mean actual vs weather-of-that-year applied to the 2014 city:\n", annual.to_string())
res["annual"] = annual.reset_index().rename(columns={"index": "year"}).to_dict("records")

json.dump(res, open(OUT / "analysis.json", "w"), indent=1, default=float)
print("\nwrote", OUT / "analysis.json")
