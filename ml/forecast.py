"""PM2.5 outlook for Beijing over the coming week, from the weather forecast.

Pulls Open-Meteo's best-match forecast (7 days back for the history features,
7 days ahead), maps it onto the ERA5- and sounding-style inputs the
"forecastable" model was trained on, and predicts every hour. The last
observed PM2.5 hours (fetched fresh from CNEMC via the site's own module) give
a nowcast correction that decays over the first day.
"""
import json, sys, urllib.request
from datetime import date, timedelta
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from weather.sources import pm25 as pm25src
import dataset, train, train_lead

HERE = Path(__file__).parent
OUT = train.OUT
LAT, LON = 39.9042, 116.4074
SURF = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation", "rain", "snowfall",
        "pressure_msl", "surface_pressure", "cloud_cover", "cloud_cover_low", "wind_speed_10m",
        "wind_direction_10m", "wind_gusts_10m", "wind_speed_100m", "wind_direction_100m",
        "boundary_layer_height", "shortwave_radiation", "vapour_pressure_deficit"]
LEV = [f"{v}_{p}hPa" for p in (925, 850, 700) for v in ("temperature", "wind_speed", "wind_direction")]


def fetch_forecast(past_days=7, forecast_days=7, model="best_match"):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&hourly={','.join(SURF + LEV)}"
           f"&timezone=Asia%2FShanghai&wind_speed_unit=ms&past_days={past_days}&forecast_days={forecast_days}&models={model}")
    with urllib.request.urlopen(url, timeout=120) as r:
        j = json.load(r)
    f = pd.DataFrame(j["hourly"]); f["t"] = pd.to_datetime(f["time"]); f = f.set_index("t").drop(columns="time")
    return f.interpolate(limit=6, limit_direction="both")


def to_model_frame(f):
    """Forecast columns -> the e_* / s_* names the model knows."""
    e = pd.DataFrame(index=f.index)
    for c in SURF:
        if "direction" in c: continue
        e["e_" + c] = f[c]
    e["e_et0_fao_evapotranspiration"] = np.nan; e["e_soil_moisture_0_to_7cm"] = np.nan; e["e_soil_temperature_0_to_7cm"] = np.nan
    a10, a100 = np.deg2rad(f["wind_direction_10m"]), np.deg2rad(f["wind_direction_100m"])
    e["e_v_north"] = f["wind_speed_10m"] * np.cos(a10); e["e_u_east"] = f["wind_speed_10m"] * np.sin(a10)
    e["e_v_north100"] = f["wind_speed_100m"] * np.cos(a100); e["e_u_east100"] = f["wind_speed_100m"] * np.sin(a100)
    e["e_blh_missing"] = e["e_boundary_layer_height"].isna().astype(int)
    # Sounding-style features, sampled at the two launch times and carried
    # forward, exactly as the twice-daily radiosonde was in training.
    s = pd.DataFrame(index=f.index)
    s["s_inv925"] = f["temperature_925hPa"] - f["temperature_2m"]
    s["s_inv850"] = f["temperature_850hPa"] - f["temperature_2m"]
    for p in (925, 850, 700):
        s[f"s_ws{p}"] = f[f"wind_speed_{p}hPa"]
        s[f"s_vn{p}"] = f[f"wind_speed_{p}hPa"] * np.cos(np.deg2rad(f[f"wind_direction_{p}hPa"]))
    launches = s[s.index.hour.isin([8, 20])]
    s = dataset.carry_soundings(launches, f.index).drop(columns="s_age")
    return e.join(s)


def recent_pm25(days=8):
    """Hourly city-mean PM2.5 for the last `days`, straight from the network."""
    out = {}
    for i in range(days, -1, -1):
        d = date.today() - timedelta(i)
        hrs = pm25src.fetch_day(d)
        if hrs:
            for h, (v, n) in hrs.items():
                out[pd.Timestamp(d) + pd.Timedelta(hours=h)] = v
    return pd.Series(out).sort_index()


