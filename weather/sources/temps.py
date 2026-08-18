"""Daily maximum and minimum temperature, from three archives.

Each city ends up with the same shape — two dicts keyed 'YYYYMMDD' -> degrees C
— but gets there differently, because the two station records have failed in
different ways:

  London  ECA&D (KNMI) blended daily series for Heathrow, which is the Met
          Office's own figure and is authoritative but lags weeks to months.
          METAR from the airport tops up the tail.

  Beijing GHCN-Daily station CHM00054511 (Capital Airport) is complete and
          official from 1951 to 2012, then falls apart: 2013-2019 is almost
          entirely absent and NOAA stopped receiving the station altogether in
          August 2025. METAR from the same airport, via Iowa, is unbroken from
          1973 to this hour, so it fills every gap GHCN leaves and carries the
          record forward. The stitch is per-day, not just at the tail, and the
          page says so.

METAR-derived daily extremes sit slightly inside the official ones: sampling at
fixed times misses a brief afternoon peak. At Heathrow that is a few tenths on
the hottest days. At Beijing the METAR reports whole degrees, so it also
quantises. Both are stated on the page rather than silently corrected.
"""
import csv
import io
import os
import struct
import zlib
from collections import defaultdict
from datetime import date, timedelta

from .fetch import get, get_text

# ── ECA&D (KNMI) ------------------------------------------------------------
ECAD_BASE = "https://knmi-ecad-assets-prd.s3.amazonaws.com/download/"


def load_ecad(path):
    """Parse a cached ECA&D station file -> {'YYYYMMDD': degC}."""
    out = {}
    with open(path, encoding="latin1") as f:
        for line in f:
            p = [x.strip() for x in line.split(",")]
            if len(p) != 5:
                continue
            _, _, dt, val, q = p
            if not (dt.isdigit() and len(dt) == 8):
                continue
            v, qq = int(val), int(q)
            if qq == 9 or v == -9999:
                continue
            out[dt] = v / 10.0
    return out


def refresh_ecad(targets):
    """Re-extract station files from KNMI's bulk zips using HTTP range requests.

    The archives are hundreds of megabytes and hold thousands of stations; the
    central directory is at the end, so reading the tail, then one member, pulls
    a few kilobytes instead of the whole thing.
    """
    def rng(url, a, b):
        return get(url, headers={"Range": f"bytes={a}-{b}"}, timeout=180)

    def size(url):
        import urllib.request
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "weather.akguo.com"})
        return int(urllib.request.urlopen(req, timeout=60).headers["Content-Length"])

    def extract(url, member, out_path):
        n = size(url)
        tail = rng(url, max(0, n - 200000), n - 1)
        i = tail.rfind(b"PK\x05\x06")
        cs = struct.unpack("<I", tail[i + 12:i + 16])[0]
        co = struct.unpack("<I", tail[i + 16:i + 20])[0]
        cd = rng(url, co, co + cs - 1)
        pos = 0
        while pos < len(cd):
            if cd[pos:pos + 4] != b"PK\x01\x02":
                break
            meth = struct.unpack("<H", cd[pos + 10:pos + 12])[0]
            csz = struct.unpack("<I", cd[pos + 20:pos + 24])[0]
            nl = struct.unpack("<H", cd[pos + 28:pos + 30])[0]
            el = struct.unpack("<H", cd[pos + 30:pos + 32])[0]
            cl = struct.unpack("<H", cd[pos + 32:pos + 34])[0]
            lho = struct.unpack("<I", cd[pos + 42:pos + 46])[0]
            name = cd[pos + 46:pos + 46 + nl].decode("latin1")
            if name.endswith(member):
                lh = rng(url, lho, lho + 29)
                lnl = struct.unpack("<H", lh[26:28])[0]
                lel = struct.unpack("<H", lh[28:30])[0]
                off = lho + 30 + lnl + lel
                raw = rng(url, off, off + csz - 1)
                with open(out_path, "wb") as f:
                    f.write(zlib.decompress(raw, -15) if meth == 8 else raw)
                return True
            pos += 46 + nl + el + cl
        raise SystemExit(f"ECA&D: {member} not found in {url}")

    for zip_name, member, out_path in targets:
        print(f"  ECA&D: extracting {member}")
        extract(ECAD_BASE + zip_name, member, out_path)


# ── GHCN-Daily (NOAA) -------------------------------------------------------
GHCN_STATION = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station/{}.csv.gz"


