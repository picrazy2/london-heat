"""Hourly PM2.5 modelling table for Beijing: CNEMC city mean joined to ZBAA METAR
and (when present) ERA5 reanalysis, with the time and history features the
models are fed.

Everything is in Beijing local time. One row per hour from Dec 2013.
"""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
PM25 = HERE.parent / "data" / "beijing_pm25_hourly.csv"
METAR = HERE / "data" / "zbaa_metar_full.csv"
ERA5 = HERE / "data" / "era5_beijing_hourly_pinned.csv"
IGRA = HERE / "data" / "igra_beijing.csv"
CITIES = HERE / "data" / "cities_hourly.csv"

# Chinese New Year's Day. The fireworks spike at midnight is the single largest
# non-meteorological PM2.5 event of the year, and a model with no idea when it
# happens will blame the weather for it.
CNY = {2014: date(2014, 1, 31), 2015: date(2015, 2, 19), 2016: date(2016, 2, 8),
       2017: date(2017, 1, 28), 2018: date(2018, 2, 16), 2019: date(2019, 2, 5),
       2020: date(2020, 1, 25), 2021: date(2021, 2, 12), 2022: date(2022, 2, 1),
       2023: date(2023, 1, 22), 2024: date(2024, 2, 10), 2025: date(2025, 1, 29),
       2026: date(2026, 2, 17)}

# Present-weather codes -> precipitation intensity (0 none, 1 light, 2 moderate,
# 3 heavy) and a separate dust flag. Haze (HZ), mist (BR), smoke (FU) and fog are
# deliberately not features: they are what PM2.5 looks like, not what causes it.
PRECIP = ("RA", "SN", "DZ", "SG", "PL", "GR", "GS", "SHRA", "SHSN", "TSRA", "RASN", "SNRA")
DUST = ("DU", "SA", "BLDU", "BLSA", "DS", "SS", "PO")


def _wx(codes):
    if not isinstance(codes, str):
        return 0, 0, 0, 0
    precip = rain = snow = dust = 0
    for c in codes.split():
        inten = 2
        if c.startswith("+"): inten, c = 3, c[1:]
        elif c.startswith("-"): inten, c = 1, c[1:]
        if c.startswith("VC"):          # in the vicinity, not at the station
            continue
        if any(p in c for p in ("RA", "DZ", "TSRA")): rain = 1
        if any(p in c for p in ("SN", "SG", "PL", "GS", "GR")): snow = 1
        if any(p in c for p in PRECIP): precip = max(precip, inten)
        if any(d in c for d in DUST): dust = 1
    return precip, rain, snow, dust


def load_pm25():
    df = pd.read_csv(PM25, dtype={"date": str})
    long = df.melt(id_vars="date", var_name="h", value_name="pm25")
    long["h"] = long["h"].str[1:].astype(int)
    long["t"] = pd.to_datetime(long["date"], format="%Y%m%d") + pd.to_timedelta(long["h"], unit="h")
    return long.set_index("t")["pm25"].sort_index()


def load_metar():
    m = pd.read_csv(METAR, na_values=["M"], keep_default_na=False, low_memory=False)
    m["t"] = pd.to_datetime(m["valid"]).dt.floor("h")
    m = m.drop_duplicates("t", keep="last").set_index("t")
    # Calm/variable wind arrives as a missing direction with a (usually small)
    # speed; treat as zero vector rather than dropping the hour.
    spd = m["sknt"].fillna(0) * 0.514444                      # knots -> m/s
    ang = np.deg2rad(m["drct"].fillna(0))
    calm = m["drct"].isna() | (spd == 0)
    # Meteorological convention: direction is where the wind blows FROM, so a
    # north wind (360) has v < 0. Flip so that `v_north` > 0 means a wind
    # arriving from the north, which is the sign that reads naturally here.
    out = pd.DataFrame(index=m.index)
    out["temp"] = m["tmpc"]
    out["dewpt"] = m["dwpc"]
    out["rh"] = m["relh"]
    out["wspd"] = spd
    out["wdir"] = m["drct"].where(~calm)
    out["u_east"] = np.where(calm, 0, -spd * np.sin(ang))     # positive = from the west... see below
    out["v_north"] = np.where(calm, 0, spd * np.cos(ang))     # positive = wind from the north
    out["u_east"] = -out["u_east"]                            # positive = wind from the east
    out["gust"] = m["gust"].fillna(0) * 0.514444
    out["pres"] = m["alti"] * 33.8639                          # inHg -> hPa
    wx = m["wxcodes"].map(_wx)
    out["precip_int"] = [w[0] for w in wx]
    out["rain"] = [w[1] for w in wx]
    out["snow"] = [w[2] for w in wx]
    out["dust"] = [w[3] for w in wx]
    sky = {"NSC": 0, "FEW": 1, "SCT": 2, "BKN": 3, "OVC": 4, "VV": 4}
    out["cloud"] = m["skyc1"].map(sky)         # NaN when not reported (most hours)
    out["cloud_reported"] = m["skyc1"].notna().astype(int)
    out["cloud"] = out["cloud"].fillna(0)
    return out


