"""
着差入り能力指数で「的中率は上がるが回収率は上がらない」理由の確認（2026-10-05）

margin_blend_test.py の2案（着順のみ／着順+秒差・どちらも巧者入りの案G 3変数）で、
 ① 予想1位・上位5頭の平均人気（人気寄りに動いたか）
 ② 1回当たったときの平均配当（安い当たりが増えたか）
 ③ 上位5頭が入れ替わったレースだけで見た的中・配当（差がどこから来るか）
 ④ 的中数の差が偶然の範囲か（レースごとの対応ありの差・符号検定）
を出す。対象は2勝以上全レースと買い条件（10〜13頭・重賞以外）。
使い方: python3 analyze/margin_blend_why.py
"""
import sys
from itertools import combinations
from math import comb
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import ability_index_v3 as V
import ability_margin_test as M
import front_ace_blend_test as FA
import ability_blend_backtest as B
from margin_blend_test import theta_table

KINDS = {"trio6": 600, "trio5": 1000, "uma5": 1000, "wide5": 1000}


def per_race(df, rank_col, pays):
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
        rows.append(dict(key=key, dt=t["dt"], n=len(g), g=t["クラス"] == "重賞",
                         pop1=float(t["市場人気"]), pop5=g["市場人気"].iloc[:5].astype(float).mean(),
                         top5=frozenset(nums[:5]), top1=nums[0],
                         trio6=got(trio, {frozenset((nums[0],) + c) for c in combinations(nums[1:5], 2)}),
                         trio5=got(trio, {frozenset(c) for c in combinations(nums[:5], 3)}),
                         uma5=got(uma, b5), wide5=got(wide, b5)))
    return pd.DataFrame(rows).set_index("key")


def sign_p(a, b):
    """片方だけ当たったレース数 a, b の両側符号検定"""
    n = a + b
    if n == 0: return 1.0
    k = min(a, b)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def report(r0, r1, title):
    r1 = r1.loc[r0.index.intersection(r1.index)]; r0 = r0.loc[r1.index]
    print(f"\n■ {title}（n={len(r0)}）")
    print(f"   平均人気  予想1位 {r0.pop1.mean():.2f} → {r1.pop1.mean():.2f} / 上位5頭 {r0.pop5.mean():.2f} → {r1.pop5.mean():.2f}")
    chg1 = (r0.top1 != r1.top1); chg5 = (r0.top5 != r1.top5)
    print(f"   予想1位が替わったレース {chg1.sum()}（{chg1.mean():.0%}） / 上位5頭の顔ぶれが替わったレース {chg5.sum()}（{chg5.mean():.0%}）")
    for k, inv in KINDS.items():
        h0, h1 = r0[k] > 0, r1[k] > 0
        a, b = int((h0 & ~h1).sum()), int((~h0 & h1).sum())
        avg0 = r0.loc[h0, k].mean() if h0.any() else 0; avg1 = r1.loc[h1, k].mean() if h1.any() else 0
        print(f"   {k:<6} 的中 {h0.sum()}→{h1.sum()}  平均配当 {avg0:,.0f}→{avg1:,.0f}円  ROI {r0[k].sum()/(len(r0)*inv)*100:.0f}→{r1[k].sum()/(len(r1)*inv)*100:.0f}%"
              f"  | 現行だけ的中{a} / 着差版だけ的中{b}（符号検定 p={sign_p(a, b):.2f}）"
              f"  | 片方だけ的中の配当合計 現行{r0.loc[h0 & ~h1, k].sum():,.0f} / 着差版{r1.loc[~h0 & h1, k].sum():,.0f}円")


def main():
    races = A.load_races()
    prevs, going, sires = V.prev_map(), V.going_map(races), V.sire_map()
    margins = M.load_margins()
    base = FA.build()
    pays = FA.payouts()
    res = []
    for alpha in (0.0, 0.5):
        th = theta_table(alpha, races, prevs, going, sires, margins)
        df = base.copy()
        v = df.join(th.rename("v3n"), on=["馬名", "dt"])["v3n"]
        m = v.groupby(df["rid"]).transform("mean")
        df["v3_c"] = (v.fillna(m) - m).fillna(0.0)
        u, w = B.fit_util(df, ["v3_c", "rest_sum", "ace"], 0.5)
        df["r"] = pd.Series(-u, index=df.index).groupby(df["rid"]).rank(method="first")
        res.append(per_race(df, "r", pays))
    r0, r1 = res
    report(r0, r1, "2勝以上 全レース")
    f = lambda e: e[e.n.between(10, 13) & ~e.g]
    report(f(r0), f(r1), "買い条件（10〜13頭・重賞以外）")


if __name__ == "__main__":
    main()
