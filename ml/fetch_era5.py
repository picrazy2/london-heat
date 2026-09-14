"""ERA5 reanalysis hourly for central Beijing via Open-Meteo's archive API (keyless).

The METAR record has no precipitation amounts and nothing about the vertical
structure of the atmosphere. ERA5 supplies hourly precipitation in mm and the
boundary-layer height, which controls how much air the city's emissions are
diluted into and is the strongest meteorological driver of PM2.5 there is.
"""
import json, sys, time, urllib.request
from pathlib import Path
import pandas as pd

LAT, LON = 39.9042, 116.4074
VARS = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "precipitation",
        "rain", "snowfall", "pressure_msl", "surface_pressure", "cloud_cover",
        "cloud_cover_low", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
        "wind_speed_100m", "wind_direction_100m", "boundary_layer_height",
        "shortwave_radiation", "et0_fao_evapotranspiration", "vapour_pressure_deficit",
        "soil_moisture_0_to_7cm", "soil_temperature_0_to_7cm"]
out = Path(__file__).parent / "data" / "era5_beijing_hourly_pinned.csv"
frames = []
for y in range(2013, 2027):
    start, end = f"{y}-01-01", (f"{y}-12-31" if y < 2026 else "2026-09-13")
    if y == 2013: start = "2013-11-01"
    url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={LAT}&longitude={LON}"
           f"&start_date={start}&end_date={end}&hourly={','.join(VARS)}&timezone=Asia%2FShanghai"
           "&wind_speed_unit=ms&models=era5")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                j = json.load(r)
            break
        except Exception as e:
            print(y, "retry", attempt, e, file=sys.stderr); time.sleep(10 * (attempt + 1))
    df = pd.DataFrame(j["hourly"])
    print(y, len(df), file=sys.stderr)
    frames.append(df)
    time.sleep(1)
pd.concat(frames).to_csv(out, index=False)
print("wrote", out)