def load_era5():
    if not ERA5.exists():
        return None
    e = pd.read_csv(ERA5)
    e["t"] = pd.to_datetime(e["time"])
    e = e.drop(columns=["time"]).set_index("t").add_prefix("e_")
    ang = np.deg2rad(e["e_wind_direction_10m"])
    e["e_v_north"] = e["e_wind_speed_10m"] * np.cos(ang)
    e["e_u_east"] = e["e_wind_speed_10m"] * np.sin(ang)
    ang100 = np.deg2rad(e["e_wind_direction_100m"])
    e["e_v_north100"] = e["e_wind_speed_100m"] * np.cos(ang100)
    e["e_u_east100"] = e["e_wind_speed_100m"] * np.sin(ang100)
    e = e.drop(columns=["e_wind_direction_10m", "e_wind_direction_100m"])
    # Open-Meteo's ERA5 archive has no boundary-layer height for Jan-Jun 2024.
    e["e_blh_missing"] = e["e_boundary_layer_height"].isna().astype(int)
    return e


IGRA_COLS = ["inv925", "inv850", "inv_strength", "inv_base", "lapse_low", "ws_low", "ws925", "vn925", "ws850", "vn850", "ws700", "vn700"]


def load_igra():
    """Twice-daily sounding summaries, carried forward to each hour (latest available)."""
    if not IGRA.exists():
        return None
    g = pd.read_csv(IGRA, parse_dates=["t"]).set_index("t")[IGRA_COLS]
    g["inv_base"] = g["inv_base"].fillna(2000)     # no inversion found -> "very high"
    return g.add_prefix("s_")


# Upwind and neighbouring cities, grouped by the direction they lie in from
# Beijing. South is the Hebei plain (transport); north-west is the steppe (dust).
CITY_GROUPS = {"south": ["保定", "石家庄", "廊坊", "沧州", "衡水", "邢台", "邯郸"],
               "east": ["天津", "唐山", "秦皇岛"],
               "northwest": ["张家口", "呼和浩特", "乌兰察布", "包头", "锡林郭勒盟"],
               "north": ["承德"], "southwest": ["太原"]}


def load_cities():
    if not CITIES.exists():
        return None
    c = pd.read_csv(CITIES, parse_dates=["t"]).set_index("t")
    out = pd.DataFrame(index=c.index)
    for grp, cities in CITY_GROUPS.items():
        for pol in ("PM2.5", "PM10", "SO2", "NO2", "O3"):
            cols = [f"{city}|{pol}" for city in cities if f"{city}|{pol}" in c.columns]
            if cols:
                out[f"c_{grp}_{pol.replace('.', '')}"] = c[cols].mean(axis=1)
    return out


def add_time(df):
    t = df.index
    df["hour"] = t.hour
    df["dow"] = t.dayofweek
    df["month"] = t.month
    df["doy"] = t.dayofyear
    df["year_frac"] = t.year + (t.dayofyear - 1) / 365.25
    for name, val, per in (("hour", t.hour, 24), ("doy", t.dayofyear, 365.25), ("dow", t.dayofweek, 7)):
        df[f"{name}_sin"] = np.sin(2 * np.pi * val / per)
        df[f"{name}_cos"] = np.cos(2 * np.pi * val / per)
    df["weekend"] = (t.dayofweek >= 5).astype(int)
    # Hours relative to CNY midnight, clipped to a +-7 day window; 0 elsewhere.
    cny = pd.Series([pd.Timestamp(CNY.get(y, date(y, 2, 1))) for y in t.year], index=t)
    dh = (t - cny) / pd.Timedelta(hours=1)
    df["cny_window"] = ((dh >= -24 * 2) & (dh <= 24 * 7)).astype(int)
    df["cny_night"] = ((dh >= -6) & (dh <= 12)).astype(int)     # the fireworks hours
    return df


