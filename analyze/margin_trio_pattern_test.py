"""
秒差版の能力指数で、三連複の相手を「人気になりやすい順位を飛ばす」買い方に替えるとROIが戻るか（2026-10-05）

仮説（ユーザー）: 秒差版は順位が正確だが人気寄りになるので、相手を 2〜5位 ではなく
  2-3-4-5-7 や 3-4-5-6-7 のように替えれば穴を拾えてROIが上がる。
多重比較を避けるため、指数2種 × 買い目5通りを事前に固定して比べる。
  指数: 着順のみ（現行）/ 秒差のみ・1秒頭打ち（いずれも案G 3変数に入れて重みを〜2025/06で学習）
  買い目（軸=予想1位）: 2345(6点・現行) / 3456(6点) / 23457(10点) / 34567(10点) / 23456(10点)
合格: 学習・テスト両期間でROI>100% かつ 上位3件除外でも現行（着順のみ×2345）を上回る。
使い方: python3 analyze/margin_trio_pattern_test.py
"""
import sys
from itertools import combinations
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import ability_index_v3 as V
import ability_margin_test as M
import front_ace_blend_test as FA
import ability_blend_backtest as B
from margin_alpha_sweep import estimate

PATTERNS = {"2345": [2, 3, 4, 5], "3456": [3, 4, 5, 6], "23457": [2, 3, 4, 5, 7], "34567": [3, 4, 5, 6, 7], "23456": [2, 3, 4, 5, 6]}


def per_race(df, pays):
    trio = pays[0]
    rows = []
    for key, g in df.groupby(["日付", "レース名"]):
        if key not in trio: continue
        g = g.sort_values("r")
        nums = [int(x) for x in g["馬番"]]
        if len(set(nums)) != len(nums) or len(nums) < 8: continue
        pops = [float(x) for x in g["市場人気"]]
        c, a = trio[key]
        t = g.iloc[0]
        row = dict(dt=t["dt"], n=len(g), g=t["クラス"] == "重賞")
        for name, ranks in PATTERNS.items():
            partners = [nums[k - 1] for k in ranks]
            bets = {frozenset((nums[0],) + p) for p in combinations(partners, 2)}
            row[name] = sum(x for cc, x in zip(c, a) if cc in bets)
            row[name + "_pts"] = len(bets)
            row[name + "_pop"] = np.mean([pops[k - 1] for k in ranks])
        rows.append(row)
    return pd.DataFrame(rows)


def stats(e, name):
    inv = e[name + "_pts"] * 100
    roi = lambda x, i: x.sum() / i.sum() * 100 if i.sum() else 0
    pay = e[name]
    top3 = pay.nlargest(3).index
    tr, te = e.dt < FA.TRAIN_END, e.dt >= FA.TRAIN_END
    return dict(hit=(pay > 0).mean() * 100, roi=roi(pay, inv), tr=roi(pay[tr], inv[tr]), te=roi(pay[te], inv[te]),
                ex3=roi(pay.drop(top3), inv.drop(top3)), pop=e[name + "_pop"].mean(),
                per=(pay.sum() - inv.sum()) / len(e))


def main():
    races = A.load_races()
    prevs, going, sires = V.prev_map(), V.going_map(races), V.sire_map()
    margins = M.load_margins()
    base = FA.build()
    pays = FA.payouts()
    res = {}
    for alpha, cap, lab in ((0.0, 2.0, "着順のみ（現行）"), (1.0, 1.0, "秒差のみ・1秒")):
        _, tab = estimate(alpha, cap, races, prevs, going, sires, margins)
        df = base.copy()
        v = df.join(tab.rename("v3n"), on=["馬名", "dt"])["v3n"]
        m = v.groupby(df["rid"]).transform("mean")
        df["v3_c"] = (v.fillna(m) - m).fillna(0.0)
        u, w = B.fit_util(df, ["v3_c", "rest_sum", "ace"], 0.5)
        df["r"] = pd.Series(-u, index=df.index).groupby(df["rid"]).rank(method="first")
        res[lab] = per_race(df, pays)
        print(f"[済] {lab} 重み{w}", flush=True)
    for scope, f in (("買い条件（10〜13頭・重賞以外）", lambda e: e[e.n.between(10, 13) & ~e.g]), ("2勝以上 全レース（8頭以上）", lambda e: e)):
        print(f"\n■ {scope}")
        print("   指数             買い目  点数 | n    的中率  ROI（学習/テスト） 上位3除外  1R収支  相手の平均人気")
        for lab, e in res.items():
            e = f(e)
            for name in PATTERNS:
                s = stats(e, name)
                print(f"   {lab:<14} {name:<6} {e[name + '_pts'].iloc[0]:>3}点 | {len(e):<4} {s['hit']:5.1f}%  {s['roi']:4.0f}%（{s['tr']:.0f}/{s['te']:.0f}）"
                      f"   {s['ex3']:4.0f}%   {s['per']:+5.0f}円   {s['pop']:.1f}")


if __name__ == "__main__":
    main()
