"""
「稍重の好走歴」は重・不良の予測に使えるか（2026-09-23）

現行 `check_track_condition` は、重のレースで「稍重で3着内」の馬に +1.0 を与え、
不良のレースでは「稍重を含む道悪の出走歴」があるだけで -1.0 のペナルティを免除している。
稍重そのものに道悪適性のシグナルが無い（2026-09-23検証）以上、この扱いが妥当かを確かめる。

方法（乖離方式・先読みなし）: 芝の重・不良レースでの残差を、
  ① その馬の過去の「重・不良」残差（縮小平均）
  ② その馬の過去の「稍重」残差（縮小平均）
の両方で説明し、②の傾きがゼロなら「稍重の実績は重・不良の予測に無価値」と判定する。
使い方: python3 analyze/soft_going_value.py
"""
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import ability_index_v3 as V

ND = NormalDist()
K = 2.0


def main():
    races = A.load_races()
    going = V.going_map(races)
    print("馬場:", {k: sum(1 for v in going.values() if v == k) for k in ("良", "稍重", "重", "不良", "")})

    obs, hmap, rr = A.build_obs(races, {}, "芝")
    ratings = A.walk_forward(obs, hmap, rr, 365, 2.0, "yr")

    rows = []
    for r in rr:
        g = going.get(r["rid"], "")
        if not g or r["dt"] < A.EVAL_START:
            continue
        n = len(r["ents"])
        th = np.array([ratings.get((e["horse_id"], r["dt"]), (np.nan, 0))[0] for e in r["ents"]])
        if np.isnan(th).mean() > 0.4:
            continue
        thc = np.where(np.isnan(th), np.nanmean(th), th) - np.nanmean(th)
        y = np.array([ND.inv_cdf((n - e["rank"] + 0.5) / n) for e in r["ents"]])
        for e, t, yy, raw in zip(r["ents"], thc, y, th):
            if np.isnan(raw):
                continue
            rows.append({"dt": r["dt"], "rid": r["rid"], "going": g, "hid": e["horse_id"], "y": yy, "thc": t,
                         "rank": e["rank"], "pop": e.get("popularity") or 99})
    df = pd.DataFrame(rows).sort_values("dt").reset_index(drop=True)
    gd = df[df.going == "良"]
    b = float((gd.y * gd.thc).sum() / (gd.thc ** 2).sum())
    df["e"] = df.y - b * df.thc

    # 時系列に「稍重」「重・不良」別の残差を蓄積（同じ日の結果は当日の特徴量に入れない）
    soft, heavy = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    f_soft, f_heavy, n_soft, n_heavy = [], [], [], []
    for dt, grp in df.groupby("dt", sort=True):
        for i, r in grp.iterrows():
            s, h = soft[r.hid], heavy[r.hid]
            f_soft.append(s[1] / (s[0] + K)); n_soft.append(s[0])
            f_heavy.append(h[1] / (h[0] + K)); n_heavy.append(h[0])
        for i, r in grp.iterrows():
            if r.going == "稍重":
                soft[r.hid][0] += 1; soft[r.hid][1] += r.e
            elif r.going in ("重", "不良"):
                heavy[r.hid][0] += 1; heavy[r.hid][1] += r.e
    df["f_soft"], df["f_heavy"] = f_soft, f_heavy
    df["n_soft"], df["n_heavy"] = n_soft, n_heavy

    hv = df[df.going.isin(["重", "不良"])]
    print(f"\n芝の重・不良: {hv['rid'].nunique()}R / {len(hv)}頭")
    print("今回（重・不良）の残差を、過去の実績で説明したときの傾き（0なら無価値）")
    for lab, col, cnt in [("過去の 重・不良 実績", "f_heavy", "n_heavy"), ("過去の 稍重 実績", "f_soft", "n_soft")]:
        d = hv[hv[cnt] >= 1]
        if len(d) < 30:
            print(f"  {lab:<20} n={len(d)} データ不足"); continue
        sl = np.polyfit(d[col], d.e, 1)[0]
        se = np.std(d.e) / (np.std(d[col]) * np.sqrt(len(d)))
        print(f"  {lab:<20} n={len(d):>5}  傾き {sl:+.3f} ± {1.96 * se:.3f}")
    # 両方持つ馬で同時に回帰
    both = hv[(hv.n_heavy >= 1) & (hv.n_soft >= 1)]
    if len(both) >= 30:
        Xb = np.column_stack([both.f_heavy, both.f_soft, np.ones(len(both))])
        coef, *_ = np.linalg.lstsq(Xb, both.e.values, rcond=None)
        print(f"  両方持つ馬 n={len(both)} で同時推定: 重・不良 {coef[0]:+.3f} / 稍重 {coef[1]:+.3f}")

    print("\n稍重の実績で3分割（重・不良レースでの成績）")
    d = hv[hv.n_soft >= 1]
    if len(d) >= 60:
        q = d.f_soft.quantile([0.33, 0.66]).values
        for nm, g in [("稍重で良かった馬", d[d.f_soft >= q[1]]), ("中間", d[(d.f_soft > q[0]) & (d.f_soft < q[1])]),
                      ("稍重で悪かった馬", d[d.f_soft <= q[0]])]:
            print(f"  {nm:<16} n={len(g):>4} 平均残差{g.e.mean():+.3f} 3着内率{(g['rank'] <= 3).mean():.0%} 平均人気{g['pop'].mean():.1f}")

    print("\n参考: 重・不良レースでの「道悪未経験（稍重含む出走なし）」の成績")
    for lab, sel in [("道悪の出走歴なし", (hv.n_soft == 0) & (hv.n_heavy == 0)), ("稍重のみ経験", (hv.n_soft >= 1) & (hv.n_heavy == 0)),
                     ("重・不良の経験あり", hv.n_heavy >= 1)]:
        g = hv[sel]
        if len(g) >= 20:
            print(f"  {lab:<18} n={len(g):>5} 平均残差{g.e.mean():+.3f} 3着内率{(g['rank'] <= 3).mean():.0%} 平均人気{g['pop'].mean():.1f}")


if __name__ == "__main__":
    main()