def add_history(df, cols_windows):
    """Rolling means/sums over the past N hours (inclusive of the current hour)."""
    for col, windows, how in cols_windows:
        for w in windows:
            r = df[col].rolling(w, min_periods=max(1, w // 2))
            df[f"{col}_{how}{w}"] = r.mean() if how == "m" else r.sum()
    return df


def build(with_era5=True, with_igra=True, with_cities=True):
    pm = load_pm25()
    met = load_metar()
    idx = pd.date_range(pm.index.min(), max(pm.index.max(), met.index.max()), freq="h")
    df = met.reindex(idx)
    # METAR is hourly with the occasional gap; short gaps are safe to bridge.
    df = df.interpolate(limit=3, limit_direction="forward")
    df["pm25"] = pm.reindex(idx)
    era = load_era5() if with_era5 else None
    if era is not None:
        df = df.join(era.reindex(idx))
    igra = load_igra() if with_igra else None
    if igra is not None:
        df = df.join(carry_soundings(igra, idx))
    cities = load_cities() if with_cities else None
    if cities is not None:
        df = df.join(cities.reindex(idx))
    return engineer(df)


def carry_soundings(igra, idx):
    """Twice-daily soundings -> hourly, each hour carrying the latest sounding (<= 18 h old)."""
    g = igra.reindex(idx.union(igra.index)).sort_index()
    age = pd.Series(np.where(g["s_inv925"].notna(), np.arange(len(g)), np.nan), index=g.index).ffill()
    pos = pd.Series(np.arange(len(g)), index=g.index)
    out = g.ffill(limit=18).reindex(idx)
    out["s_age"] = np.minimum((pos - age).reindex(idx).to_numpy(), 48)
    return out


def engineer(df):
    """Time, history and derived features on an hourly frame. Works on the
    historical table and on a forecast frame alike; columns that are absent
    (no METAR in a forecast, no cities) are simply skipped."""
    df = df.copy()
    for c in WEATHER_BASE + ["wdir"]:
        if c not in df: df[c] = np.nan
    if "pm25" not in df: df["pm25"] = np.nan
    df = add_time(df)
    hist = [("v_north", (3, 6, 12, 24, 48), "m"), ("u_east", (6, 24), "m"),
            ("wspd", (3, 6, 12, 24, 48), "m"), ("rh", (6, 24), "m"),
            ("temp", (24,), "m"), ("precip_int", (3, 6, 12, 24, 48), "s"),
            ("rain", (6, 24), "s"), ("snow", (6, 24), "s"), ("dust", (6, 24), "s")]
    if "s_inv925" in df:
        hist += [("s_inv925", (24,), "m"), ("s_vn850", (24,), "m"), ("s_vn925", (24,), "m")]
        if "s_ws_low" in df: hist += [("s_ws_low", (24,), "m")]
    hist += [(c, (6, 24), "m") for c in df.columns if c.startswith("c_") and c.endswith("PM25")]
    hist += [(c, (6, 24), "m") for c in df.columns if c.startswith("c_") and c.endswith("PM10")]
    if "e_precipitation" in df:
        hist += [("e_precipitation", (3, 6, 12, 24, 48, 72), "s"),
                 ("e_boundary_layer_height", (6, 24), "m"), ("e_v_north", (6, 12, 24, 48), "m"),
                 ("e_v_north100", (12, 24), "m"), ("e_wind_speed_10m", (12, 24, 48), "m"),
                 ("e_wind_speed_100m", (12, 24), "m"), ("e_relative_humidity_2m", (24,), "m"),
                 ("e_precip_flag", (6, 24), "s"), ("e_snow_flag", (6, 24), "s")]
        df["e_precip_flag"] = (df["e_precipitation"] > 0.1).astype(int)
        df["e_snow_flag"] = (df["e_snowfall"] > 0.05).astype(int)
    df = add_history(df, hist)
    df["temp_d24"] = df["temp"] - df["temp"].shift(24)
    df["pres_d3"] = df["pres"] - df["pres"].shift(3)
    df["pres_d24"] = df["pres"] - df["pres"].shift(24)
    df["dewpt_dep"] = df["temp"] - df["dewpt"]
    if "e_temperature_2m" in df:
        df["e_temp_d24"] = df["e_temperature_2m"] - df["e_temperature_2m"].shift(24)
        df["e_pres_d24"] = df["e_pressure_msl"] - df["e_pressure_msl"].shift(24)
    # Hours since the last "strong north wind" hour (>= 5 m/s from within 45deg
    # of north), capped at 96. A ventilation clock. Computed from METAR when
    # present, else from ERA5 10 m wind.
    if df["wdir"].notna().any():
        strong_n = (df["v_north"] >= 5 * np.cos(np.deg2rad(45))) & (df["wdir"].between(315, 360) | df["wdir"].between(0, 45))
    else:
        strong_n = (df["e_v_north"] >= 5 * np.cos(np.deg2rad(45))) & (df["e_v_north"] > np.abs(df["e_u_east"]))
    last = pd.Series(np.where(strong_n, np.arange(len(df)), np.nan), index=df.index).ffill()
    df["hrs_since_strong_n"] = np.minimum(np.arange(len(df)) - last, 96).fillna(96)
    df["strong_n_hours24"] = strong_n.astype(int).rolling(24, min_periods=1).sum()
    df["strong_n_hours48"] = strong_n.astype(int).rolling(48, min_periods=1).sum()
    if "e_v_north" in df:
        e_strong = (df["e_v_north"] >= 5 * np.cos(np.deg2rad(45))) & (df["e_v_north"] > np.abs(df["e_u_east"]))
        last = pd.Series(np.where(e_strong, np.arange(len(df)), np.nan), index=df.index).ffill()
        df["e_hrs_since_strong_n"] = np.minimum(np.arange(len(df)) - last, 96).fillna(96)
        df["e_strong_n_hours24"] = e_strong.astype(int).rolling(24, min_periods=1).sum()
    # Lagged PM2.5 for the autoregressive variant only. Never in the weather model.
    for lag in (1, 3, 6, 12, 24):
        df[f"pm25_lag{lag}"] = df["pm25"].shift(lag)
    df["pm25_m24_lag1"] = df["pm25"].shift(1).rolling(24, min_periods=12).mean()
    # The city's emissions baseline: mean log PM2.5 over the trailing year,
    # lagged a month so it carries none of the current weather regime. This is
    # the alternative to a raw year number, which a network will extrapolate.
    if "level365" not in df:
        df["level365"] = np.log1p(df["pm25"]).shift(24 * 30).rolling(24 * 365, min_periods=24 * 180).mean()
    return df.copy()


ERA5_BASE = ["e_temperature_2m", "e_relative_humidity_2m", "e_precipitation", "e_snowfall", "e_pressure_msl",
             "e_cloud_cover", "e_cloud_cover_low", "e_wind_speed_10m", "e_wind_gusts_10m", "e_wind_speed_100m",
             "e_boundary_layer_height", "e_shortwave_radiation", "e_vapour_pressure_deficit",
             "e_v_north", "e_u_east", "e_v_north100", "e_u_east100", "e_blh_missing"]
# METAR cloud fields are not used: a cloud group is only present when the
# report is not CAVOK, and CAVOK requires visibility >= 10 km, so "cloud was
# reported" is a haze detector in disguise. ERA5 cloud cover stands in.
WEATHER_BASE = ["temp", "dewpt", "rh", "wspd", "u_east", "v_north", "gust", "pres",
                "precip_int", "rain", "snow", "dust", "dewpt_dep"]
TIME = ["hour", "dow", "month", "doy", "year_frac", "hour_sin", "hour_cos", "doy_sin", "doy_cos",
        "dow_sin", "dow_cos", "weekend", "cny_window", "cny_night"]
AR = ["pm25_lag1", "pm25_lag3", "pm25_lag6", "pm25_lag12", "pm25_lag24", "pm25_m24_lag1"]


def feature_sets(df):
    hist = [c for c in df.columns if any(c.startswith(p + "_") and c[-1].isdigit() for p in
            ("v_north", "u_east", "wspd", "rh", "temp", "precip_int", "rain", "snow", "dust"))
            and c not in WEATHER_BASE and not c.startswith("pm25")]
    hist += [c for c in ("temp_d24", "pres_d3", "pres_d24", "hrs_since_strong_n", "strong_n_hours24", "strong_n_hours48")
             if c not in hist]
    era = [c for c in df.columns if c.startswith("e_")]
    snd = [c for c in df.columns if c.startswith("s_")]
    # Everything a weather forecast can supply: ERA5-style surface fields and
    # the pressure-level sounding features. No METAR point data, no upwind
    # pollution, no full-profile inversion detection.
    fc_snd = [c for c in snd if any(c.startswith("s_" + p) for p in ("inv925", "inv850", "vn925", "ws925", "vn850", "ws850", "vn700", "ws700"))]
    forecastable = [c for c in TIME] + [c for c in era if not any(k in c for k in ("soil", "et0"))] + fc_snd
    cit = [c for c in df.columns if c.startswith("c_")]
    cit_pm = [c for c in cit if "PM" in c]
    return {
        "metar_now": WEATHER_BASE + TIME,
        "metar_hist": WEATHER_BASE + TIME + hist,
        "metar_era5": WEATHER_BASE + TIME + hist + era,
        "plus_sonde": WEATHER_BASE + TIME + hist + era + snd,
        "plus_cities_pm": WEATHER_BASE + TIME + hist + era + snd + cit_pm,
        "plus_cities": WEATHER_BASE + TIME + hist + era + snd + cit,
        "metar_era5_ar": WEATHER_BASE + TIME + hist + era + AR,
        "forecastable": forecastable,
    }


if __name__ == "__main__":
    df = build()
    out = HERE / "data" / "hourly.parquet"
    df.to_parquet(out)
    print(df.shape, df.index.min(), df.index.max())
    print("pm25 coverage:", df.pm25.notna().mean().round(3))
    print(df[["pm25", "temp", "wspd", "v_north", "precip_int", "rain", "hrs_since_strong_n"]].describe().T)
    for k, v in feature_sets(df).items():
        print(k, len(v))