def fit_deploy_models(df, cols):
    """Weather model W and residual model R, fit on the whole record for deployment."""
    pw, pr = OUT / "lgb_forecastable_deploy.txt", OUT / "lgb_resid_deploy.txt"
    if pw.exists() and pr.exists():
        return lgb.Booster(model_file=str(pw)), lgb.Booster(model_file=str(pr)), json.load(open(OUT / "lgb_resid_deploy_cols.json"))
    ok = df["pm25"].notna() & df["level365"].notna()
    rng = np.random.default_rng(2)
    ym = df.index.year * 12 + df.index.month
    months = np.array(sorted(set(ym[ok]))); va_m = rng.choice(months, size=len(months) // 10, replace=False)
    va = ok & pd.Series(np.isin(ym, va_m), index=df.index); tr = ok & ~va
    y = np.log1p(df["pm25"])
    _, _, mw = train.fit_lgb(df.loc[tr, cols], y[tr], df.loc[va, cols], y[va], df.loc[va, cols].iloc[:1])
    mw.save_model(str(pw))
    wpred = train_lead.oof_weather(df, cols, ok)
    resid = (y - wpred).to_numpy()
    mr, cols_r = train_lead.fit_resid(df, resid, wpred, tr, va)
    mr.save_model(str(pr)); json.dump(cols_r, open(OUT / "lgb_resid_deploy_cols.json", "w"))
    return mw, mr, cols_r


def recent_cities(days=2):
    """Upwind city-group PM2.5/PM10 for the last couple of days, straight from the network."""
    import io
    rows = []
    for i in range(days, -1, -1):
        d = date.today() - timedelta(i)
        try:
            with urllib.request.urlopen(f"https://quotsoft.net/air/data/china_cities_{d:%Y%m%d}.csv", timeout=60) as r:
                rows.append(pd.read_csv(io.BytesIO(r.read()), dtype={"date": str}))
        except Exception:
            continue
    if not rows: return None
    d = pd.concat(rows); d = d[d["type"].isin(["PM2.5", "PM10"])]
    d["t"] = pd.to_datetime(d["date"], format="%Y%m%d") + pd.to_timedelta(d["hour"], unit="h")
    out = pd.DataFrame(index=sorted(d["t"].unique()))
    for grp, cities in dataset.CITY_GROUPS.items():
        for pol in ("PM2.5", "PM10"):
            sub = d[d["type"] == pol].set_index("t")
            cols = [c for c in cities if c in sub.columns]
            out[f"c_{grp}_{pol.replace('.', '')}"] = sub[cols].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    return out


def main():
    hist = dataset.build()
    cols = [c for c in dataset.feature_sets(hist)["forecastable"] if c != "year_frac"] + ["level365"]
    mw, mr, cols_r = fit_deploy_models(hist, cols)
    f = fetch_forecast()
    frame = to_model_frame(f)
    frame["level365"] = hist["level365"].dropna().iloc[-1]
    X = dataset.engineer(frame); X["level365"] = frame["level365"]
    w = pd.Series(mw.predict(X[cols], num_iteration=mw.best_iteration), index=X.index)     # log scale
    obs = recent_pm25(); cities = recent_cities()
    now = obs.index.max()
    # residual features as of the last observed hour
    r = np.log1p(obs).reindex(w.index) - w
    r_last, r_m6, r_m24 = r[now], r.loc[:now].tail(6).mean(), r.loc[:now].tail(24).mean()
    fut = w.index[w.index > now]
    F = pd.DataFrame(index=fut)
    F["lead"] = ((fut - now) / pd.Timedelta(hours=1)).astype(int)
    F["r_last"], F["r_last_m6"], F["r_last_m24"] = r_last, r_m6, r_m24
    F["pm25_last"] = np.log1p(obs[now]); F["w_last"] = w[now]; F["w_now"] = w[fut]
    c_now = cities.loc[:now].iloc[-1] if cities is not None and len(cities.loc[:now]) else None
    for c in train_lead.CITY:
        F[c + "_last"] = np.log1p(c_now[c]) if c_now is not None and c in c_now and not np.isnan(c_now[c]) else np.nan
    F["south_grad_last"] = F["c_south_PM25_last"] - F["pm25_last"]; F["nw_grad_last"] = F["c_northwest_PM25_last"] - F["pm25_last"]
    vn = X["e_v_north100"]; pr = X["e_precipitation"]
    F["vn100_mean_window"] = [vn.loc[now:t].iloc[1:].mean() for t in fut]
    F["precip_window"] = [pr.loc[now:t].iloc[1:].sum() for t in fut]
    F["hour_issue"] = now.hour
    corr = pd.Series(mr.predict(F[cols_r], num_iteration=mr.best_iteration), index=fut)
    pred_w = np.expm1(w); pred = pred_w.copy(); pred[fut] = np.expm1(w[fut] + corr)
    daily = pred[fut].resample("D").mean().round(1)
    out = {"issued": str(pd.Timestamp.now().floor("min")), "last_obs": str(now), "last_obs_value": float(obs[now]),
           "hours": [str(t) for t in w.index], "weather_model": pred_w.round(1).tolist(), "forecast": pred.round(1).tolist(),
           "observed": [None if t not in obs.index or np.isnan(obs[t]) else float(obs[t]) for t in w.index],
           "upwind_now": {k: (None if v is None or np.isnan(v) else float(v)) for k, v in (c_now.items() if c_now is not None else [])},
           "daily": {str(k.date()): float(v) for k, v in daily.items()},
           "weather": {c: f[c].round(2).tolist() for c in ("temperature_2m", "precipitation", "wind_speed_10m", "wind_direction_10m", "wind_speed_100m", "wind_direction_100m", "boundary_layer_height", "relative_humidity_2m")}}
    json.dump(out, open(OUT / "forecast.json", "w"))
    print(f"issued {out['issued']}  last observed {now} = {obs[now]:.0f} ug/m3  (weather model said {pred_w[now]:.0f}; south group now {out['upwind_now'].get('c_south_PM25', float('nan')):.0f}, north-west {out['upwind_now'].get('c_northwest_PM25', float('nan')):.0f})")
    print("daily mean outlook (ug/m3):")
    for k, v in daily.items(): print(f"  {k.date()} {k.day_name()[:3]}  {v:5.1f}   " + "#" * int(v / 3))
    past = pred_w[pred_w.index <= now].reindex(obs.index).dropna()
    if len(past) > 24:
        from sklearn.metrics import r2_score
        print(f"weather model over the last {len(past)} h vs observed: r2_log {r2_score(np.log1p(obs[past.index]), np.log1p(past)):.2f}  mae {np.abs(obs[past.index]-past).mean():.1f}")


if __name__ == "__main__":
    main()
