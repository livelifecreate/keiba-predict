"""
馬単・三連単の買い方スイープ（2026-09-24）

これまで検証していなかった2券種（控除率27.5%・単複より高い）を、案Gの順位で総当たりする。
軸は予想1位で確定済み（三連複の検証で2位軸は的中半減）。

評価: 的中率・ROI・高配当上位3件を除いたROI・前後半の再現性。1点100円。払戻は cache/payouts（着順どおりの並び）。
使い方: python3 analyze/exacta_trifecta_sweep.py
"""
import sys, tempfile
from itertools import combinations, permutations
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


def payouts():
    """{race_id: {券種: (着順どおりの馬番tuple, 払戻)}}"""
    out = {}
    for p in (BASE / "cache" / "payouts").glob("*.json"):
        rid = p.stem
        d = {}
        for bt, size in (("馬単", 2), ("3連単", 3)):
            nums, amounts = ba2.get_payout(rid, bt)
            if amounts and len(nums) >= size:
                d[bt] = (tuple(nums[:size]), amounts[0])
        if d:
            out[rid] = d
    return out


# 買い方: 予想順位（1始まり）のリストを受け取り、買う組み合わせ（順序つきtuple）を返す
FORMS_EXACTA = {
    "馬単 1→2 (1点)":            lambda r: [(r[0], r[1])],
    "馬単 1⇄2 表裏 (2点)":        lambda r: [(r[0], r[1]), (r[1], r[0])],
    "馬単 1→2,3 (2点)":          lambda r: [(r[0], x) for x in r[1:3]],
    "馬単 1→2〜4 (3点)":          lambda r: [(r[0], x) for x in r[1:4]],
    "馬単 1→2〜5 (4点)":          lambda r: [(r[0], x) for x in r[1:5]],
    "馬単 1→2〜6 (5点)":          lambda r: [(r[0], x) for x in r[1:6]],
    "馬単 1,2着に1位 ×2〜4 (6点)": lambda r: [(r[0], x) for x in r[1:4]] + [(x, r[0]) for x in r[1:4]],
}
FORMS_TRIFECTA = {
    "三連単 1→2→3 (1点)":          lambda r: [(r[0], r[1], r[2])],
    "三連単 1着固定×2〜4 (6点)":     lambda r: [(r[0],) + p for p in permutations(r[1:4], 2)],
    "三連単 1着固定×2〜5 (12点)":    lambda r: [(r[0],) + p for p in permutations(r[1:5], 2)],
    "三連単 1着固定×2〜6 (20点)":    lambda r: [(r[0],) + p for p in permutations(r[1:6], 2)],
    "三連単 1-2位の表裏×3〜5 (6点)": lambda r: [(a, b, c) for a, b in ((r[0], r[1]), (r[1], r[0])) for c in r[2:5]],
    "三連単 A+B (24点・現行)":       lambda r: ([(r[0],) + p for p in permutations(r[1:5], 2)]
                                              + [(a, r[0], c) for a, c in permutations(r[1:5], 2)]),
    "三連単 1,2着に1-2位×3着2〜6(8点)": lambda r: [(a, b, c) for a, b in ((r[0], r[1]), (r[1], r[0]))
                                                for c in r[2:6] if c not in (a, b)],
}


def run(df, pay, rid_of, forms, bet_type, label, sub=None):
    d = df if sub is None else df[sub]
    print(f"\n--- {label} ---")
    print(f"{'買い方':<30}{'R数':>6}{'的中率':>8}{'ROI':>7}{'上位3除外':>9}{'2025後半':>9}{'2026':>7}")
    for name, f in forms.items():
        n = hit = inv = col = 0
        halves = {"前": [0, 0], "後": [0, 0]}
        pays = []
        for key, g in d.groupby(["日付", "レース名"]):
            rid = rid_of.get(key)
            if rid not in pay or bet_type not in pay[rid] or len(g) < 6:
                continue
            g = g.sort_values("rank_G")
            nums = [int(x) for x in g["馬番"]]
            bets = set(f(nums))
            win, amt = pay[rid][bet_type]
            got = amt if win in bets else 0
            n += 1
            inv += 100 * len(bets)
            col += got
            hit += got > 0
            pays.append(got)
            h = "前" if g["dt"].iloc[0] < SPLIT else "後"
            halves[h][0] += 100 * len(bets)
            halves[h][1] += got
        if n == 0:
            continue
        top3 = sum(sorted(pays, reverse=True)[:3])
        print(f"{name:<30}{n:>6}{hit / n * 100:>7.1f}%{col / inv * 100:>6.0f}%{(col - top3) / inv * 100:>8.0f}%"
              f"{halves['前'][1] / max(halves['前'][0], 1) * 100:>8.0f}%{halves['後'][1] / max(halves['後'][0], 1) * 100:>6.0f}%")


def main():
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"])
    m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    rest = [c for c in factors if c not in B.ABILITY_FACTORS]
    df["rest_sum"] = df[rest].sum(axis=1)
    u, w = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["u_G"] = u
    df["rank_G"] = df.groupby("rid")["u_G"].rank(ascending=False, method="first")
    df["_m"] = df["市場人気"].astype(float)
    print("案Gの重み:", w)

    pay = payouts()
    rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}
    te = df[df.dt >= TRAIN_END]
    print(f"払戻あり: {len(pay)}R  テスト: {te['rid'].nunique()}R")

    run(te, pay, rid_of, FORMS_EXACTA, "馬単", "馬単・全クラス（2勝以上）")
    run(te, pay, rid_of, FORMS_TRIFECTA, "3連単", "三連単・全クラス（2勝以上）")
    target = te["クラス"].isin(["3勝クラス", "OP"])
    run(te, pay, rid_of, FORMS_EXACTA, "馬単", "馬単・3勝/OPのみ", target)
    run(te, pay, rid_of, FORMS_TRIFECTA, "3連単", "三連単・3勝/OPのみ", target)
    # 参考: 市場人気順で同じ買い方
    te2 = te.copy()
    te2["rank_G"] = te2.groupby("rid")["_m"].rank(method="first")
    run(te2, pay, rid_of, FORMS_EXACTA, "馬単", "馬単・市場人気順（参考）")
    run(te2, pay, rid_of, FORMS_TRIFECTA, "3連単", "三連単・市場人気順（参考）")


if __name__ == "__main__":
    main()
