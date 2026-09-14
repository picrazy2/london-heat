"""Fit the deployment models small enough to ship, and export them as plain
JSON the browser can evaluate: W (forecastable weather -> log PM2.5) and R
(lead-aware residual). Also writes a test vector so the JavaScript port of the
feature engineering can be checked against Python to the last decimal.

Tree encoding, per tree: parallel arrays over internal nodes
  f[i] feature index, t[i] threshold, l[i] / r[i] child (>= 0 internal node,
  < 0 leaf: value = v[-c - 1]), d[i] 1 if a missing value goes left.
Score = sum over trees of the leaf reached, plus nothing (LightGBM folds the
base score into the first tree's leaves).
"""
import json, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import r2_score
import dataset, train, train_lead, forecast

OUT = train.OUT
SMALL = dict(num_leaves=31, learning_rate=0.06, min_data_in_leaf=100, feature_fraction=0.8, bagging_fraction=0.8,
             bagging_freq=1, lambda_l2=1.0, verbose=-1, num_threads=8, objective="regression")
SMALL_R = dict(SMALL, num_leaves=31, min_data_in_leaf=200, lambda_l2=5.0, learning_rate=0.1)


def fit_small(X, y, Xv, yv, params, rounds=1500):
    dtr = lgb.Dataset(X, y); dva = lgb.Dataset(Xv, yv, reference=dtr)
    return lgb.train(params, dtr, rounds, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])


def compact(booster):
    dump = booster.dump_model(num_iteration=booster.best_iteration or None)
    trees = []
    for t in dump["tree_info"]:
        f, th, l, r, d, v = [], [], [], [], [], []
        def walk(node):
            if "leaf_value" in node:
                v.append(node["leaf_value"]); return -len(v)
            i = len(f); f.append(node["split_feature"]); th.append(node["threshold"]); d.append(1 if node["default_left"] else 0)
            l.append(None); r.append(None)
            assert node["decision_type"] == "<=", node["decision_type"]
            # missing_type: "None" -> a NaN is treated as 0 before the comparison;
            # "Zero" -> both 0 and NaN take the default direction; "NaN" -> NaN does.
            mt = node.get("missing_type", "NaN")
            if mt == "None": d[i] = 2
            elif mt == "Zero": d[i] = 3 + (1 if node["default_left"] else 0)
            l[i] = walk(node["left_child"]); r[i] = walk(node["right_child"])
            return i
        walk(t["tree_structure"])
        # Thresholds are nudged up by a relative 1e-9: LightGBM puts them at
        # midpoints between observed values, so nothing real lives in that
        # sliver, and a rolling sum that lands on 0.20000000000000098 in one
        # implementation and 0.2 in another no longer takes different branches.
        # Ten significant figures keep the nudge and the 1e-35 binary splits.
        nudged = [float(f"{x + 1e-9 * max(1.0, abs(x)):.10g}") for x in th]
        trees.append({"f": f, "t": nudged, "l": l, "r": r, "d": d, "v": [round(x, 5) for x in v]})
    return trees


def predict_compact(trees, X):
    """Reference evaluator for the compact format (what the JS must match)."""
    out = np.zeros(len(X))
    for tr in trees:
        f, th, l, r, d, v = tr["f"], tr["t"], tr["l"], tr["r"], tr["d"], tr["v"]
        for k in range(len(X)):
            row = X[k]; i = 0
            while i >= 0:
                x = row[f[i]]; dd = d[i]
                if dd >= 3:
                    if np.isnan(x) or x == 0.0:
                        i = l[i] if dd == 4 else r[i]; continue
                elif np.isnan(x):
                    if dd == 2: x = 0.0
                    else:
                        i = l[i] if dd == 1 else r[i]; continue
                i = l[i] if x <= th[i] else r[i]
            out[k] += v[-i - 1]
    return out


