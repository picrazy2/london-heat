"""Blocked cross-validation across the whole record.

The forward split in train.py asks "can this predict next year". This asks a
different question: "how much of hourly PM2.5 does the weather explain within
the era it was measured in". Each fold holds out whole calendar months (a
month is far longer than any weather memory, so nothing leaks across the
boundary) drawn from every year, so the held-out data spans the same 2013-26
distribution as the training data.

The year drift is handled by the trailing-year level feature as before, so a
held-out January 2016 is judged against the city's late-2015 baseline, not
against 2025's.
"""
import argparse, time
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import r2_score

import dataset, train

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-era5", action="store_true")
    ap.add_argument("--set", default="metar_hist")
    ap.add_argument("--models", default="lgb,mlp")
    ap.add_argument("--folds", type=int, default=5)
    a = ap.parse_args()
    df = dataset.build(with_era5=not a.no_era5)
    cols = [c for c in dataset.feature_sets(df)[a.set] if c != "year_frac"] + ["level365"]
    ok = df["pm25"].notna() & df["level365"].notna()
    ym = df.index.year * 12 + df.index.month
    months = np.array(sorted(set(ym[ok])))
    rng = np.random.default_rng(0)
    fold_of = dict(zip(months, rng.permutation(len(months)) % a.folds))
    fold = pd.Series([fold_of.get(m, -1) for m in ym], index=df.index)
    y = np.log1p(df["pm25"]).to_numpy()
    X = df[cols]
    for mname in a.models.split(","):
        pred = pd.Series(np.nan, index=df.index)
        t0 = time.time()
        for k in range(a.folds):
            te = ok & (fold == k)
            trn = ok & (fold != k)
            # a slice of the training months is the early-stopping set
            va_months = rng.choice(months[np.array([fold_of[m] != k for m in months])], size=max(4, len(months)//10), replace=False)
            va = trn & pd.Series(np.isin(ym, va_months), index=df.index)
            trn = trn & ~va
            Xtr, Xva, Xte = X[trn].to_numpy(), X[va].to_numpy(), X[te].to_numpy()
            if mname == "lgb":
                _, pt, _ = train.fit_lgb(pd.DataFrame(Xtr, columns=cols), y[trn], pd.DataFrame(Xva, columns=cols), y[va], pd.DataFrame(Xte, columns=cols))
            elif mname == "mlp":
                _, pt, _ = train.fit_mlp(Xtr, y[trn], Xva, y[va], Xte)
            elif mname == "ridge":
                _, pt, _ = train.fit_ridge(Xtr, y[trn], Xva, y[va], Xte)
            pred[te] = pt
            print(f"  {mname} fold {k}: r2_log {r2_score(y[te], pt):.3f}", flush=True)
        m = pred.notna()
        s = train.score(y[m], pred[m].to_numpy())
        print(f"{a.set} {mname} blocked-CV: r2_log {s['r2_log']:.3f} r2 {s['r2']:.3f} rmse {s['rmse']:.1f} mae {s['mae']:.1f}  ({time.time()-t0:.0f}s)")
        by_year = pd.DataFrame({"y": y[m], "p": pred[m]}, index=df.index[m]).groupby(lambda t: t.year).apply(
            lambda g: pd.Series({"r2_log": r2_score(g.y, g.p), "mae": np.abs(np.expm1(g.y) - np.expm1(g.p)).mean(), "mean": np.expm1(g.y).mean()}))
        print(by_year.round(2).to_string())
        pred.to_frame(mname).assign(actual=df["pm25"]).to_parquet(train.OUT / f"cv_preds_{a.set}_{mname}.parquet")

if __name__ == "__main__":
    main()
