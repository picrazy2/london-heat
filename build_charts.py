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
import urllib.request, csv, json, re, os, sys, struct, zlib
from datetime import date, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
P = lambda f: os.path.join(BASE, f)
MABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

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

def metar_daily(cutoff_ymd):
    """Return dicts date('YYYYMMDD')->max/min for METAR days AFTER the ECA&D cutoff."""
    cutoff = "%04d%02d%02d" % cutoff_ymd
    mx=defaultdict(lambda:-99.); mn=defaultdict(lambda:99.)
    with open(P("egll_metar.csv")) as f:
        for r in csv.DictReader(f):
            v=r.get("tmpc")
            if v in ("M","",None): continue
            try: v=float(v)
            except: continue
            k=r["valid"][:10].replace("-","")
            if k<=cutoff: continue
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
    mmx,mmn=metar_daily((yy,mm,dd))
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

    # render year_explorer
    t=open(P("year_explorer.tmpl.html")).read()
    t=(t.replace("__ALL__",j(ALL)).replace("__DEC__",j(DEC))
        .replace("__LASTDATE__",fmt_short(metar_last))
        .replace("__CURYEAR__",str(cur_year)).replace("__LASTCOMPLETE__",str(cur_year-1)))
    open(P("year_explorer.html"),"w").write(t)

    # render heathrow_heat
    g=open(P("heathrow_heat.tmpl.html")).read()
    g=(g.replace("__HIST__",j(HIST)).replace("__SEASON__",j(SEASON))
        .replace("__ECALAST__",fmt_long(eca_last)).replace("__METARLAST__",fmt_long(metar_last))
        .replace("__METARSHORT__",fmt_short(metar_last)).replace("__YTD__",fmt_short(metar_last))
        .replace("__CURYEAR__",str(cur_year)).replace("__NYEARS__",str(cur_year-first_year))
        .replace("__N20_INSIGHT__",n20_txt))
    open(P("heathrow_heat.html"),"w").write(g)

    # report
    i=all_years.index(cur_year)
    print("\n=== refreshed ===")
    print(f"ECA&D official through {fmt_long(eca_last)}; METAR through {fmt_long(metar_last)}")
    print(f"{cur_year} YTD: {HIST['d25'][i]} d≥25°, {HIST['d30'][i]} d≥30°, "
          f"{HIST['n15'][i]} nights≥15°, {HIST['n20'][i]} tropical nights≥20°")
    print("wrote year_explorer.html and heathrow_heat.html")

if __name__=="__main__":
    main()
