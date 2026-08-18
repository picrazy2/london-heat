"""Beijing PM2.5, from the city's own monitoring network.

Two endpoints, one network. Both are keyless.

  history  quotsoft.net mirrors the CNEMC hourly publication as one small CSV
           per day per city, 35 Beijing stations wide, back to 2013-12. The
           build caches the whole thing as a single hourly city-mean series, so
           a daily refresh fetches only the last few days.

  live     air.cnemc.cn:18007 is the National Environmental Monitoring Centre's
           own real-time feed. It carries station coordinates, which the archive
           does not, so it is what the map is drawn from.

Two candidate sources were tried and rejected. Copernicus CAMS, via Open-Meteo,
is keyless and convenient but models Beijing's annual mean at ~82 ug/m3 against
a measured ~30 — a factor of 2.7, which would have made every number on the page
wrong. The WAQI dataset publishes only US-EPA index values, not concentrations,
which would have made the scale toggle impossible: you cannot re-derive China's
index from America's answer without the number both were computed from.
"""
import csv
import io
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from .fetch import get_text, maybe

DAY_CSV = "https://quotsoft.net/air/data/beijing_all_{ymd}.csv"
LIVE = "https://air.cnemc.cn:18007/CityData/GetAQIDataPublishLive?cityName=%E5%8C%97%E4%BA%AC%E5%B8%82"

# The archive starts here; earlier dates 404. Beijing began publishing PM2.5
# hourly in 2013, in the middle of the winter that made it an international
# story, so the record opens on almost the worst air it has ever measured.
FIRST_DAY = date(2013, 12, 6)

# Two of the columns are not city air: Dingling is the designated clean-air
# control site up in the hills at the Ming tombs, and the other is a regional
# background site. The published city average leaves both out and so does this.
EXCLUDE = {"定陵(对照点)", "京东南区域点"}


def _parse_day(text):
    """One day's CSV -> {hour: (city_mean_pm25, n_stations)} for that day."""
    rdr = csv.reader(io.StringIO(text))
    try:
        header = next(rdr)
    except StopIteration:
        return {}
    cols = header[3:]
    keep = [i for i, name in enumerate(cols) if name not in EXCLUDE]
    out = {}
    for row in rdr:
        if len(row) < 4 or row[2] != "PM2.5":
            continue
        vals = row[3:]
        got = []
        for i in keep:
            if i < len(vals) and vals[i].strip():
                try:
                    v = float(vals[i])
                except ValueError:
                    continue
                # The feed uses out-of-range sentinels for a station that is
                # down; a real hourly PM2.5 above 1500 has never been measured.
                if 0 <= v <= 1500:
                    got.append(v)
        if len(got) >= 5:                      # a city mean needs a city
            try:
                hr = int(row[1])
            except ValueError:
                continue
            if 0 <= hr <= 23:
                out[hr] = (round(sum(got) / len(got), 1), len(got))
    return out


def fetch_day(d):
    """Hourly city-mean PM2.5 for one date, or None if unavailable."""
    raw = maybe(DAY_CSV.format(ymd=d.strftime("%Y%m%d")), timeout=60)
    if raw is None:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gbk", "replace")
    if "<html" in text[:200].lower():
        return None
    return _parse_day(text)


# ── the cached hourly series ------------------------------------------------
# One row per day, 24 hourly city means. Blank means the network published
# nothing usable for that hour, which happens and must stay visible rather than
# being interpolated away.
HEADER = ["date"] + [f"h{h}" for h in range(24)]


def load_hourly(path):
    """-> {date_str 'YYYYMMDD': [24 floats or None]}"""
    out = {}
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                d = row["date"]
                out[d] = [float(row[f"h{h}"]) if row.get(f"h{h}") else None for h in range(24)]
    except FileNotFoundError:
        pass
    return out


def save_hourly(path, data):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for d in sorted(data):
            vals = data[d]
            w.writerow([d] + ["" if v is None else f"{v:g}" for v in vals])


