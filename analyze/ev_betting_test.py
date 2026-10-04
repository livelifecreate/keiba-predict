"""
期待値で買う（Benter の2段目）の検証（2026-10-04）

1. 各レースで p_i ∝ exp(a·log(市場勝率) + b·案G効用 + c·巻き返し候補) を条件付きロジットで推定
   （学習〜2025/06で重みを決め、テスト2025/07〜で評価）。
2. 3着内確率は Harville の式で勝率から計算。
3. 単勝: p×オッズ が閾値超えのみ購入。複勝: P(3着内)×予想複勝払戻（学習期間の「単勝オッズ帯別・3着内時の平均複勝払戻」）が閾値超えのみ購入。
使い方: python3 analyze/ev_betting_test.py
"""
import sys, textwrap
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import comeback_test as CB

TRAIN_END = CB.TRAIN_END


def build():
    src = open(Path(__file__).resolve().parent / "comeback_test.py", encoding="utf-8").read()
    body = src.split("def main():")[1].split("    def line(x, lab):")[0]
    ns = dict(vars(CB)); exec(textwrap.dedent(body), ns)
    df = ns["df"]
    odds = df["単勝オッズ"].astype(float)
    q = 1 / odds
    df["lq"] = np.log(q / q.groupby(df["rid"]).transform("sum"))
    u = df.groupby("rid")["v3_c"].transform(lambda s: s * 0)  # placeholder
    # 案G効用（rank_G を作った u を再計算）
    import ability_blend_backtest as B
    uu, _ = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["uG"] = (uu - pd.Series(uu, index=df.index).groupby(df["rid"]).transform("mean")).values
    df["comeback"] = ((df.rank_G <= 3) & df.bigloss & (df.reasons.apply(len) > 0)).astype(float)
    df["won"] = (df["実着順"].astype(float) == 1).astype(float)
    return df


def fit(d, cols, iters=30):
    """条件付きロジットをニュートン法で推定（numpyのみ）"""
    X = d[cols].values.astype(float); y = d["won"].values; _, gi = np.unique(d["rid"].values, return_inverse=True)
    G = gi.max() + 1
    w = np.zeros(len(cols)); w[0] = 1.0
    for _ in range(iters):
        z = X @ w
        zmax = np.full(G, -np.inf); np.maximum.at(zmax, gi, z)
        e = np.exp(z - zmax[gi]); s = np.bincount(gi, e, G)
        p = e / s[gi]
        Ex = np.stack([np.bincount(gi, p * X[:, k], G) for k in range(X.shape[1])], 1)
        Xw = np.stack([np.bincount(gi, y * X[:, k], G) for k in range(X.shape[1])], 1)
        has = np.bincount(gi, y, G) > 0
        grad = (Xw[has] - Ex[has]).sum(0)
        Xc = X - Ex[gi]
        H = -(Xc * (p * has[gi])[:, None]).T @ Xc
        step = np.linalg.solve(H, grad)
        w = w - step
        if np.abs(step).max() < 1e-6: break
    return w, None


def probs(d, cols, w):
    z = d[cols].values @ w
    e = np.exp(z - pd.Series(z, index=d.index).groupby(d["rid"]).transform("max").values)
    return e / pd.Series(e, index=d.index).groupby(d["rid"]).transform("sum").values


def harville_top3(p):
    n = len(p); out = p.copy()
    for j in range(n):
        if p[j] >= 1: continue
        r2 = p / (1 - p[j]); r2[j] = 0
        out += p[j] * r2
        for k in range(n):
            if k == j or p[j] + p[k] >= 1: continue
            r3 = p / (1 - p[j] - p[k]); r3[j] = r3[k] = 0
            out += p[j] * r2[k] * r3
    return out


def main():
    df = build()
    tr = df[df.dt < TRAIN_END]
    variants = {"市場のみ": ["lq"], "市場+案G": ["lq", "uG"], "市場+案G+巻き返し": ["lq", "uG", "comeback"]}
    P = {}
    print("■ 2段目の重み（学習期間）と対数損失（テスト期間・1レースあたり）")
    for name, cols in variants.items():
        w, nll = fit(tr, cols)
        te = df[df.dt >= TRAIN_END]
        p = probs(df, cols, w)
        P[name] = p
        ll = -np.mean(np.log(p[(df.dt >= TRAIN_END).values & (df.won == 1).values]))
        print(f"  {name:<16} 重み {np.round(w, 3)}  テスト対数損失 {ll:.4f}")

    # 複勝の予想払戻（学習期間・単勝オッズ帯別の3着内時平均）
    ob = pd.cut(df["単勝オッズ"].astype(float), [0, 1.5, 2, 3, 5, 8, 12, 20, 35, 60, 1e9])
    placed = df[(df.dt < TRAIN_END) & (df.place > 0)]
    exp_pay = placed.groupby(ob[placed.index], observed=True)["place"].mean()
    df["exp_place_pay"] = ob.map(exp_pay).astype(float)

    for name in variants:
        df["p"] = P[name]
        df["p3"] = df.groupby("rid")["p"].transform(lambda s: pd.Series(harville_top3(s.values), index=s.index))
        df["ev_win"] = df["p"] * df["単勝オッズ"].astype(float)
        df["ev_pl"] = df["p3"] * df["exp_place_pay"] / 100
        print(f"\n■ {name}（テスト期間2025/07〜の成績。学習期間の値は参考）")
        for kind, ev, pay in (("単勝", "ev_win", "win"), ("複勝", "ev_pl", "place")):
            for th in (1.0, 1.1, 1.2, 1.3):
                for lab, x in (("学習", df[(df.dt < TRAIN_END) & (df[ev] > th)]), ("テスト", df[(df.dt >= TRAIN_END) & (df[ev] > th)])):
                    if kind == "複勝": x = x[x.has_fk]
                    if lab == "学習": trs = f"学習 n={len(x):>4} ROI{x[pay].mean():4.0f}%"
                    else:
                        ex = x.drop(x[pay].nlargest(3).index)[pay].mean() if len(x) > 3 else np.nan
                        print(f"   {kind} EV>{th:.1f}: テスト n={len(x):>4} 的中{(x[pay]>0).mean()*100:5.1f}% ROI{x[pay].mean():4.0f}%（上位3除外{ex:4.0f}%・平均人気{x['pop'].mean():4.1f}） | {trs}")


if __name__ == "__main__":
    main()
