"""Fit and compare PM2.5 models on the hourly table.

Target is log1p(pm25): the series is right-skewed with a handful of 500+ hours,
and a model trained on raw values spends all its capacity on those. Skill is
reported on both scales.

Split is strictly forward in time. Trees cannot extrapolate the year trend, so
the honest test of "can it predict 2025" is to hold 2024+ out entirely.
"""
import argparse, json, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb
import torch
import torch.nn as nn
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

import dataset

HERE = Path(__file__).parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
torch.manual_seed(0); np.random.seed(0)
DEV = "mps" if torch.backends.mps.is_available() else "cpu"

TRAIN_END, VAL_END = "2023-01-01", "2024-01-01"


def split(df):
    ok = df["pm25"].notna()
    tr = ok & (df.index < TRAIN_END)
    va = ok & (df.index >= TRAIN_END) & (df.index < VAL_END)
    te = ok & (df.index >= VAL_END)
    return tr, va, te


def score(y_log, p_log):
    y, p = np.expm1(y_log), np.expm1(p_log)
    return {"r2_log": r2_score(y_log, p_log), "r2": r2_score(y, p),
            "rmse": float(np.sqrt(mean_squared_error(y, p))), "mae": float(mean_absolute_error(y, p)),
            "n": int(len(y))}


def fit_ridge(X, y, Xv, yv, Xt):
    sc = StandardScaler().fit(X)
    f = lambda a: np.nan_to_num(sc.transform(a), nan=0.0)      # NaN -> column mean after scaling
    m = Ridge(alpha=1.0).fit(f(X), y)
    return m.predict(f(Xv)), m.predict(f(Xt)), m


def fit_lgb(X, y, Xv, yv, Xt, cat=()):
    params = dict(objective="regression", learning_rate=0.03, num_leaves=63, min_data_in_leaf=100,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1,
                  num_threads=8)
    dtr = lgb.Dataset(X, y, categorical_feature=list(cat))
    dva = lgb.Dataset(Xv, yv, reference=dtr)
    m = lgb.train(params, dtr, num_boost_round=5000, valid_sets=[dva],
                  callbacks=[lgb.early_stopping(200, verbose=False)])
    return m.predict(Xv, num_iteration=m.best_iteration), m.predict(Xt, num_iteration=m.best_iteration), m


class MLP(nn.Module):
    def __init__(self, d, width=256, depth=3, drop=0.1):
        super().__init__()
        layers, last = [], d
        for _ in range(depth):
            layers += [nn.Linear(last, width), nn.GELU(), nn.Dropout(drop)]
            last = width
        layers.append(nn.Linear(last, 1))
        self.net = nn.Sequential(*layers)
    def forward(self, x): return self.net(x).squeeze(-1)