def refresh_ghcn(station, tx_path, tn_path):
    """Pull one GHCN-Daily station and write TMAX/TMIN as 'YYYYMMDD,value' files.

    Only quality-flagged-clean rows are kept: column 5 is the QFLAG, and any
    non-blank value there means GHCN's own checks rejected the observation.
    """
    print(f"  GHCN: downloading {station}")
    raw = get(GHCN_STATION.format(station), timeout=300, gunzip=True)
    tx, tn = {}, {}
    for row in csv.reader(io.StringIO(raw.decode("latin1"))):
        if len(row) < 6:
            continue
        _, dt, elem, val, _mflag, qflag = row[0], row[1], row[2], row[3], row[4], row[5]
        if elem not in ("TMAX", "TMIN") or qflag.strip():
            continue
        if not (dt.isdigit() and len(dt) == 8):
            continue
        try:
            v = int(val) / 10.0
        except ValueError:
            continue
        if v < -80 or v > 60:
            continue
        (tx if elem == "TMAX" else tn)[dt] = v
    for path, data in ((tx_path, tx), (tn_path, tn)):
        with open(path, "w") as f:
            for k in sorted(data):
                f.write(f"{k},{data[k]:.1f}\n")
    print(f"  GHCN: {len(tx)} TMAX, {len(tn)} TMIN through {max(tx) if tx else 'n/a'}")


def load_pairs(path):
    """Parse a 'YYYYMMDD,value' file -> {'YYYYMMDD': float}."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                k, _, v = line.strip().partition(",")
                if len(k) == 8 and v:
                    out[k] = float(v)
    except FileNotFoundError:
        pass
    return out


# ── METAR (Iowa Environmental Mesonet) --------------------------------------
IEM = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station={st}"
       "&data=tmpc&year1={y1}&month1={m1}&day1={d1}&year2={y2}&month2={m2}&day2={d2}"
       "&tz={tz}&format=onlycomma&latlon=no&missing=M")


def metar_daily(station, tz, start, end_excl, cache_path=None, offline=False):
    """Daily max/min from METAR between `start` and `end_excl` (both date objects).

    Excluding the in-progress day is deliberate and matters: a day's minimum
    lands near dawn but its maximum lands mid-afternoon, so a partial day always
    has a usable minimum and a too-low maximum. Counting it would quietly drop
    hot days while keeping warm nights.

    `cache_path` keeps the raw download so `offline=True` can rebuild the site
    from it. Beijing's pull is fifty years wide and takes minutes; iterating on
    the page design should not re-download it every time.
    """
    if offline and cache_path and os.path.exists(cache_path):
        print(f"  METAR {station}: using cached {os.path.basename(cache_path)}")
        with open(cache_path) as f:
            raw = f.read()
    else:
        url = IEM.format(st=station, tz=tz.replace("/", "%2F"),
                         y1=start.year, m1=start.month, d1=start.day,
                         y2=end_excl.year + 1, m2=1, d2=1)
        print(f"  METAR {station}: from {start} ...")
        raw = get_text(url, timeout=600)
        if cache_path:
            with open(cache_path, "w") as f:
                f.write(raw)
    mx, mn, n = defaultdict(lambda: -99.0), defaultdict(lambda: 99.0), defaultdict(int)
    end_key = end_excl.strftime("%Y%m%d")
    start_key = start.strftime("%Y%m%d")
    for r in csv.DictReader(io.StringIO(raw)):
        v = r.get("tmpc")
        if v in ("M", "", None):
            continue
        try:
            v = float(v)
        except ValueError:
            continue
        if v < -60 or v > 60:
            continue
        k = r["valid"][:10].replace("-", "")
        if k < start_key or k >= end_key:
            continue
        mx[k] = max(mx[k], v)
        mn[k] = min(mn[k], v)
        n[k] += 1
    # A day carried by one or two observations is not a daily extreme. Six is a
    # low bar that still admits the 3-hourly era (eight a day) and rejects the
    # ragged days at the edge of an outage.
    ok = {k for k in mx if n[k] >= 6}
    return ({k: round(mx[k], 1) for k in ok}, {k: round(mn[k], 1) for k in ok})


# ── stitching ---------------------------------------------------------------
def stitch(base, fill):
    """`base` wins where it has a value; `fill` supplies every other day.

    Returns the merged dict plus the set of dates that came from `fill`, so the
    page can be honest about which parts of the record are the official figure
    and which are the airport's own reports.
    """
    out = dict(base)
    filled = set()
    for k, v in fill.items():
        if k not in out:
            out[k] = v
            filled.add(k)
    return out, filled


def day_after(ymd):
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    return date(y, m, d) + timedelta(days=1)
