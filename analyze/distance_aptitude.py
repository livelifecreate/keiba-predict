"""
距離別能力指数は成立するか（2026-09-26）

問題意識: 能力指数θは芝ダ別までしか分けておらず、1200mの馬も2400mの馬も同じ「芝の能力」1つ。
  「この馬は1600mに絞れば上位」という距離適性が独立して存在するなら、指数に足す価値がある。

検証（乖離方式・先読みなし。7月に却下した4指数と同じ作法）:
  残差 e = 実際の相対成績 − 能力指数から期待される成績
  その馬の「過去の同距離帯での残差（縮小平均）」が、今回の同距離帯レースの残差を予測するか。
  対照 ①他距離帯での残差 → 今回（単なる好不調の持ち越し）
       ②同距離帯での残差 → 他距離帯のレース（距離固有でないなら同じだけ効く）
  距離帯は 〜1400 / 1500-1700 / 1800-2000 / 2100〜 の4区分（芝ダ別）。

さらに ③「前走からの距離変化」との違いも見る（v3には距離延長-0.192/短縮+0.069として既に入っている）。
使い方: python3 analyze/distance_aptitude.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A

ND = NormalDist()
TRAIN_END = pd.Timestamp(2025, 7, 1)
K = 2.0


def band(dist: int) -> str:
    return "〜1400" if dist <= 1400 else "1500-1700" if dist <= 1700 else "1800-2000" if dist <= 2000 else "2100〜"


def main():
    races = A.load_races()
    ratings = {}
    for s in ("芝", "ダ"):
        obs, hmap, rr = A.build_obs(races, {}, s)
        ratings.update(A.walk_forward(obs, hmap, rr, 365, 2.0, "yr"))

    rows = []
    for r in races:
        if r["dt"] < A.EVAL_START:
            continue
        n = len(r["ents"])
        th = np.array([ratings.get((e["horse_id"], r["dt"]), (np.nan, 0))[0] for e in r["ents"]])
        if np.isnan(th).mean() > 0.4:
            continue
        thc = np.where(np.isnan(th), np.nanmean(th), th) - np.nanmean(th)
        y = np.array([ND.inv_cdf((n - e["rank"] + 0.5) / n) for e in r["ents"]])
        b = band(r["dist"])
        for e, t, yy, raw in zip(r["ents"], thc, y, th):
            if np.isnan(raw):
                continue
            rows.append({"dt": r["dt"], "rid": r["rid"], "hid": e["horse_id"], "surface": r["surface"],
                         "band": b, "dist": r["dist"], "y": yy, "thc": t, "rank": e["rank"],
                         "pop": e.get("popularity") or 99, "cls": r["cls"]})
    df = pd.DataFrame(rows).sort_values("dt").reset_index(drop=True)
    tr = df[df.dt < TRAIN_END]
    coef = float((tr.y * tr.thc).sum() / (tr.thc ** 2).sum())
    df["e"] = df.y - coef * df.thc
    print(f"対象 {len(df):,}頭 / {df.rid.nunique():,}R  期待値の係数 b={coef:.3f}")
    print("距離帯の内訳:", dict(df.band.value_counts()))

    # 時系列に「同距離帯」「他距離帯」の残差を蓄積（同日のレースは当日の特徴量に入れない）
    same, other = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0])
    f_same, f_other, n_same, n_other = [], [], [], []
    for dt, grp in df.groupby("dt", sort=True):
        for i, r in grp.iterrows():
            ks, ko = (r.hid, r.surface, r.band), (r.hid, r.surface)
            s, o = same[ks], other[ko]
            f_same.append(s[1] / (s[0] + K)); n_same.append(s[0])
            # 他距離帯 = その馬の全走から同距離帯ぶんを引く
            f_other.append((o[1] - s[1]) / max(o[0] - s[0], 0) if o[0] - s[0] > 0 else 0.0)
            n_other.append(o[0] - s[0])
        for i, r in grp.iterrows():
            same[(r.hid, r.surface, r.band)][0] += 1
            same[(r.hid, r.surface, r.band)][1] += r.e
            other[(r.hid, r.surface)][0] += 1
            other[(r.hid, r.surface)][1] += r.e
    df["f_same"], df["f_other"] = f_same, f_other
    df["n_same"], df["n_other"] = n_same, n_other

    te = df[df.dt >= TRAIN_END]

    def slope(d, col):
        d = d[d[col].notna()]
        if len(d) < 200:
            return None
        X = np.column_stack([d[col], np.ones(len(d))])
        cf, *_ = np.linalg.lstsq(X, d.e.values, rcond=None)
        res = d.e.values - X @ cf
        se = np.sqrt(np.sum(res ** 2) / (len(d) - 2) * np.linalg.inv(X.T @ X)[0, 0])
        return cf[0], 1.96 * se, len(d)

    print("\n■ 今回の残差を、過去の残差で説明したときの傾き（テスト期間・±は95%区間）")
    for lab, d, col in [("同じ距離帯の実績 → 今回（本命）", te[te.n_same >= 1], "f_same"),
                        ("他の距離帯の実績 → 今回（対照：好不調）", te[te.n_other >= 1], "f_other"),
                        ("同じ距離帯の実績 → 他距離帯のレース（対照）", None, None)]:
        if d is None:
            continue
        r = slope(d, col)
        if r:
            print(f"  {lab:<36} 傾き {r[0]:+.3f} ± {r[1]:.3f}  n={r[2]:,}")
    # 対照②: 「別の距離帯での実績」を今回に当てはめる（馬×芝ダごとに事前集約して高速化）
    by_horse = defaultdict(dict)
    for (h, s, b), v in same.items():
        if v[0] >= 1:
            by_horse[(h, s)][b] = v[1] / (v[0] + K)
    alt = [np.mean([x for bb, x in by_horse.get((h, s), {}).items() if bb != b]) if
           [x for bb, x in by_horse.get((h, s), {}).items() if bb != b] else np.nan
           for h, s, b in zip(te.hid, te.surface, te.band)]
    te = te.assign(f_altband=alt)
    r = slope(te[te.f_altband.notna()], "f_altband")
    if r:
        print(f"  {'別の距離帯の実績 → 今回（対照）':<36} 傾き {r[0]:+.3f} ± {r[1]:.3f}  n={r[2]:,}")

    print("\n■ 同じ距離帯での実績で3分割（テスト期間・その距離帯を1走以上経験）")
    d = te[te.n_same >= 1]
    q = d.f_same.quantile([0.33, 0.66]).values
    for lab, g in [("その距離で走れている", d[d.f_same >= q[1]]), ("中間", d[(d.f_same > q[0]) & (d.f_same < q[1])]),
                   ("その距離で走れていない", d[d.f_same <= q[0]])]:
        print(f"  {lab:<22} n={len(g):>5} 平均残差{g.e.mean():+.3f} 3着内率{(g['rank'] <= 3).mean():>5.1%} 平均人気{g['pop'].mean():.1f}")

    print("\n■ 経験本数別（同じ距離帯を何走しているか）")
    for lo, hi, lab in [(1, 1, "1走"), (2, 3, "2〜3走"), (4, 6, "4〜6走"), (7, 99, "7走以上")]:
        g = te[(te.n_same >= lo) & (te.n_same <= hi)]
        r = slope(g, "f_same")
        if r:
            print(f"  {lab:<8} 傾き {r[0]:+.3f} ± {r[1]:.3f}  n={r[2]:,}")


if __name__ == "__main__":
    main()
