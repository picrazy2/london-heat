#!/usr/bin/env python3
"""One-shot refresh: download latest Heathrow data, recompute every dataset,
and regenerate both artifact HTML files so they are current.

Usage:  python3 build_charts.py

- METAR (recent weeks) is re-downloaded every run from the Iowa Environmental
  Mesonet (keyless).  This is the part that changes daily.
- ECA&D official daily series is used from the cached files heathrow_tx.txt /
  heathrow_tn.txt (it updates only every few months). Pass --refresh-ecad to
  re-extract it from the KNMI bulk archive (slow, ~a few MB via range requests).
"""
import urllib.request, csv, json, re, os, sys, struct, zlib, calendar
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(BASE, f)
SITE = os.path.join(BASE, "public")          # what Cloudflare Pages serves
O = lambda f: os.path.join(SITE, f)
MABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

SITE_URL  = "https://weather.akguo.com"
SITE_NAME = "London Heat"

PAGES = [("/", "The warming record"), ("/year_explorer", "A year in temperature")]

META = {
    "/": ("London Heat — Heathrow's warming record",
          "Hot days and tropical nights at London Heathrow since 1960, counted from "
          "the airport's own thermometer. Updated daily."),
    "/year_explorer": ("London Heat — a year in temperature",
          "Every day of any year at London Heathrow, against its decade's typical "
          "shape. Daily maxima and minima since 1960."),
}

# A rising ramp, cool to hot: the chart's argument, at 16 pixels.
FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="13" fill="#16130f"/>
  <rect x="12" y="38" width="11" height="15" rx="2.5" fill="#4f97ec"/>
  <rect x="26.5" y="27" width="11" height="26" rx="2.5" fill="#f2824a"/>
  <rect x="41" y="14" width="11" height="39" rx="2.5" fill="#ec6a6a"/>
</svg>
"""

# ---------------- tiny PNG writer (zlib/struct are already imported) ----------------
def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

def write_png(path, w, h, buf):
    raw = b"".join(b"\x00" + bytes(buf[y*w*3:(y+1)*w*3]) for y in range(h))
    hdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", hdr)
                + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))

def _rgb(h): h=h.lstrip("#"); return tuple(int(h[i:i+2],16) for i in (0,2,4))
def _lerp(a, b, t): return tuple(round(a[i] + (b[i]-a[i])*t) for i in range(3))

def canvas(w, h, hexcol):
    return bytearray(bytes(_rgb(hexcol)) * (w*h))

def fill(buf, w, h, x0, y0, x1, y1, rgb):
    x0,y0 = max(0,int(x0)), max(0,int(y0)); x1,y1 = min(w,int(x1)), min(h,int(y1))
    px = bytes(rgb)
    for y in range(y0, y1):
        buf[(y*w+x0)*3:(y*w+x1)*3] = px * (x1-x0)

def vbar(buf, W, H, x0, x1, y0, y1, rgb, r=4, round_top=True):
    """Bar with a rounded data-end; the baseline end stays square."""
    x0,x1,y0,y1 = int(x0),int(x1),int(y0),int(y1)
    if y1<=y0: return
    r = min(r, (x1-x0)//2, y1-y0)
    for y in range(y0, y1):
        d = (y - y0) if round_top else (y1 - 1 - y)
        if d < r:
            inset = r - int((r*r - (r-1-d)**2) ** 0.5)
        else:
            inset = 0
        fill(buf, W, H, x0+inset, y, x1-inset, y+1, rgb)

def social_card(path, years, vals, partial_year):
    """1200x630 preview: hot days per year as a deviation from the 1961-90 normal.

    Plotting the deviation rather than the count lets colour carry the *sign* —
    a diverging encoding — instead of restating the bar's own length, which is
    what colouring by magnitude would do.
    """
    W,H = 1200,630
    buf = canvas(W, H, "#16130f")
    L,R,T,B = 80, 80, 80, 80
    pw, ph = W-L-R, H-T-B
    surface = _rgb("#16130f")
    cool, warm, neutral = _rgb("#4f97ec"), _rgb("#e0504f"), _rgb("#8f867a")

    i0, i1 = years.index(1961), years.index(1990)
    normal = sum(vals[i0:i1+1])/(i1-i0+1)
    dev = [v - normal for v in vals]
    up, dn = max(max(dev), 0.1), min(min(dev), -0.1)
    span = up - dn
    zero = T + (up/span)*ph               # y of the baseline

    n = len(vals); bw = pw/n
    for i, d in enumerate(dev):
        x0, x1 = L + i*bw + 1, L + (i+1)*bw - 1   # 2px surface gap between bars
        c = warm if d >= 0 else cool
        if years[i] == partial_year:               # part-year: hold it back
            c = _lerp(c, surface, 0.45)
        h = abs(d)/span * ph
        if d >= 0: vbar(buf, W, H, x0, x1, zero-h, zero, c, round_top=True)
        else:      vbar(buf, W, H, x0, x1, zero, zero+h, c, round_top=False)
    # the 1961-90 normal, drawn over the bars
    fill(buf, W, H, L-14, zero-1, L+pw+14, zero+1, neutral)
    write_png(path, W, H, buf)

NAV_CSS = """
  .sitenav { display:flex; gap:6px; margin:0 0 28px; flex-wrap:wrap; }
  .sitenav a {
    font-size:13.5px; font-weight:600; text-decoration:none; color:var(--muted);
    padding:7px 13px; border-radius:999px; border:1px solid transparent; line-height:1;
    transition:color .12s ease, background .12s ease, border-color .12s ease;
  }
  .sitenav a:hover { color:var(--ink); }
  .sitenav a[aria-current="page"] {
    color:var(--ink); background:var(--panel); border-color:var(--ring); box-shadow:var(--shadow);
  }
