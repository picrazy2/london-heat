"""Hourly city-level pollutants for the cities around Beijing, from the same
quotsoft mirror of the CNEMC publication the site reads. One 440 KB file per
day for the whole country; only a ring of cities and six pollutants are kept.

Upwind PM2.5 is the transport signal (what the south wind is carrying), upwind
PM10 the dust signal (what the north wind is carrying in spring).
"""
import io, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
import pandas as pd, urllib.request

CITIES = ["北京", "天津", "石家庄", "唐山", "保定", "张家口", "承德", "廊坊", "沧州", "衡水", "邢台", "邯郸",
          "秦皇岛", "太原", "呼和浩特", "包头", "鄂尔多斯", "乌兰察布", "锡林郭勒盟", "济南", "沈阳"]
TYPES = ["PM2.5", "PM10", "SO2", "NO2", "O3", "CO"]
OUT = Path(__file__).parent / "data" / "cities"
OUT.mkdir(exist_ok=True)
URL = "https://quotsoft.net/air/data/china_cities_{ymd}.csv"

def one(d):
    ymd = d.strftime("%Y%m%d"); f = OUT / f"{ymd}.csv"
    if f.exists(): return ymd, "cached"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(URL.format(ymd=ymd), timeout=120) as r: raw = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404: f.write_text(""); return ymd, "404"
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    else:
        return ymd, "fail"
    try:
        df = pd.read_csv(io.BytesIO(raw))
        keep = [c for c in CITIES if c in df.columns]
        df = df[df["type"].isin(TYPES)][["date", "hour", "type"] + keep]
        df.to_csv(f, index=False)
        return ymd, f"ok {len(keep)}"
    except Exception as e:
        f.write_text(""); return ymd, f"parse-fail {e}"

days = [date(2013, 12, 6) + timedelta(i) for i in range((date(2026, 9, 14) - date(2013, 12, 6)).days)]
todo = [d for d in days if not (OUT / f"{d:%Y%m%d}.csv").exists()]
print(len(todo), "days to fetch", file=sys.stderr)
n = 0
with ThreadPoolExecutor(8) as ex:
    for fut in as_completed([ex.submit(one, d) for d in todo]):
        ymd, st = fut.result(); n += 1
        if n % 100 == 0 or st.startswith(("fail", "parse")): print(n, ymd, st, file=sys.stderr, flush=True)
print("done", file=sys.stderr)
