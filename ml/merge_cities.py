"""Stack the per-day city files into one hourly table: columns are city|pollutant."""
import pandas as pd
from pathlib import Path
D = Path(__file__).parent / "data"
frames = []
for f in sorted((D / "cities").glob("*.csv")):
    if f.stat().st_size == 0: continue
    try:
        d = pd.read_csv(f, dtype={"date": str})
    except Exception:
        continue
    if d.empty: continue
    long = d.melt(id_vars=["date", "hour", "type"], var_name="city", value_name="v")
    long["t"] = pd.to_datetime(long["date"], format="%Y%m%d") + pd.to_timedelta(long["hour"], unit="h")
    long["k"] = long["city"] + "|" + long["type"]
    frames.append(long.pivot_table(index="t", columns="k", values="v", aggfunc="first"))
w = pd.concat(frames).sort_index()
w = w[~w.index.duplicated()]
w.to_csv(D / "cities_hourly.csv")
print(w.shape, w.index.min(), w.index.max())
print("coverage:", w.notna().mean().round(2).groupby(lambda k: k.split("|")[1]).mean().round(2).to_dict())
print(w.filter(like="|PM2.5").mean().round(0).sort_values().to_dict())
