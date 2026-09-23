"""
「ダート適性のある馬は芝の道悪でも走る」は本当か（2026-09-22）

検証方法（乖離方式・先読みなし）:
  芝のレースで 残差 e = 実際の相対パフォーマンス − 芝の能力指数から期待される値 を計算し、
  「ダート適性」= その馬のダート能力指数θ_ダ − 芝能力指数θ_芝（レース日より前のデータのみ）
  との関係を、馬場状態（良 / 稍重 / 重・不良）別に見る。
  説が正しければ「重・不良でだけ、ダート寄りの馬の残差がプラス」になるはず。
  対照として良馬場でも同じ傾きが出るなら、それは道悪と無関係（単にダートが強い馬は芝でも強い等）。

馬場は cache/horse_full_history の4区分（稍重・重・不良）を優先し、無ければ race_result の2値を使う。
使い方: python3 analyze/dirt_on_wet_turf.py
"""
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import wet_track_calibration as WET

BASE = Path(__file__).resolve().parent.parent
ND = NormalDist()


def main():
    import json
    races = A.load_races()
    full = WET.going_from_full_history()
    venue = {}
    fallback = {}
    for p in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(p.read_text())
        rid = d.get("race_id") or p.stem
        venue[rid] = d.get("venue") or ""
        fallback[rid] = WET.NORM.get(d.get("track_condition") or "", "")
    going = {}
    for r in races:
        g = full.get((r["dt"], venue.get(r["rid"], ""), r["surface"])) if full else None
        going[r["rid"]] = g or fallback.get(r["rid"], "")
    print("馬場の内訳:", {k: sum(1 for v in going.values() if v == k) for k in ("良", "稍重", "重", "不良", "")})

    # 芝・ダートそれぞれの能力指数（開催日ごと・先読みなし）
    ratings = {}
    for s in ("芝", "ダ"):
        obs, hmap, rr = A.build_obs(races, {}, s)
        ratings[s] = A.walk_forward(obs, hmap, rr, 365, 2.0, "yr")

    # 馬ごとのダート能力の時系列（日付順）→ 芝レース当日より前の最新値を引く
    dirt_series = defaultdict(list)
    for (hid, dt), (th, W) in ratings["ダ"].items():
        if not np.isnan(th):
            dirt_series[hid].append((dt, th, W))
    for v in dirt_series.values():
        v.sort()

    def dirt_as_of(hid, dt):
        v = dirt_series.get(hid)
        if not v:
            return np.nan, 0.0
        lo, hi = 0, len(v)
        while lo < hi:                       # dt より前の最後の要素を二分探索
            mid = (lo + hi) // 2
            if v[mid][0] < dt:
                lo = mid + 1
            else:
                hi = mid
        return (v[lo - 1][1], v[lo - 1][2]) if lo > 0 else (np.nan, 0.0)

    rows = []
    for r in races:
        if r["surface"] != "芝" or r["dt"] < A.EVAL_START:
            continue
        g = going.get(r["rid"], "")
        if not g:
            continue
        n = len(r["ents"])
        th = np.array([ratings["芝"].get((e["horse_id"], r["dt"]), (np.nan, 0))[0] for e in r["ents"]])
        if np.isnan(th).mean() > 0.4:
            continue
        thc = np.where(np.isnan(th), np.nanmean(th), th) - np.nanmean(th)
        y = np.array([ND.inv_cdf((n - e["rank"] + 0.5) / n) for e in r["ents"]])
        for e, t, yy, raw in zip(r["ents"], thc, y, th):
            if np.isnan(raw):
                continue
            dth, dW = dirt_as_of(e["horse_id"], r["dt"])
            rows.append({"rid": r["rid"], "dt": r["dt"], "cls": r["cls"], "going": g, "y": yy, "thc": t,
                         "rank": e["rank"], "pop": e.get("popularity") or 99, "odds": e.get("odds") or 0,
                         "馬名": e["horse_name"], "dirt": dth, "dirt_n": dW, "turf_raw": raw})
    df = pd.DataFrame(rows)
    good = df[df.going == "良"]
    b = float((good.y * good.thc).sum() / (good.thc ** 2).sum())
    df["e"] = df["y"] - b * df["thc"]
    df["has_dirt"] = df["dirt_n"] >= 1.0
    # ダート適性 = ダート能力 − 芝能力（どちらも同じ尺度）。レース内で中心化
    df["gap"] = df["dirt"] - df["turf_raw"]
    m = df.groupby("rid")["gap"].transform("mean")
    df["gap_c"] = (df["gap"] - m).where(df["has_dirt"])
    print(f"期待値の係数 b={b:.3f}  芝の対象 {len(df)}頭  うちダート経験あり {df['has_dirt'].mean():.0%}")

    print("\n===== 「ダート寄りの馬」の残差（芝レース・馬場別）=====")
    print(f"{'馬場':<8}{'頭数':>7}{'傾き':>8}   ダート寄り上位25% / 中間 / 下位25% の平均残差・3着内率")
    for lab, sel in [("良", df.going == "良"), ("稍重", df.going == "稍重"), ("重・不良", df.going.isin(["重", "不良"]))]:
        d = df[sel & df.has_dirt & df.gap_c.notna()]
        if len(d) < 50:
            print(f"{lab:<8}{len(d):>7}  データ不足"); continue
        sl = np.polyfit(d.gap_c, d.e, 1)[0]
        q = d.gap_c.quantile([0.25, 0.75]).values
        parts = []
        for nm, g in [("上位", d[d.gap_c >= q[1]]), ("中間", d[(d.gap_c > q[0]) & (d.gap_c < q[1])]), ("下位", d[d.gap_c <= q[0]])]:
            parts.append(f"{nm} {g.e.mean():+.3f}/{(g['rank'] <= 3).mean():.0%}(n={len(g)})")
        print(f"{lab:<8}{len(d):>7}{sl:>+8.3f}   " + "  ".join(parts))

    print("\n===== 参考: ダート経験の有無そのもの（芝レース・馬場別の平均残差）=====")
    for lab, sel in [("良", df.going == "良"), ("稍重", df.going == "稍重"), ("重・不良", df.going.isin(["重", "不良"]))]:
        d = df[sel]
        a, bb = d[d.has_dirt], d[~d.has_dirt]
        if len(a) < 30 or len(bb) < 30:
            continue
        print(f"  {lab:<8} ダート経験あり n={len(a):>5} 残差{a.e.mean():+.3f} 3着内率{(a['rank'] <= 3).mean():.0%} 平均人気{a['pop'].mean():.1f}"
              f" / なし n={len(bb):>5} 残差{bb.e.mean():+.3f} 3着内率{(bb['rank'] <= 3).mean():.0%} 平均人気{bb['pop'].mean():.1f}")


if __name__ == "__main__":
    main()