def _train_torch(model, Xtr, ytr, Xva, yva, epochs=60, lr=2e-3, bs=1024, wd=1e-4, log=None):
    model = model.to(DEV)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=wd)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=epochs * ((len(Xtr) + bs - 1) // bs))
    Xtr, ytr = torch.tensor(Xtr, dtype=torch.float32), torch.tensor(ytr, dtype=torch.float32)
    Xva_t, yva_t = torch.tensor(Xva, dtype=torch.float32).to(DEV), torch.tensor(yva, dtype=torch.float32).to(DEV)
    best, best_state, bad = 1e9, None, 0
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(len(Xtr))
        for i in range(0, len(Xtr), bs):
            idx = perm[i:i + bs]
            xb, yb = Xtr[idx].to(DEV), ytr[idx].to(DEV)
            loss = nn.functional.huber_loss(model(xb), yb, delta=1.0)
            opt.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); sched.step()
        model.eval()
        with torch.no_grad():
            vl = nn.functional.mse_loss(model(Xva_t), yva_t).item()
        if log: print(f"    ep {ep:3d} val_mse {vl:.4f}", file=log)
        if vl < best - 1e-4:
            best, bad, best_state = vl, 0, {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 12: break
    model.load_state_dict(best_state)
    return model


def fit_mlp(X, y, Xv, yv, Xt, log=None):
    sc = StandardScaler().fit(X)
    f = lambda a: np.nan_to_num(sc.transform(a), nan=0.0).astype(np.float32)
    m = _train_torch(MLP(X.shape[1]), f(X), y.astype(np.float32), f(Xv), yv.astype(np.float32), log=log)
    m.eval()
    with torch.no_grad():
        pv = m(torch.tensor(f(Xv)).to(DEV)).cpu().numpy()
        pt = m(torch.tensor(f(Xt)).to(DEV)).cpu().numpy()
    return pv, pt, m


# ── sequence model ────────────────────────────────────────────────────────────
class GRUNet(nn.Module):
    """GRU over the past L hours of raw weather, plus the current hour's static features."""
    def __init__(self, d_seq, d_static, hidden=128, layers=2, drop=0.1):
        super().__init__()
        self.gru = nn.GRU(d_seq, hidden, num_layers=layers, batch_first=True, dropout=drop)
        self.head = nn.Sequential(nn.Linear(hidden + d_static, 128), nn.GELU(), nn.Dropout(drop), nn.Linear(128, 1))
    def forward(self, seq, static):
        _, h = self.gru(seq)
        return self.head(torch.cat([h[-1], static], dim=-1)).squeeze(-1)


def make_windows(A, ends, L):
    """A: (T, d) array; ends: integer positions; returns (len(ends), L, d) windows ending at each position."""
    idx = ends[:, None] - np.arange(L)[::-1][None, :]
    return A[idx]


def fit_gru(df, seq_cols, static_cols, tr, va, te, L=72, log=None, epochs=40):
    seq = df[seq_cols].to_numpy(dtype=np.float32)
    sc = StandardScaler().fit(seq[tr.to_numpy()])
    seq = np.nan_to_num(sc.transform(seq), nan=0.0).astype(np.float32)
    st = df[static_cols].to_numpy(dtype=np.float32)
    sc2 = StandardScaler().fit(st[tr.to_numpy()])
    st = np.nan_to_num(sc2.transform(st), nan=0.0).astype(np.float32)
    y = np.log1p(df["pm25"].to_numpy(dtype=np.float32))
    pos = np.arange(len(df))
    def sel(mask):
        p = pos[mask.to_numpy() & (pos >= L)]
        return p
    ptr, pva, pte = sel(tr), sel(va), sel(te)
    model = GRUNet(seq.shape[1], st.shape[1]).to(DEV)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    bs = 512
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-3, total_steps=epochs * ((len(ptr) + bs - 1) // bs))
    seq_t, st_t, y_t = torch.tensor(seq), torch.tensor(st), torch.tensor(y)
    def predict(p):
        model.eval(); outs = []
        with torch.no_grad():
            for i in range(0, len(p), 4096):
                pp = p[i:i + 4096]
                w = torch.tensor(make_windows(seq, pp, L)).to(DEV)
                outs.append(model(w, st_t[pp].to(DEV)).cpu().numpy())
        return np.concatenate(outs)
    best, best_state, bad = 1e9, None, 0
    for ep in range(epochs):
        model.train()
        perm = np.random.permutation(ptr)
        for i in range(0, len(perm), bs):
            pp = perm[i:i + bs]
            w = torch.tensor(make_windows(seq, pp, L)).to(DEV)
            loss = nn.functional.huber_loss(model(w, st_t[pp].to(DEV)), y_t[pp].to(DEV), delta=1.0)
            opt.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); sched.step()
        vl = float(np.mean((predict(pva) - y[pva]) ** 2))
        if log: print(f"    ep {ep:3d} val_mse {vl:.4f}", file=log)
        if vl < best - 1e-4:
            best, bad, best_state = vl, 0, {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 8: break
    model.load_state_dict(best_state)
    return predict(pva), predict(pte), pva, pte, model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-era5", action="store_true")
    ap.add_argument("--models", default="ridge,lgb,mlp,gru")
    ap.add_argument("--sets", default="metar_now,metar_hist,metar_era5,metar_era5_ar")
    ap.add_argument("--tag", default="")
    ap.add_argument("--gru-len", type=int, default=72)
    ap.add_argument("--year", default="level", choices=["raw", "clip", "level", "both"],
                    help="raw year_frac | clip it at the end of training | replace with trailing-year level | both")
    a = ap.parse_args()
    df = dataset.build(with_era5=not a.no_era5)
    sets = dataset.feature_sets(df)
    tr, va, te = split(df)
    y = np.log1p(df["pm25"])
    ytr, yva, yte = y[tr].to_numpy(), y[va].to_numpy(), y[te].to_numpy()
    results, preds = [], {}
    log = open(OUT / f"train{a.tag}.log", "w")
    print(f"train {tr.sum()}  val {va.sum()}  test {te.sum()}   device {DEV}")
    for sname in a.sets.split(","):
        cols = sets.get(sname)
        if not cols or (sname.startswith("metar_era5") and not any(c.startswith("e_") for c in cols)):
            print(f"skip {sname}"); continue
        cols = list(cols)
        X = df[cols].copy()
        if a.year in ("clip", "both"):
            X["year_frac"] = X["year_frac"].clip(upper=pd.Timestamp(TRAIN_END).year)
        if a.year in ("level", "both"):
            X["level365"] = df["level365"]; cols.append("level365")
        if a.year == "level":
            X = X.drop(columns=["year_frac"]); cols.remove("year_frac")
        Xtr, Xva, Xte = X[tr].to_numpy(), X[va].to_numpy(), X[te].to_numpy()
        for mname in a.models.split(","):
            if mname == "gru" and sname not in ("metar_now", "metar_era5", "forecastable"):
                continue           # the GRU builds its own history from raw hours
            t0 = time.time()
            print(f"[{sname}] {mname} ...", end=" ", flush=True)
            if mname == "ridge":
                pv, pt, m = fit_ridge(Xtr, ytr, Xva, yva, Xte)
            elif mname == "lgb":
                pv, pt, m = fit_lgb(pd.DataFrame(Xtr, columns=cols), ytr, pd.DataFrame(Xva, columns=cols), yva,
                                    pd.DataFrame(Xte, columns=cols))
                m.save_model(str(OUT / f"lgb_{sname}{a.tag}.txt"))
                imp = pd.Series(m.feature_importance("gain"), index=cols).sort_values(ascending=False)
                imp.to_csv(OUT / f"importance_{sname}{a.tag}.csv")
            elif mname == "mlp":
                pv, pt, m = fit_mlp(Xtr, ytr, Xva, yva, Xte, log=log)
            elif mname == "gru":
                seq_cols = [c for c in dataset.WEATHER_BASE] + ["hour_sin", "hour_cos"]
                if sname == "metar_era5":
                    seq_cols += dataset.ERA5_BASE
                if sname == "forecastable":
                    seq_cols = [c for c in dataset.ERA5_BASE if not any(k in c for k in ("soil", "et0"))] + ["hour_sin", "hour_cos"] + [c for c in cols if c.startswith("s_") and not c[-1].isdigit()]
                static_cols = [c for c in dataset.TIME if c != "year_frac"] + [c for c in cols if c in ("year_frac", "level365")]
                dfg = df.copy(); dfg["year_frac"] = X["year_frac"] if "year_frac" in X else 0
                pv, pt, pva_pos, pte_pos, m = fit_gru(dfg, seq_cols, static_cols, tr, va, te, L=a.gru_len, log=log)
                torch.save(m.state_dict(), OUT / f"gru_{sname}{a.tag}.pt")
                yva_g, yte_g = y.to_numpy()[pva_pos], y.to_numpy()[pte_pos]
                sv, stt = score(yva_g, pv), score(yte_g, pt)
                preds[f"{sname}/{mname}"] = pd.Series(np.expm1(pt), index=df.index[pte_pos])
                results.append({"set": sname, "model": mname, **{f"val_{k}": v for k, v in sv.items()},
                                **{f"test_{k}": v for k, v in stt.items()}, "secs": time.time() - t0})
                print(f"val r2_log {sv['r2_log']:.3f}  test r2_log {stt['r2_log']:.3f} r2 {stt['r2']:.3f} rmse {stt['rmse']:.1f} mae {stt['mae']:.1f}  ({time.time()-t0:.0f}s)")
                continue
            sv, stt = score(yva, pv), score(yte, pt)
            preds[f"{sname}/{mname}"] = pd.Series(np.expm1(pt), index=df.index[te])
            results.append({"set": sname, "model": mname, **{f"val_{k}": v for k, v in sv.items()},
                            **{f"test_{k}": v for k, v in stt.items()}, "secs": time.time() - t0})
            print(f"val r2_log {sv['r2_log']:.3f}  test r2_log {stt['r2_log']:.3f} r2 {stt['r2']:.3f} rmse {stt['rmse']:.1f} mae {stt['mae']:.1f}  ({time.time()-t0:.0f}s)")
    res = pd.DataFrame(results)
    res.to_csv(OUT / f"results{a.tag}.csv", index=False)
    pd.DataFrame(preds).assign(actual=df["pm25"]).to_parquet(OUT / f"test_preds{a.tag}.parquet")
    print("\n", res[["set", "model", "val_r2_log", "test_r2_log", "test_r2", "test_rmse", "test_mae"]].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