def refresh(path, days_back=10, full=False, today=None):
    """Bring the cached hourly series up to date.

    `days_back` re-fetches a short trailing window every run rather than only
    the missing days: the network back-fills late observations, and a day first
    seen at 15/24 hours should not be frozen that way for ever.
    """
    data = load_hourly(path)
    today = today or date.today()
    if full or not data:
        start = FIRST_DAY
    else:
        last = max(data)
        start = date(int(last[:4]), int(last[4:6]), int(last[6:8])) - timedelta(days=days_back)
        start = max(start, FIRST_DAY)

    wanted = []
    d = start
    while d <= today:
        wanted.append(d)
        d += timedelta(days=1)

    # One file per day means a full backfill is ~4,600 requests, which is twenty
    # minutes done one at a time and about two done eight at a time. Eight is
    # chosen to be unremarkable to a small mirror that is doing this for free,
    # not to be as fast as possible.
    n_new = n_fail = 0
    workers = 8 if len(wanted) > 30 else 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_day, day): day for day in wanted}
        for done, fut in enumerate(as_completed(futures), 1):
            day = futures[fut]
            try:
                hours = fut.result()
            except Exception:                            # noqa: BLE001
                hours = None
            if hours:
                data[day.strftime("%Y%m%d")] = [hours.get(h, (None,))[0] for h in range(24)]
                n_new += 1
            else:
                n_fail += 1
            if len(wanted) > 400 and done % 500 == 0:
                print(f"    PM2.5 backfill {done}/{len(wanted)} days ...", flush=True)
                save_hourly(path, data)      # checkpoint: a long backfill is resumable
    save_hourly(path, data)
    print(f"  PM2.5: {n_new} days updated, {n_fail} unavailable; series now "
          f"{min(data)}..{max(data)} ({len(data)} days)")
    return data


# ── the live feed -----------------------------------------------------------
def live_stations():
    """Current hour, per station, with coordinates. None if the feed is down.

    The same normalisation runs in the Cloudflare function that serves /api/live;
    this copy exists so the build can cache a station table (names and positions
    change rarely) and the map still draws if the feed is unreachable at runtime.
    """
    try:
        raw = get_text(LIVE, timeout=45)
    except Exception:                                  # noqa: BLE001
        return None
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return None
    out = []
    for r in rows:
        try:
            lat, lon = float(r["Latitude"]), float(r["Longitude"])
        except (KeyError, TypeError, ValueError):
            continue

        def num(key):
            v = r.get(key)
            if v in (None, "", "NA", "—", "-"):
                return None
            try:
                return float(v)
            except ValueError:
                return None

        out.append({
            "code": r.get("StationCode"), "name": r.get("PositionName"),
            "lat": lat, "lon": lon,
            "pm25": num("PM2_5"), "pm25_24h": num("PM2_5_24h"),
            "pm10": num("PM10"), "o3": num("O3_8h"), "no2": num("NO2"),
            "so2": num("SO2"), "co": num("CO"), "aqi_cn": num("AQI"),
            "time": r.get("TimePoint"),
        })
    return out or None


def daily_stats(hourly):
    """Per-day summary from the hourly series.

    `mean` is the 24-hour mean, which is the averaging period both AQI scales
    are defined on — an index computed from an hourly spike is not comparable
    to a published daily figure, and both scales say so.
    """
    out = {}
    for d, vals in hourly.items():
        got = [v for v in vals if v is not None]
        if len(got) < 18:              # both standards want a mostly-complete day
            continue
        out[d] = {
            "mean": round(sum(got) / len(got), 1),
            "max": round(max(got), 1),
            "min": round(min(got), 1),
            "hours": len(got),
        }
    return out


def diurnal(hourly, months=None):
    """Mean PM2.5 by hour of day, optionally restricted to a set of months."""
    acc = defaultdict(list)
    for d, vals in hourly.items():
        if months and int(d[4:6]) not in months:
            continue
        for h, v in enumerate(vals):
            if v is not None:
                acc[h].append(v)
    return [round(sum(acc[h]) / len(acc[h]), 1) if acc[h] else None for h in range(24)]


def diurnal_relative(hourly, months=None):
    """Each hour as a percentage above or below its own day's mean.

    The absolute profile is nearly flat, and truthfully so: the difference
    between a clean day and a filthy one is many times the difference between
    3am and 3pm, so averaging raw concentrations by hour buries the daily cycle
    under the between-day variance. Normalising each day by itself first leaves
    only the shape of a day, which is the thing the chart is asking about.
    """
    acc = defaultdict(list)
    for d, vals in hourly.items():
        if months and int(d[4:6]) not in months:
            continue
        got = [v for v in vals if v is not None]
        # A day too clean to divide by, or too gappy, would produce enormous
        # ratios from rounding noise rather than from anything real.
        if len(got) < 20:
            continue
        mean = sum(got) / len(got)
        if mean < 5:
            continue
        for h, v in enumerate(vals):
            if v is not None:
                acc[h].append((v / mean - 1) * 100)
    return [round(sum(acc[h]) / len(acc[h]), 1) if acc[h] else None for h in range(24)]
