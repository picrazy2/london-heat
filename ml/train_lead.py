"""A lead-aware forecast: weather model + a residual model that learns how the
weather model's error at issue time persists.

    log pm25(t) = W(t) + R(lead, r(t - lead), upwind(t - lead), ...)

W is the forecastable weather model. r = log pm25 - W is its error, which is
strongly autocorrelated (a stagnant day it under-calls stays under-called).
R is fit on out-of-fold W so the residuals it sees are honest. Each training
row draws a random lead (log-uniform, 1..120 h) so one model covers the
whole horizon and learns the decay itself rather than being handed one.

Scored on 2024-26 by lead. ERA5 stands in for the forecast, so these are
upper bounds on real skill; forecast error grows with lead on top of this.
"""
import json, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import r2_score
import dataset, train

CITY = [f"c_{g}_PM25" for g in ("south", "east", "northwest", "north", "southwest")] + [f"c_{g}_PM10" for g in ("south", "northwest")]
MAXLEAD = 120
P_W = dict(objective="regression", learning_rate=0.03, num_leaves=63, min_data_in_leaf=100, feature_fraction=0.8,
           bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, num_threads=8)
P_R = dict(objective="regression", learning_rate=0.03, num_leaves=31, min_data_in_leaf=200, feature_fraction=0.9,
           bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, verbose=-1, num_threads=8)


