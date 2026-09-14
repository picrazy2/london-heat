"""Pull the full ZBAA METAR record from IEM with every field the model wants.

The site build only caches temperature; this pulls wind, humidity, precipitation,
pressure, visibility, sky cover and present-weather codes as well, in Beijing
local time so it joins the CNEMC hourly series without a timezone shuffle.
"""
import sys
import urllib.request
from pathlib import Path

FIELDS = "tmpc,dwpc,relh,drct,sknt,gust,p01i,alti,mslp,vsby,skyc1,skyl1,wxcodes"
URL = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=ZBAA"
       f"&data={FIELDS}&year1=2013&month1=11&day1=1&year2=2026&month2=12&day2=31"
       "&tz=Asia%2FShanghai&format=onlycomma&latlon=no&missing=M&trace=T&direct=no&report_type=3")

out = Path(__file__).parent / "data" / "zbaa_metar_full.csv"
print("fetching", URL, file=sys.stderr)
with urllib.request.urlopen(URL, timeout=900) as r:
    out.write_bytes(r.read())
print("wrote", out, out.stat().st_size, "bytes")
