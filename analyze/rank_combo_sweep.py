"""
三連複の「どの順位を買い目に入れるか」総当たり（2026-09-25）

相手幅のスイープ（連続した2〜N位）では「2〜5位が最良」と分かったが、
「2位や3位を抜いて4〜7位にする」「1位を軸にせず2〜5位のBOXにする」など
飛び飛びの組み合わせは試していない。ここを総当たりする。

軸は予想1位固定（2位軸は的中半減が確認済み）。相手は予想2〜8位から2〜5頭を選ぶ全通り。
「両期間（学習2024/06〜2025/06 / テスト2025/07〜）でともにROI100%超」を合格条件にする。
使い方: python3 analyze/rank_combo_sweep.py
"""
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import strength_profile as S
import market_residual_model as M
import ability_blend_backtest as B
import verify.bet_analysis2 as ba2

TRAIN_END = pd.Timestamp(2025, 7, 1)


def main():
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"])
    m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)
    u, _ = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["rank_G"] = df.assign(u=u).groupby("rid")["u"].rank(ascending=False, method="first")

    rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}
    pay = {}
    for p in (BASE / "cache" / "payouts").glob("*.json"):
        nums, amounts = ba2.get_payout(p.stem, "3連複")
        if amounts and len(nums) >= 3 * len(amounts):
            pay[p.stem] = ([frozenset(nums[3 * k:3 * k + 3]) for k in range(len(amounts))], amounts)

    # レースごとに「予想順位→馬番」と払戻を用意（新しい買い条件: 11〜13頭・重賞以外）
    races = []
    for key, g in df.groupby(["日付", "レース名"]):
        rid = rid_of.get(key)
        if rid not in pay:
            continue
        g = g.sort_values("rank_G")
        if not 11 <= len(g) <= 13 or g["クラス"].iloc[0] == "重賞":
            continue
        races.append({"dt": g["dt"].iloc[0], "nums": [int(x) for x in g["馬番"]], "pay": pay[rid]})
    print(f"対象レース（11〜13頭・重賞以外・払戻あり）: {len(races)}R"
          f"（学習{sum(1 for r in races if r['dt'] < TRAIN_END)} / テスト{sum(1 for r in races if r['dt'] >= TRAIN_END)}）")

    def evaluate(picks, axis=1):
        """picks: 相手にする予想順位のtuple（1始まり）。軸は axis 位"""
        agg = {"n": 0, "hit": 0, "inv": 0, "col": 0}
        half = {"tr": [0, 0], "te": [0, 0]}
        pays = []
        for r in races:
            nums = r["nums"]
            if max(picks + (axis,)) > len(nums):
                continue
            a = nums[axis - 1]
            others = [nums[i - 1] for i in picks]
            bets = {frozenset((a,) + c) for c in combinations(others, 2)}
            combos, amounts = r["pay"]
            got = sum(x for c, x in zip(combos, amounts) if c in bets)
            agg["n"] += 1
            agg["inv"] += 100 * len(bets)
            agg["col"] += got
            agg["hit"] += got > 0
            pays.append(got)
            k = "tr" if r["dt"] < TRAIN_END else "te"
            half[k][0] += 100 * len(bets)
            half[k][1] += got
        if agg["n"] < 60:
            return None
        top3 = sum(sorted(pays, reverse=True)[:3])
        return {"picks": picks, "pts": len(picks) * (len(picks) - 1) // 2, "n": agg["n"],
                "hit": agg["hit"] / agg["n"] * 100, "roi": agg["col"] / agg["inv"] * 100,
                "ex3": (agg["col"] - top3) / agg["inv"] * 100,
                "tr": half["tr"][1] / max(half["tr"][0], 1) * 100,
                "te": half["te"][1] / max(half["te"][0], 1) * 100}

    rows = []
    for size in (2, 3, 4, 5):
        for picks in combinations(range(2, 9), size):
            r = evaluate(picks)
            if r:
                rows.append(r)
    res = pd.DataFrame(rows)
    res["both"] = (res.tr > 100) & (res.te > 100)
    print(f"\n試した組み合わせ: {len(res)}通り  うち両期間100%超: {res.both.sum()}通り")

    print("\n■ ROI上位12（全体）")
    print(f"{'相手の順位':<22}{'点数':>4}{'R数':>5}{'的中率':>8}{'ROI':>7}{'上位3除外':>9}{'学習':>7}{'テスト':>7}")
    for _, r in res.sort_values("roi", ascending=False).head(12).iterrows():
        mark = " ★" if r.both else ""
        print(f"{'-'.join(map(str, r.picks)):<22}{r.pts:>4}{r.n:>5}{r.hit:>7.1f}%{r.roi:>6.0f}%{r.ex3:>8.0f}%{r.tr:>6.0f}%{r.te:>6.0f}%{mark}")

    print("\n■ 両期間100%超のみ（★）を上位3件除外ROIの順に")
    b = res[res.both].sort_values("ex3", ascending=False)
    for _, r in b.head(10).iterrows():
        print(f"{'-'.join(map(str, r.picks)):<22}{r.pts:>4}{r.n:>5}{r.hit:>7.1f}%{r.roi:>6.0f}%{r.ex3:>8.0f}%{r.tr:>6.0f}%{r.te:>6.0f}%")

    print("\n■ 参考: 現行の買い目と、順位を飛ばす代表例")
    for picks in [(2, 3, 4, 5), (2, 3, 4, 5, 6), (2, 3, 4), (4, 5, 6, 7), (2, 4, 5, 6), (3, 4, 5, 6), (2, 3, 6, 7)]:
        r = evaluate(picks)
        if r:
            print(f"{'-'.join(map(str, picks)):<22}{r['pts']:>4}{r['n']:>5}{r['hit']:>7.1f}%{r['roi']:>6.0f}%{r['ex3']:>8.0f}%{r['tr']:>6.0f}%{r['te']:>6.0f}%")


if __name__ == "__main__":
    main()
