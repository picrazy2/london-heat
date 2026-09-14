"""Beijing (54511, Nanjiao) radiosonde from IGRA v2 -> twice-daily profile summaries.

What the surface can't see: whether there is a lid. For each sounding the
temperature at 925 and 850 hPa relative to the surface, the strongest inversion
in the lowest 1500 m, and the wind just above the city.
"""
import numpy as np, pandas as pd
from pathlib import Path

SRC = Path(__file__).parent / "data" / "igra" / "CHM00054511-data.txt"
OUT = Path(__file__).parent / "data" / "igra_beijing.csv"

def val(s, scale=1.0):
    try:
        v = int(s)
    except ValueError:
        return np.nan
    return np.nan if v in (-9999, -8888) else v * scale

rows = []
cur = None
def flush():
    if cur is None or len(cur["lev"]) < 4: return
    L = pd.DataFrame(cur["lev"], columns=["p", "z", "t", "rh", "wd", "ws"]).dropna(subset=["p"])
    L = L[(L.p > 0)].sort_values("p", ascending=False)
    L = L[L.z.notna() | L.t.notna()]
    if L.empty: return
    sfc = L.iloc[0]
    if sfc.p < 900 or np.isnan(sfc.t): return       # station is at ~55 m; a sounding without a surface is junk
    out = {"t": cur["t"], "p_sfc": sfc.p, "t_sfc": sfc.t}
    lp = np.log(L.p.to_numpy())
    def interp(col, p):
        ok = L[col].notna().to_numpy()
        if ok.sum() < 2 or L.p[ok].max() < p or L.p[ok].min() > p: return np.nan
        return float(np.interp(np.log(p), lp[ok][::-1], L[col].to_numpy()[ok][::-1]))
    for p in (925, 850, 700):
        out[f"t{p}"] = interp("t", p); out[f"rh{p}"] = interp("rh", p)
        wd, ws = interp("wd", p), interp("ws", p)          # crude on direction, fine for a component
        out[f"ws{p}"] = ws; out[f"vn{p}"] = ws * np.cos(np.deg2rad(wd)) if not np.isnan(wd) else np.nan
    # inversion in the lowest 1500 m: largest temperature rise between successive levels
    z0 = sfc.z if not np.isnan(sfc.z) else 55
    low = L[(L.z.notna()) & (L.t.notna()) & (L.z - z0 <= 1500)]
    if len(low) >= 2:
        dt = np.diff(low.t.to_numpy()); dz = np.diff(low.z.to_numpy())
        out["inv_strength"] = float(max(0, dt.max()))            # K, 0 if no inversion
        i = int(dt.argmax()); out["inv_base"] = float(low.z.iloc[i] - z0) if dt[i] > 0 else np.nan
        top = low.iloc[-1]
        out["lapse_low"] = float((top.t - sfc.t) / max(1, (top.z - z0)) * 1000)   # K/km, positive = inversion-ish
        out["ws_low"] = float(low.ws.mean()) if low.ws.notna().any() else np.nan
    rows.append(out)

with open(SRC) as f:
    for line in f:
        if line.startswith("#"):
            flush()
            y, m, d, h = int(line[13:17]), int(line[18:20]), int(line[21:23]), int(line[24:26])
            if y < 2013 or h == 99:
                cur = None; continue
            cur = {"t": pd.Timestamp(y, m, d, h) + pd.Timedelta(hours=8), "lev": []}   # UTC -> Beijing
        elif cur is not None:
            cur["lev"].append((val(line[9:15], 0.01), val(line[16:21]), val(line[22:27], 0.1),
                               val(line[28:33], 0.1), val(line[40:45]), val(line[46:51], 0.1)))
flush()
df = pd.DataFrame(rows).set_index("t").sort_index()
df["inv925"] = df.t925 - df.t_sfc; df["inv850"] = df.t850 - df.t_sfc
df.to_csv(OUT)
print(df.shape, df.index.min(), df.index.max())
print(df.groupby(df.index.year).size().to_dict())
print(df.index.hour.value_counts().to_dict())
print(df.describe().T[["count", "mean", "min", "50%", "max"]].round(1))
