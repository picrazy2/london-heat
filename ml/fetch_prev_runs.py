"""Archived forecasts for Beijing, as issued 1..7 days before each hour, from
Open-Meteo's previous-runs API. This is what lets forecast skill be measured
against what the forecast actually said, rather than against reanalysis."""
import json, sys, time, urllib.request
from pathlib import Path
import pandas as pd
VARS = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation", "rain", "snowfall", "pressure_msl",
        "surface_pressure", "cloud_cover", "cloud_cover_low", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
        "wind_speed_100m", "wind_direction_100m", "boundary_layer_height", "shortwave_radiation", "vapour_pressure_deficit"]
out = Path(__file__).parent / "data" / "prev_runs.csv"
frames = []
for d in range(1, 8):
    hv = ",".join(f"{v}_previous_day{d}" for v in VARS)
    url = (f"https://previous-runs-api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074&start_date=2024-01-01"
           f"&end_date=2026-09-13&hourly={hv}&timezone=Asia%2FShanghai&wind_speed_unit=ms")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=300) as r: j = json.load(r)
            break
        except Exception as e:
            print(d, "retry", attempt, e, file=sys.stderr); time.sleep(5 * (attempt + 1))
    f = pd.DataFrame(j["hourly"]).set_index("time"); f.columns = [c.replace(f"_previous_day{d}", f"|{d}") for c in f.columns]
    frames.append(f); print(d, f.shape, f.isna().mean().round(3).max(), file=sys.stderr, flush=True)
pd.concat(frames, axis=1).to_csv(out); print("wrote", out)
