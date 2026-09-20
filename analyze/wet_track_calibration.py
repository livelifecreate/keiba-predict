"""
道悪適性の数値化・予備キャリブレーション（2026-09-20）

考え方: 能力指数v2から「このメンバーならこの程度走る」期待値が出る。
  残差 e = 実際の相対パフォーマンス(着順の正規スコア) − 期待値(θ_i − レース平均θ)
  を 良馬場 / 道悪 に分けて馬ごとに蓄積し、
  「過去の道悪残差（縮小平均）」が「次の道悪レースの残差」を予測するかを見る（乖離方式・先読みなし）。
  対照として ①過去の良馬場残差→道悪（単なる好不調の持ち越し） ②過去の道悪残差→良馬場（道悪固有でないなら同じだけ効く）も出す。
  血統: 父馬の産駒全体の道悪残差（縮小平均）でも同じ検証をする。

データの制約: cache/race_result の track_condition は「良/重」の2値で33%が欠損（稍重・不良の区別なし）。
  通算成績（9/22-23取得予定・馬場4区分つき）が入れば再検証する。ここでは良 vs 重 の予備検証。
使い方: python3 analyze/wet_track_calibration.py
"""
import json, sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A

BASE = Path(__file__).resolve().parent.parent
K_HORSE, K_SIRE = 2.0, 30.0
ND = NormalDist()


