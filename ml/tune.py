"""Random search over LightGBM on the validation year, for a given feature set."""
import argparse, json, time
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import r2_score
import dataset, train

ap = argparse.ArgumentParser(); ap.add_argument("--set", default="plus_cities"); ap.add_argument("--n", type=int, default=24)
a = ap.parse_args()
df = dataset.build(); cols = [c for c in dataset.feature_sets(df)[a.set] if c != "year_frac"] + ["level365"]
tr, va, te = train.split(df); y = np.log1p(df["pm25"])
X = df[cols]; Xtr, ytr, Xva, yva = X[tr], y[tr], X[va], y[va]
rng = np.random.default_rng(0); rows = []
space = dict(num_leaves=[31, 63, 127, 255], min_data_in_leaf=[20, 50, 100, 200, 400], feature_fraction=[0.5, 0.65, 0.8, 0.95],
             bagging_fraction=[0.7, 0.85, 1.0], lambda_l2=[0, 1, 5, 20], learning_rate=[0.02, 0.03, 0.05],
             objective=["regression", "huber"], min_gain_to_split=[0, 0.01, 0.1])
base = dict(verbose=-1, num_threads=8, bagging_freq=1, seed=0)
for i in range(a.n):
    p = {k: v[rng.integers(len(v))] for k, v in space.items()}; p = {k: (float(v) if isinstance(v, np.floating) else int(v) if isinstance(v, np.integer) else v) for k, v in p.items()}
    t0 = time.time()
    dtr = lgb.Dataset(Xtr, ytr); dva = lgb.Dataset(Xva, yva, reference=dtr)
    m = lgb.train({**base, **p}, dtr, num_boost_round=6000, valid_sets=[dva], callbacks=[lgb.early_stopping(200, verbose=False)])
    pv = m.predict(X[va], num_iteration=m.best_iteration); pt = m.predict(X[te], num_iteration=m.best_iteration)
    r = {**p, "iters": m.best_iteration, "val": r2_score(y[va], pv), "test": r2_score(y[te], pt), "secs": round(time.time() - t0)}
    rows.append(r); print(f"{i:2d} val {r['val']:.4f} test {r['test']:.4f} iters {r['iters']:5d} {p}", flush=True)
res = pd.DataFrame(rows).sort_values("val", ascending=False); res.to_csv(train.OUT / f"tune_{a.set}.csv", index=False)
print("\nbest by val:\n", res.head(5).to_string(index=False))
json.dump({k: (v.item() if hasattr(v, "item") else v) for k, v in res.iloc[0].drop(["val", "test", "secs", "iters"]).items()}, open(train.OUT / f"best_params_{a.set}.json", "w"))
