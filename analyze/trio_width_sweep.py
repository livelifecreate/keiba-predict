"""
三連複「1軸-相手」の相手幅スイープ（2026-09-22）

「予想ランキングの何位まで紐に入れるべきか」を総当たりで出す。
軸＝予想1位、相手＝予想2位〜(N+1)位（C(N,2)点）を N=2..9 で比較。
順位づけは現行運用の案D（能力指数v2＋能力以外の因子）。比較用に現行スコア(A)と市場人気順も出す。

評価: 的中率・ROI・前後半の再現性・高配当上位3件を除いたROI。1点100円。払戻は cache/payouts。
使い方: python3 analyze/trio_width_sweep.py
"""
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M
import ability_blend_backtest as B
import verify.bet_analysis2 as ba2

TRAIN_END = pd.Timestamp(2025, 7, 1)
SPLIT = pd.Timestamp(2026, 1, 1)


def payout_map():
    """{race_id: (馬番の組リスト, 払戻リスト)}"""
    out = {}
    for p in (BASE / "cache" / "payouts").glob("*.json"):
        nums, amounts = ba2.get_payout(p.stem, "3連複")
        if amounts and len(nums) >= 3 * len(amounts):
            out[p.stem] = ([frozenset(nums[3 * k:3 * k + 3]) for k in range(len(amounts))], amounts)
    return out


def sweep(df, rank_col, label, pay, rid_of, sub=None, axis_rank=1):
    d = df if sub is None else df[sub]
    res = []
    for width in range(2, 10):
        n = hit = inv = col = 0
        halves = {"前": [0, 0, 0], "後": [0, 0, 0]}
        pays = []
        for key, g in d.groupby(["日付", "レース名"]):
            rid = rid_of.get(key)
            if rid not in pay or len(g) < width + 1:
                continue
            g = g.sort_values(rank_col)
            axis = int(g["馬番"].iloc[axis_rank - 1])
            others = [int(x) for x in g["馬番"].iloc[axis_rank:axis_rank + width]]
            bets = {frozenset((axis,) + c) for c in combinations(others, 2)}
            combos, amounts = pay[rid]
            got = sum(a for c, a in zip(combos, amounts) if c in bets)
            n += 1
            inv += 100 * len(bets)
            col += got
            hit += got > 0
            pays.append(got)
            h = "前" if g["dt"].iloc[0] < SPLIT else "後"
            halves[h][0] += 1
            halves[h][1] += 100 * len(bets)
            halves[h][2] += got
        if n == 0:
            continue
        top3 = sum(sorted(pays, reverse=True)[:3])
        res.append({"width": width, "pts": width * (width - 1) // 2, "n": n, "hit": hit / n * 100,
                    "roi": col / inv * 100, "roi_ex3": (col - top3) / inv * 100,
                    "roi_前": halves["前"][2] / max(halves["前"][1], 1) * 100,
                    "roi_後": halves["後"][2] / max(halves["後"][1], 1) * 100})
    print(f"\n--- {label} ---")
    print(f"{'相手':>4}{'点数':>5}{'R数':>6}{'的中率':>8}{'ROI':>7}{'上位3除外':>9}{'2025後半':>9}{'2026':>7}")
    for r in res:
        print(f"2〜{r['width'] + 1:<2}{r['pts']:>5}{r['n']:>6}{r['hit']:>7.1f}%{r['roi']:>6.0f}%{r['roi_ex3']:>8.0f}%{r['roi_前']:>8.0f}%{r['roi_後']:>6.0f}%")
    return res


def main():
    df, factors = M.load()
    df = B.attach_v2(df)
    rest = [c for c in factors if c not in B.ABILITY_FACTORS]
    df["rest_sum"] = df[rest].sum(axis=1)
    u, w = B.fit_util(df, ["v2_c", "rest_sum"], 0.5)
    df["u_D"] = u
    df["rank_D"] = df.groupby("rid")["u_D"].rank(ascending=False, method="first")
    df["_a"] = df["予想スコア"].astype(float)
    df["_m"] = df["市場人気"].astype(float)
    df["rank_A"] = df.groupby("rid")["_a"].rank(ascending=False, method="first")
    df["rank_M"] = df.groupby("rid")["_m"].rank(method="first")
    print("案Dの重み:", w)

    pay = payout_map()
    races = ba2.load_races()
    rid_of = {r["key"]: r["race_id"] for r in races}
    te = df[df.dt >= TRAIN_END]
    print(f"払戻データのあるレース: {len(pay)}  テスト対象: {te['rid'].nunique()}R")

    print("\n===== 予想順位ごとの複勝率（案D・テスト2025/07〜）=====")
    for k in range(1, 11):
        g = te[te["rank_D"] == k]
        if len(g) > 50:
            print(f"  {k:>2}位  n={len(g):>5}  複勝率{(g['実着順'] <= 3).mean():>6.1%}  勝率{(g['実着順'] == 1).mean():>6.1%}  平均人気{g['市場人気'].astype(float).mean():>4.1f}")

    target = te["クラス"].isin(["3勝クラス", "OP"])
    sweep(te, "rank_D", "案D・全クラス（2勝以上）", pay, rid_of)
    sweep(te, "rank_D", "案D・3勝/OPのみ（現行の買い対象）", pay, rid_of, target)
    sweep(te, "rank_A", "現行スコア・全クラス", pay, rid_of)
    sweep(te, "rank_M", "市場人気順・全クラス（参考）", pay, rid_of)
    sweep(te, "rank_D", "案D・軸を予想2位にした場合（参考）", pay, rid_of, axis_rank=2)


if __name__ == "__main__":
    main()
