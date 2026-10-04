"""
先行・コース巧者を案Gの順位計算に加える検証（2026-10-04）

bigloss_course_front_test.py で、先行馬（+3.4pt）とコース巧者（+3.0pt）を案Gが学習/テストとも過小評価していた。
案G = v3_c + rest_sum の2変数に、先行（front）・巧者（ace）・先行×先行2頭以下（front_few）を足して重みを学習（〜2025/06）し、
テスト2025/07〜で 予想1位の成績と、買い条件（10〜13頭・重賞以外）の三連複1軸6点・三連複/馬連/ワイド5頭BOXを比べる。
使い方: python3 analyze/front_ace_blend_test.py
"""
import sys
from itertools import combinations
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bigloss_course_front_test as BF
import ability_blend_backtest as B
import verify.bet_analysis2 as ba2
TRAIN_END = BF.TRAIN_END


def build():
    df = BF.build()
    for c in ("front", "ace"):
        df[c] = df[c].astype(float)
    df["front_few"] = df["front"] * df["few_front"].astype(float)
    return df


def payouts():
    rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}
    def load(kind, k):
        out = {}
        for key, rid in rid_of.items():
            nums, am = ba2.get_payout(rid, kind)
            if am and len(nums) >= k * len(am):
                out[key] = ([frozenset(nums[k*i:k*i+k]) for i in range(len(am))], am)
        return out
    return load("3連複", 3), load("馬連", 2), load("ワイド", 2)


def evaluate(df, rank_col, pays):
    trio, uma, wide = pays
    rows = []
    for key, g in df.groupby(["日付", "レース名"]):
        if key not in trio or key not in uma or key not in wide: continue
        g = g.sort_values(rank_col)
        nums = [int(x) for x in g["馬番"]]
        if len(set(nums)) != len(nums): continue
        t = g.iloc[0]
        def got(tbl, bets):
            c, a = tbl[key]; return sum(x for cc, x in zip(c, a) if cc in bets)
        b5 = {frozenset(c) for c in combinations(nums[:5], 2)}
        rows.append(dict(dt=t["dt"], n=len(g), g=t["クラス"] == "重賞",
            p1_t3=float(t["実着順"]) <= 3, p1_win=float(t["単勝オッズ"]) * 100 if float(t["実着順"]) == 1 else 0,
            trio6=got(trio, {frozenset((nums[0],) + c) for c in combinations(nums[1:5], 2)}),
            trio5=got(trio, {frozenset(c) for c in combinations(nums[:5], 3)}),
            uma5=got(uma, b5), wide5=got(wide, b5)))
    return pd.DataFrame(rows)


def report(e, title):
    inv = dict(trio6=600, trio5=1000, uma5=1000, wide5=1000)
    def s(x):
        r = {"n": len(x), "p1": x.p1_t3.mean() * 100, "win": x.p1_win.mean()}
        for k, v in inv.items():
            r[k] = x[k].sum() / (len(x) * v) * 100
            r[k + "_hit"] = (x[k] > 0).mean() * 100
            r[k + "_ex"] = x[k].drop(x[k].nlargest(3).index).sum() / ((len(x) - 3) * v) * 100
        return r
    a, tr, te = s(e), s(e[e.dt < TRAIN_END]), s(e[e.dt >= TRAIN_END])
    print(f"   {title:<26} n={a['n']:>4} 予想1位3着内 {a['p1']:4.1f}%（{tr['p1']:.1f}/{te['p1']:.1f}） 単勝{a['win']:4.0f}%"
          + "".join(f" | {k} 的中{a[k+'_hit']:4.1f}% ROI{a[k]:4.0f}%（{tr[k]:.0f}/{te[k]:.0f}・除3 {a[k+'_ex']:.0f}）" for k in inv))


def main():
    df = build()
    pays = payouts()
    variants = {
        "G 現行（v3+能力以外）": ["v3_c", "rest_sum"],
        "G+先行": ["v3_c", "rest_sum", "front"],
        "G+巧者": ["v3_c", "rest_sum", "ace"],
        "G+先行+巧者": ["v3_c", "rest_sum", "front", "ace"],
        "G+先行+巧者+先行少": ["v3_c", "rest_sum", "front", "ace", "front_few"],
    }
    evals = {}
    print("■ 学習した重み（〜2025/06）")
    for name, cols in variants.items():
        u, w = B.fit_util(df, cols, 0.5)
        df["r_" + name] = pd.Series(-u, index=df.index).groupby(df["rid"]).rank(method="first")
        evals[name] = evaluate(df, "r_" + name, pays)
        print(f"   {name:<22} {w}")
    for scope, f in (("買い条件（10〜13頭・重賞以外）", lambda e: e[e.n.between(10, 13) & ~e.g]), ("2勝以上 全レース", lambda e: e)):
        print(f"\n■ {scope}   ※（学習/テスト）・除3=上位3件除外")
        for name in variants:
            report(f(evals[name]), name)


if __name__ == "__main__":
    main()