def oof_weather(df, cols_w, mask, folds=5, seed=0):
    """Out-of-fold weather predictions over `mask` rows, blocked by month."""
    y = np.log1p(df["pm25"]); ym = df.index.year * 12 + df.index.month
    months = np.array(sorted(set(ym[mask]))); rng = np.random.default_rng(seed)
    fold_of = dict(zip(months, rng.permutation(len(months)) % folds))
    fold = pd.Series([fold_of.get(m, -1) for m in ym], index=df.index)
    pred = pd.Series(np.nan, index=df.index)
    for k in range(folds):
        te = mask & (fold == k); trn = mask & (fold != k) & (fold >= 0)
        va_m = rng.choice([m for m in months if fold_of[m] != k], size=max(3, len(months) // 12), replace=False)
        va = trn & pd.Series(np.isin(ym, va_m), index=df.index); trn = trn & ~va
        dtr = lgb.Dataset(df.loc[trn, cols_w], y[trn]); dva = lgb.Dataset(df.loc[va, cols_w], y[va], reference=dtr)
        m = lgb.train(P_W, dtr, 5000, valid_sets=[dva], callbacks=[lgb.early_stopping(200, verbose=False)])
        pred[te] = m.predict(df.loc[te, cols_w], num_iteration=m.best_iteration)
    return pred


def resid_frame(df, resid, wpred, leads):
    """What was known `leads[i]` hours before each row, for the residual model."""
    pos = np.arange(len(df)); src = pos - leads; ok = src >= 0; src = np.clip(src, 0, len(df) - 1)
    out = pd.DataFrame(index=df.index)
    def at(v): return np.where(ok, np.asarray(v)[src], np.nan)
    out["lead"] = leads
    out["r_last"] = at(resid)
    out["r_last_m6"] = at(pd.Series(resid).rolling(6, min_periods=3).mean())
    out["r_last_m24"] = at(pd.Series(resid).rolling(24, min_periods=12).mean())
    out["pm25_last"] = np.log1p(at(df["pm25"]))
    out["w_last"] = at(wpred)
    out["w_now"] = wpred
    for c in CITY:
        out[c + "_last"] = np.log1p(at(df[c]))
    # upwind minus Beijing at issue time: the gradient the wind will move along
    out["south_grad_last"] = out["c_south_PM25_last"] - out["pm25_last"]
    out["nw_grad_last"] = out["c_northwest_PM25_last"] - out["pm25_last"]
    # how the wind blows between issue and target: mean northerly over the lead window
    vn = df["e_v_north100"].to_numpy(); cs = np.nancumsum(np.nan_to_num(vn)); 
    out["vn100_mean_window"] = np.where(ok, (cs - cs[src]) / np.maximum(leads, 1), np.nan)
    out["precip_window"] = np.where(ok, (np.cumsum(np.nan_to_num(df["e_precipitation"].to_numpy())) - np.cumsum(np.nan_to_num(df["e_precipitation"].to_numpy()))[src]), np.nan)
    out["hour_issue"] = (df.index.hour.to_numpy() - leads) % 24
    return out


def draw_leads(rng, n):
    return np.clip(np.exp(rng.uniform(0, np.log(MAXLEAD), size=n)).round().astype(int), 1, MAXLEAD)


def fit_resid(df, resid, wpred, tr, va, reps=3, seed=0):
    rng = np.random.default_rng(seed); parts = []; ys = []
    for _ in range(reps):
        F = resid_frame(df, resid, wpred, draw_leads(rng, len(df))); parts.append(F); ys.append(resid)
    X = pd.concat(parts); y = pd.concat([pd.Series(r, index=df.index) for r in ys])
    ok = y.notna() & X["r_last"].notna()
    trm = (pd.concat([tr] * reps) & ok).to_numpy(); vam = (pd.concat([va] * reps) & ok).to_numpy()
    dtr = lgb.Dataset(X[trm], y[trm]); dva = lgb.Dataset(X[vam], y[vam], reference=dtr)
    m = lgb.train(P_R, dtr, 6000, valid_sets=[dva], callbacks=[lgb.early_stopping(200, verbose=False)])
    return m, list(X.columns)


if __name__ == "__main__":
    df = dataset.build()
    cols_w = [c for c in dataset.feature_sets(df)["forecastable"] if c != "year_frac"] + ["level365"]
    tr, va, te = train.split(df); y = np.log1p(df["pm25"])
    # weather model: OOF for the fitting years, forward-fit for the test years
    wpred = oof_weather(df, cols_w, tr | va)
    _, pt, mw = train.fit_lgb(df.loc[tr, cols_w], y[tr], df.loc[va, cols_w], y[va], df.loc[te, cols_w])
    wpred[te] = pt
    resid = (y - wpred).to_numpy()
    print(f"weather-only test r2_log {r2_score(y[te], wpred[te]):.3f}   OOF r2_log on fit years {r2_score(y[tr|va], wpred[tr|va]):.3f}")
    m, cols = fit_resid(df, resid, wpred, tr, va)
    m.save_model(str(train.OUT / "lgb_resid.txt")); json.dump(cols, open(train.OUT / "lgb_resid_cols.json", "w"))
    imp = pd.Series(m.feature_importance("gain"), index=cols); print((imp / imp.sum()).sort_values(ascending=False).head(8).round(3).to_dict())
    rows = []
    for L in (1, 3, 6, 12, 18, 24, 36, 48, 72, 96, 120):
        F = resid_frame(df, resid, wpred, np.full(len(df), L))[cols]
        p = wpred + m.predict(F, num_iteration=m.best_iteration)
        ok = te & F["r_last"].notna()
        pers = np.log1p(df["pm25"].shift(L))
        rows.append({"lead": L, "r2_log": r2_score(y[ok], p[ok]), "mae": float(np.abs(np.expm1(y[ok]) - np.expm1(p[ok])).mean()),
                     "persistence_r2_log": r2_score(y[ok], pers[ok]), "weather_only_r2_log": r2_score(y[ok], wpred[ok])})
        print(f"lead {L:3d} h: r2_log {rows[-1]['r2_log']:.3f}  mae {rows[-1]['mae']:.1f}   (persistence {rows[-1]['persistence_r2_log']:.3f}, weather-only {rows[-1]['weather_only_r2_log']:.3f})")
    pd.DataFrame(rows).to_csv(train.OUT / "lead_skill.csv", index=False)