if __name__ == "__main__":
    df = dataset.build()
    cols_w = [c for c in dataset.feature_sets(df)["forecastable"] if c != "year_frac"] + ["level365"]
    tr, va, te = train.split(df); y = np.log1p(df["pm25"])
    # 1. how much does "small" cost? (forward split)
    mw_s = fit_small(df.loc[tr, cols_w], y[tr], df.loc[va, cols_w], y[va], SMALL)
    print(f"small W: {mw_s.num_trees()} trees, test r2_log {r2_score(y[te], mw_s.predict(df.loc[te, cols_w])):.3f}  (full-size was 0.711)")
    # 2. deployment fit on everything
    ok = df["pm25"].notna() & df["level365"].notna()
    rng = np.random.default_rng(2); ym = df.index.year * 12 + df.index.month
    months = np.array(sorted(set(ym[ok]))); va_m = rng.choice(months, size=len(months) // 10, replace=False)
    vam = ok & pd.Series(np.isin(ym, va_m), index=df.index); trm = ok & ~vam
    mw = fit_small(df.loc[trm, cols_w], y[trm], df.loc[vam, cols_w], y[vam], SMALL, rounds=600)   # capped: the file has to ship
    wpred = train_lead.oof_weather(df, cols_w, ok); resid = (y - wpred).to_numpy()
    rng2 = np.random.default_rng(0); parts = []; ys = []
    for _ in range(3):
        F = train_lead.resid_frame(df, resid, wpred, train_lead.draw_leads(rng2, len(df))); parts.append(F); ys.append(pd.Series(resid, index=df.index))
    XR = pd.concat(parts); yR = pd.concat(ys); okr = yR.notna() & XR["r_last"].notna()
    trr = (pd.concat([trm] * 3) & okr).to_numpy(); var = (pd.concat([vam] * 3) & okr).to_numpy()
    mr = fit_small(XR[trr], yR[trr], XR[var], yR[var], SMALL_R)
    cols_r = list(XR.columns)
    print(f"deploy W {mw.num_trees()} trees, R {mr.num_trees()} trees")
    # 3. export + verify the compact evaluator against LightGBM
    tw, trr_ = compact(mw), compact(mr)
    Xs = df.loc[te, cols_w].to_numpy(dtype=float)[:500]
    dw = np.abs(predict_compact(tw, Xs) - mw.predict(Xs)); assert dw.mean() < 0.01 and dw.max() < 0.2, ("compact W mismatch", dw.mean(), dw.max())
    Xr = XR[var][cols_r].to_numpy(dtype=float)[:500]
    dr = np.abs(predict_compact(trr_, Xr) - mr.predict(Xr)); assert dr.mean() < 0.01 and dr.max() < 0.2, ("compact R mismatch", dr.mean(), dr.max())
    print(f"compact vs LightGBM: W mean|diff| {dw.mean():.4f}  R mean|diff| {dr.mean():.4f}")
    model = {"w": {"cols": cols_w, "trees": tw}, "r": {"cols": cols_r, "trees": trr_},
             "cny": {str(k): v.isoformat() for k, v in dataset.CNY.items()},
             "note": "log1p(PM2.5) = W(weather) + R(lead, what was known at issue). Evaluate with the tree format in ml/export_model.py."}
    path = OUT.parent.parent / "data" / "pm25_model.json"
    json.dump(model, open(path, "w"), separators=(",", ":"))
    print("wrote", path, f"{path.stat().st_size/1e6:.2f} MB")
    # 4. test vector: a real forecast frame through the Python feature pipeline
    f = forecast.fetch_forecast()
    frame = forecast.to_model_frame(f); frame["level365"] = float(df["level365"].dropna().iloc[-1])
    X = dataset.engineer(frame); X["level365"] = frame["level365"]
    w = predict_compact(tw, X[cols_w].to_numpy(dtype=float))
    raw = {"time": [str(t) for t in f.index], **{c: [None if pd.isna(v) else float(v) for v in f[c]] for c in f.columns}}
    json.dump({"raw": raw, "level365": frame["level365"].iloc[0], "cols": cols_w,
               "features": {c: [None if pd.isna(v) else float(v) for v in X[c]] for c in cols_w},
               "w": [float(v) for v in w]}, open(OUT / "js_test_vector.json", "w"))
    print("wrote test vector:", len(f), "hours")