"""

def nav_html(here):
    links = "".join(
        f'    <a href="{href}"{" aria-current=\"page\"" if href==here else ""}>{label}</a>\n'
        for href, label in PAGES)
    return f'\n  <nav class="sitenav" aria-label="Pages">\n{links}  </nav>\n'

def esc(s): return (s.replace("&","&amp;").replace('"',"&quot;")
                     .replace("<","&lt;").replace(">","&gt;"))

ICONS = ('<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n'
         '<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
         '<meta name="theme-color" content="#faf8f5" media="(prefers-color-scheme: light)">\n'
         '<meta name="theme-color" content="#16130f" media="(prefers-color-scheme: dark)">\n')

def social_meta(here, stamp):
    title, desc = META[here]
    url = SITE_URL + ("" if here=="/" else here)
    img = f"{SITE_URL}/social.png?v={stamp}"   # ?v= busts scrapers' image caches
    t = [f'<meta name="description" content="{esc(desc)}">',
         f'<link rel="canonical" href="{esc(url)}">',
         '<meta property="og:type" content="website">',
         f'<meta property="og:site_name" content="{esc(SITE_NAME)}">',
         f'<meta property="og:title" content="{esc(title)}">',
         f'<meta property="og:description" content="{esc(desc)}">',
         f'<meta property="og:url" content="{esc(url)}">',
         f'<meta property="og:image" content="{esc(img)}">',
         '<meta property="og:image:width" content="1200">',
         '<meta property="og:image:height" content="630">',
         '<meta property="og:image:alt" content="Hot days per year at Heathrow, 1960 to '
         'today, as a deviation from the 1961-90 average: mostly below it early on, '
         'almost entirely above it since the 1990s">',
         '<meta name="twitter:card" content="summary_large_image">',
         f'<meta name="twitter:title" content="{esc(title)}">',
         f'<meta name="twitter:description" content="{esc(desc)}">',
         f'<meta name="twitter:image" content="{esc(img)}">']
    return "\n".join(t) + "\n"

def wrap(frag, here=None, stamp=""):
    """Templates are bare fragments (a <title>, a <style>, then content) because they
    began life as Claude artifacts, which supplied the document skeleton. Served as
    real files they need one: without a charset the °C signs mojibake, and without a
    viewport phones render at desktop width."""
    i = frag.find("</style>")
    if i == -1: head, body = "", frag
    else:       head, body = frag[:i] + NAV_CSS + "</style>", frag[i+8:]
    social = social_meta(here, stamp) if here in META else ""
    if here:
        marker = '<div class="wrap">'
        body = body.replace(marker, marker + nav_html(here), 1)
    return ('<!doctype html>\n<html lang="en">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'{ICONS}{social}{head}\n</head>\n<body>{body}</body>\n</html>\n')

def emit(name, text, here=None, stamp=""):
    with open(O(name), "w", encoding="utf-8") as f:
        f.write(wrap(text, here, stamp))

def doy(y,m,d): return (date(y,m,d) - date(y,1,1)).days + 1
def fmt_short(dstr):  # 'YYYY-MM-DD' or 'YYYYMMDD' -> '7 Jul'
    y,m,d = _ymd(dstr); return f"{d} {MABBR[m-1]}"
def fmt_long(dstr):   # -> '7 Jul 2026'
    y,m,d = _ymd(dstr); return f"{d} {MABBR[m-1]} {y}"
def _ymd(s):
    s=s.replace('-','')
    return int(s[:4]), int(s[4:6]), int(s[6:8])

# ---------------- ECA&D loaders ----------------
def load_eca(path):
    v={}
    with open(path, encoding="latin1") as f:
        for line in f:
            p=[x.strip() for x in line.split(",")]
            if len(p)!=5: continue
            _,_,dt,val,q=p
            if not (dt.isdigit() and len(dt)==8): continue
            vv,qq=int(val),int(q)
            if qq==9 or vv==-9999: continue
            v[dt]=vv/10.0
    return v

def refresh_ecad():
    """Re-extract Heathrow (STAID 1860) TX/TN from KNMI bulk zips via HTTP range."""
    def get(url,a,b):
        r=urllib.request.Request(url, headers={"Range":f"bytes={a}-{b}"})
        return urllib.request.urlopen(r).read()
    def total(url):
        return int(urllib.request.urlopen(urllib.request.Request(url,method="HEAD")).headers["Content-Length"])
    def extract(url,target,out):
        n=total(url); tail=get(url,max(0,n-200000),n-1)
        i=tail.rfind(b"PK\x05\x06")
        cs=struct.unpack("<I",tail[i+12:i+16])[0]; co=struct.unpack("<I",tail[i+16:i+20])[0]
        cd=get(url,co,co+cs-1); pos=0
        while pos<len(cd):
            if cd[pos:pos+4]!=b"PK\x01\x02": break
            meth=struct.unpack("<H",cd[pos+10:pos+12])[0]
            csz=struct.unpack("<I",cd[pos+20:pos+24])[0]
            nl=struct.unpack("<H",cd[pos+28:pos+30])[0]; el=struct.unpack("<H",cd[pos+30:pos+32])[0]
            cl=struct.unpack("<H",cd[pos+32:pos+34])[0]; lho=struct.unpack("<I",cd[pos+42:pos+46])[0]
            name=cd[pos+46:pos+46+nl].decode("latin1")
            if name.endswith(target):
                lh=get(url,lho,lho+29); lnl=struct.unpack("<H",lh[26:28])[0]; lel=struct.unpack("<H",lh[28:30])[0]
                off=lho+30+lnl+lel; raw=get(url,off,off+csz-1)
                open(out,"wb").write(zlib.decompress(raw,-15) if meth==8 else raw); return True
            pos+=46+nl+el+cl
        return False
    b="https://knmi-ecad-assets-prd.s3.amazonaws.com/download/"
    print("  re-extracting ECA&D TX/TN ...")
    extract(b+"ECA_blend_tx.zip","TX_STAID001860.txt",P("heathrow_tx.txt"))
    extract(b+"ECA_blend_tn.zip","TN_STAID001860.txt",P("heathrow_tn.txt"))

# ---------------- METAR download ----------------
def download_metar(start_ymd):
    y0,m0,d0 = start_ymd
    url=("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=EGLL&data=tmpc"
         f"&year1={y0}&month1={m0}&day1={d0}&year2={y0+2}&month2=1&day2=1"
         "&tz=Europe/London&format=onlycomma&latlon=no&missing=M")
    print(f"  downloading METAR from {y0}-{m0:02d}-{d0:02d} ...")
    data=urllib.request.urlopen(url, timeout=120).read()
    open(P("egll_metar.csv"),"wb").write(data)

def today_london():
    return datetime.now(ZoneInfo("Europe/London")).strftime("%Y%m%d")

def metar_daily(cutoff_ymd, end_excl):
    """Return dicts date('YYYYMMDD')->max/min for METAR days after the ECA&D cutoff
    and strictly before end_excl.

    Excluding the in-progress day matters: a day's minimum lands near dawn but its
    maximum lands mid-afternoon, so a partial day always has a usable min and a
    too-low max. Counting it would drop hot days while keeping tropical nights.
    """
    cutoff = "%04d%02d%02d" % cutoff_ymd
    mx=defaultdict(lambda:-99.); mn=defaultdict(lambda:99.)
    with open(P("egll_metar.csv")) as f:
        for r in csv.DictReader(f):
            v=r.get("tmpc")
            if v in ("M","",None): continue
            try: v=float(v)
            except: continue
            k=r["valid"][:10].replace("-","")
            if k<=cutoff or k>=end_excl: continue
            mx[k]=max(mx[k],v); mn[k]=min(mn[k],v)
    return {k:round(v,1) for k,v in mx.items()}, {k:round(v,1) for k,v in mn.items()}

# ---------------- main build ----------------
def main():
    refresh = "--refresh-ecad" in sys.argv
    if refresh: refresh_ecad()

    tx=load_eca(P("heathrow_tx.txt")); tn=load_eca(P("heathrow_tn.txt"))
    eca_last=max(tx)                       # 'YYYYMMDD'
    yy,mm,dd=_ymd(eca_last)
    nxt=date(yy,mm,dd)+timedelta(days=1)
    download_metar((nxt.year,nxt.month,nxt.day))
    mmx,mmn=metar_daily((yy,mm,dd), today_london())
    for k in mmx: tx[k]=mmx[k]
    for k in mmn: tn[k]=mmn[k]
    metar_last=max(mmx) if mmx else eca_last

    # per-year daily
    yrs_max=defaultdict(dict); yrs_min=defaultdict(dict)
    for k,v in tx.items(): yrs_max[int(k[:4])][doy(*_ymd(k))]=v
    for k,v in tn.items(): yrs_min[int(k[:4])][doy(*_ymd(k))]=v
    all_years=sorted(y for y in yrs_max if len(yrs_max[y])>=200 or str(y)==metar_last[:4])
    cur_year=int(metar_last[:4])

    # ALL (interactive daily)
    ALL={}
    for y in all_years:
        dm=yrs_max[y]; dn=yrs_min[y]; s=min(dm); e=max(dm)
        ALL[str(y)]={"s":s,"x":[dm.get(i) for i in range(s,e+1)],"n":[dn.get(i) for i in range(s,e+1)]}

    # annual counts (historical charts)
    def year_counts(vals,thr):
        c={y:0 for y in all_years}
        for k,v in vals.items():
            y=int(k[:4])
            if y in c and v>=thr: c[y]+=1
        return [c[y] for y in all_years]
    HIST={"years":all_years,"d25":year_counts(tx,25),"d30":year_counts(tx,30),
          "n15":year_counts(tn,15),"n20":year_counts(tn,20),"partial":cur_year}
    # year-to-date counts: every year cut at the same calendar date as the latest data
    cut_md=metar_last[4:8]
    def ytd_counts(vals,thr):
        c={y:0 for y in all_years}
        for k,v in vals.items():
            y=int(k[:4])
            if y in c and k[4:8]<=cut_md and v>=thr: c[y]+=1
        return [c[y] for y in all_years]
    HIST["d25y"]=ytd_counts(tx,25); HIST["d30y"]=ytd_counts(tx,30)
    HIST["n15y"]=ytd_counts(tn,15); HIST["n20y"]=ytd_counts(tn,20)
    HIST["ytd"]=fmt_short(metar_last)
    # longest consecutive-day streak per year (full-year and year-to-date)
    by_year=defaultdict(list)
    for k in set(tx)|set(tn): by_year[int(k[:4])].append(k)
    def streak(vals,thr,cut=None):
        out={y:0 for y in all_years}
        for y in all_years:
            best=run=0; prevmeet=None
            for k in sorted(k for k in by_year[y] if k in vals and (cut is None or k[4:8]<=cut)):
                d=date(*_ymd(k))
                if vals[k]>=thr:
                    run=run+1 if (prevmeet and (d-prevmeet).days==1) else 1
                    prevmeet=d; best=max(best,run)
                else:
                    run=0; prevmeet=None
            out[y]=best
        return [out[y] for y in all_years]
    for key,vals,thr in [("d25",tx,25),("d30",tx,30),("n15",tn,15),("n20",tn,20)]:
        HIST[key+"s"]=streak(vals,thr)
        HIST[key+"sy"]=streak(vals,thr,cut_md)

    # decade weekly profiles + averages (complete years only, exclude current partial year)
    cov=defaultdict(int)
    for k in tx: cov[int(k[:4])]+=1
    good=set(y for y in cov if cov[y]>=350 and y<cur_year)
    NW=52
    wk=lambda dn: min(NW-1,(dn-1)//7)
    wmax=defaultdict(lambda:defaultdict(list)); wmin=defaultdict(lambda:defaultdict(list))
    peryr=defaultdict(lambda:[0,0,0,0])
    for k,v in tx.items():
        y=int(k[:4])
        if y in good:
            wmax[(y//10)*10][wk(doy(*_ymd(k)))].append(v)
            if v>=25:peryr[y][0]+=1
            if v>=30:peryr[y][1]+=1
    for k,v in tn.items():
        y=int(k[:4])
        if y in good:
            wmin[(y//10)*10][wk(doy(*_ymd(k)))].append(v)
            if v>=15:peryr[y][2]+=1
            if v>=20:peryr[y][3]+=1
    decs=sorted(wmax)
    import statistics as st
    DEC={"decades":[str(d) for d in decs],
         "weeks":[w*7+4 for w in range(NW-1)]+[361],
         "weekmax":{}, "weekmin":{}, "avg":{}, "maxprof":{}, "minprof":{}}
    for dec in decs:
        DEC["weekmax"][str(dec)]=[round(sum(wmax[dec][w])/len(wmax[dec][w]),2) if wmax[dec][w] else None for w in range(NW)]
        DEC["weekmin"][str(dec)]=[round(sum(wmin[dec][w])/len(wmin[dec][w]),2) if wmin[dec][w] else None for w in range(NW)]
        ys=[y for y in peryr if (y//10)*10==dec]
        DEC["avg"][str(dec)]={"d25":round(st.mean(peryr[y][0] for y in ys),1),
                              "d30":round(st.mean(peryr[y][1] for y in ys),1),
                              "n15":round(st.mean(peryr[y][2] for y in ys),1),
                              "n20":round(st.mean(peryr[y][3] for y in ys),1),"nyears":len(ys)}

    # monthly averages per year: mean daily max, mean daily min, and their midpoint.
    # A month only ranks if it is essentially complete — otherwise the part-year's
    # 8-day July would be compared against 31-day Julys.
    mdays_x=defaultdict(list); mdays_n=defaultdict(list); mdays_b=defaultdict(list)
    for k,v in tx.items(): mdays_x[(int(k[:4]),int(k[4:6]))].append(v)
    for k,v in tn.items(): mdays_n[(int(k[:4]),int(k[4:6]))].append(v)
    for k in set(tx)&set(tn):
        mdays_b[(int(k[:4]),int(k[4:6]))].append((tx[k]+tn[k])/2)
    def mavg(store,y,m):
        vals=store.get((y,m))
        need=calendar.monthrange(y,m)[1]-2      # tolerate a couple of gaps
        if not vals or len(vals)<need: return None
        return round(sum(vals)/len(vals),1)
    MONTHLY={"years":all_years,"cur":cur_year,
             "hi":{}, "lo":{}, "avg":{}}
    for m in range(1,13):
        MONTHLY["hi"][str(m)]=[mavg(mdays_x,y,m) for y in all_years]
        MONTHLY["lo"][str(m)]=[mavg(mdays_n,y,m) for y in all_years]
        MONTHLY["avg"][str(m)]=[mavg(mdays_b,y,m) for y in all_years]

    # season profiles (all qualifying days, all years)
    def season(vals,thr):
        bd=[0]*366; bm=[0]*13
        for k,v in vals.items():
            if v>=thr:
                dn=doy(*_ymd(k)); bd[dn]+=1; bm[int(k[4:6])]+=1
        peak=max(range(1,366),key=lambda i:bd[i])
        return {"doy":bd[1:366],"mf":0,"ml":0,"pk":peak,"tot":sum(bd),"mon":bm[1:13]}
    SEASON={"d25":season(tx,25),"d30":season(tx,30),"n15":season(tn,15),"n20":season(tn,20)}

    # dynamic strings
    n20_cur=HIST["n20"][-1]
    prev_rec=max(HIST["n20"][:-1]) if len(HIST["n20"])>1 else 0
    prev_rec_yr=all_years[HIST["n20"].index(prev_rec)] if prev_rec else None
    if n20_cur>prev_rec:
        n20_txt=(f"Genuinely rare even now. <b>Part-year {cur_year} leads at {n20_cur}</b> "
                 f"— a new all-time high, past {prev_rec_yr}'s {prev_rec}.")
    else:
        n20_txt=(f"Genuinely rare even now. <b>{prev_rec_yr} holds the record at {prev_rec}</b>; "
                 f"{cur_year} so far has {n20_cur}.")

    j=lambda o: json.dumps(o,separators=(",",":"))

    first_year=all_years[0]

    os.makedirs(SITE, exist_ok=True)

    # icons + social card. metar_last stamps the card URL so scrapers re-fetch it.
    open(O("favicon.svg"),"w").write(FAVICON)
    ic=canvas(180,180,"#16130f")
    for x0,y0,c in [(34,107,"#4f97ec"),(75,76,"#f2824a"),(115,39,"#ec6a6a")]:
        fill(ic,180,180,x0,y0,x0+31,149,_rgb(c))
    write_png(O("apple-touch-icon.png"),180,180,ic)
    social_card(O("social.png"), all_years, HIST["d25"], cur_year)

    # render year_explorer
    t=open(P("year_explorer.tmpl.html")).read()
    t=(t.replace("__ALL__",j(ALL)).replace("__DEC__",j(DEC))
        .replace("__LASTDATE__",fmt_short(metar_last))
        .replace("__CURYEAR__",str(cur_year)).replace("__LASTCOMPLETE__",str(cur_year-1)))
    emit("year_explorer.html",t,here="/year_explorer",stamp=metar_last)

    # render heathrow_heat as the site's front page
    g=open(P("heathrow_heat.tmpl.html")).read()
    g=(g.replace("__HIST__",j(HIST)).replace("__SEASON__",j(SEASON))
        .replace("__ECALAST__",fmt_long(eca_last)).replace("__METARLAST__",fmt_long(metar_last))
        .replace("__METARSHORT__",fmt_short(metar_last)).replace("__YTD__",fmt_short(metar_last))
        .replace("__CURYEAR__",str(cur_year)).replace("__NYEARS__",str(cur_year-first_year))
        .replace("__N20_INSIGHT__",n20_txt).replace("__MONTHLY__",j(MONTHLY)))
    emit("index.html",g,here="/",stamp=metar_last)

    # without this Pages answers every unknown path with index.html and a 200
    emit("404.html",open(P("404.tmpl.html")).read())

    # report
    i=all_years.index(cur_year)
    print("\n=== refreshed ===")
    print(f"ECA&D official through {fmt_long(eca_last)}; METAR through {fmt_long(metar_last)}")
    print(f"{cur_year} YTD: {HIST['d25'][i]} d≥25°, {HIST['d30'][i]} d≥30°, "
          f"{HIST['n15'][i]} nights≥15°, {HIST['n20'][i]} tropical nights≥20°")
    print("wrote public/: index.html (the record), year_explorer.html, 404.html, favicon.svg, apple-touch-icon.png, social.png")

if __name__=="__main__":
    main()