def main():
    races = A.load_races()
    tc = {}
    for p in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(p.read_text())
        tc[d.get("race_id") or p.stem] = d.get("track_condition") or ""
    sire = {}
    for p in (BASE / "cache" / "sire").glob("*.json"):
        try:
            v = json.loads(p.read_text())
            sire[p.stem] = v if isinstance(v, str) else (v.get("sire") or v.get("name") or "")
        except Exception:
            pass
    print(f"馬場状態: 良 {sum(v == '良' for v in tc.values())}R / 重 {sum(v == '重' for v in tc.values())}R / 不明 {sum(v == '' for v in tc.values())}R   父馬データ {len(sire)}頭")

    ratings = {}
    for s in ("芝", "ダ"):
        obs, hmap, rr = A.build_obs(races, {}, s)
        ratings.update(A.walk_forward(obs, hmap, rr, 365, 2.0, "yr"))

    rows = []
    for r in races:
        g = tc.get(r["rid"], "")
        if g not in ("良", "重") or r["dt"] < A.EVAL_START:
            continue
        n = len(r["ents"])
        th = np.array([ratings.get((e["horse_id"], r["dt"]), (np.nan, 0))[0] for e in r["ents"]])
        if np.isnan(th).mean() > 0.4:
            continue
        thc = np.where(np.isnan(th), np.nanmean(th), th) - np.nanmean(th)
        y = np.array([ND.inv_cdf((n - e["rank"] + 0.5) / n) for e in r["ents"]])
        # 期待値は θ差に比例（係数は全体回帰で後から吸収されるため、ここでは残差 = y − b·θ差 の b を 1.0 と置かず後で推定）
        for e, t, yy, raw in zip(r["ents"], thc, y, th):
            if np.isnan(raw):
                continue
            sn = sire.get(e["horse_id"], "")
            rows.append({"dt": r["dt"], "surface": r["surface"], "going": g, "cls": r["cls"], "y": yy, "thc": t,
                         "rank": e["rank"], "n": n, "pop": e.get("popularity") or 99,
                         "hid": e["horse_id"], "sire": sn, "_key": (r["rid"])})
    df = pd.DataFrame(rows)

    # 期待値の係数 b を良馬場で推定（y ≈ b·θ差）
    good = df[df.going == "良"]
    b = float((good.y * good.thc).sum() / (good.thc ** 2).sum())
    df["e"] = df["y"] - b * df["thc"]
    print(f"期待値の係数 b={b:.3f}（良馬場・n={len(good)}）  対象 {len(df)}頭")

    # 残差を時系列で蓄積し直す（b確定後）
    df = df.sort_values("dt").reset_index(drop=True)
    H = defaultdict(lambda: {"良": [0, 0.0], "重": [0, 0.0]})
    S = defaultdict(lambda: {"良": [0, 0.0], "重": [0, 0.0]})
    feats = []
    for dt, grp in df.groupby("dt", sort=True):
        for i, r in grp.iterrows():
            h, s = H[r.hid], S[r.sire] if r.sire else {"良": [0, 0.0], "重": [0, 0.0]}
            feats.append((i, h["重"][0], h["重"][1] / (h["重"][0] + K_HORSE), h["良"][0], h["良"][1] / (h["良"][0] + K_HORSE),
                          s["重"][0], s["重"][1] / (s["重"][0] + K_SIRE), s["良"][1] / (s["良"][0] + K_SIRE)))
        for i, r in grp.iterrows():
            H[r.hid][r.going][0] += 1
            H[r.hid][r.going][1] += r.e
            if r.sire:
                S[r.sire][r.going][0] += 1
                S[r.sire][r.going][1] += r.e
    f = pd.DataFrame(feats, columns=["i", "n_wet", "f_wet", "n_good", "f_good", "s_nwet", "sf_wet", "sf_good"]).set_index("i")
    df = df.join(f)
    df["sf_diff"] = df["sf_wet"] - df["sf_good"]           # 父馬の「道悪固有」成分

    def slope(d, x):
        d = d[d[x].notna()]
        if len(d) < 30 or d[x].std() == 0:
            return float("nan"), len(d)
        return float(np.polyfit(d[x], d["e"], 1)[0]), len(d)

    for surf in ("芝", "ダ"):
        d = df[df.surface == surf]
        wet, gd = d[d.going == "重"], d[d.going == "良"]
        print(f"\n===== {surf}  重 {wet['_key'].nunique()}R / 良 {gd['_key'].nunique()}R =====")
        w1 = wet[wet.n_wet >= 1]
        print("【馬自身】今回の残差 e を過去残差の縮小平均に回帰した傾き（1に近いほど再現性が高い）")
        print(f"  道悪→道悪（道悪経験1走以上）   傾き {slope(w1, 'f_wet')[0]:+.3f}  n={len(w1)}")
        print(f"  良→道悪（対照: 好不調の持ち越し） 傾き {slope(wet[wet.n_good >= 1], 'f_good')[0]:+.3f}  n={(wet.n_good >= 1).sum()}")
        print(f"  道悪→良（対照: 道悪固有でない分） 傾き {slope(gd[gd.n_wet >= 1], 'f_wet')[0]:+.3f}  n={(gd.n_wet >= 1).sum()}")
        print(f"  良→良（参考）                    傾き {slope(gd[gd.n_good >= 1], 'f_good')[0]:+.3f}  n={(gd.n_good >= 1).sum()}")
        print("  道悪経験ありの馬を過去の道悪残差で3分割 → 今回の道悪レース")
        for lab, sel in [("道悪で下振れ (f≤-0.25)", w1.f_wet <= -0.25), ("中間", (w1.f_wet > -0.25) & (w1.f_wet < 0.25)), ("道悪で上振れ (f≥+0.25)", w1.f_wet >= 0.25)]:
            g = w1[sel]
            if len(g):
                print(f"    {lab:<22} n={len(g):>5} 平均残差 {g.e.mean():+.3f}  3着内率 {(g['rank'] <= 3).mean():.1%}  平均人気 {g['pop'].mean():.1f}")
        print("【父馬】産駒全体の道悪残差（縮小平均・産駒の道悪出走10走以上）")
        ws = wet[wet.s_nwet >= 10]
        print(f"  父の道悪残差→道悪   傾き {slope(ws, 'sf_wet')[0]:+.3f}  n={len(ws)}")
        print(f"  父の(道悪−良)→道悪 傾き {slope(ws, 'sf_diff')[0]:+.3f}")
        print(f"  父の道悪残差→良（対照） 傾き {slope(gd[gd.s_nwet >= 10], 'sf_wet')[0]:+.3f}")
        q = ws["sf_diff"].quantile([0.2, 0.8]).values if len(ws) else [0, 0]
        for lab, sel in [("父が道悪×(下位20%)", ws.sf_diff <= q[0]), ("中間", (ws.sf_diff > q[0]) & (ws.sf_diff < q[1])), ("父が道悪◎(上位20%)", ws.sf_diff >= q[1])]:
            g = ws[sel]
            if len(g):
                print(f"    {lab:<22} n={len(g):>5} 平均残差 {g.e.mean():+.3f}  3着内率 {(g['rank'] <= 3).mean():.1%}  平均人気 {g['pop'].mean():.1f}")
        if len(ws):
            top = ws.groupby("sire").agg(sf=("sf_diff", "last"), n=("s_nwet", "last")).sort_values("sf")
            print("   道悪×の父:", ", ".join(f"{k}({v.sf:+.2f}/{int(v.n)}走)" for k, v in top.head(5).iterrows()))
            print("   道悪◎の父:", ", ".join(f"{k}({v.sf:+.2f}/{int(v.n)}走)" for k, v in top.tail(5).iterrows()))


if __name__ == "__main__":
    main()
