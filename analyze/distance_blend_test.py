"""
距離適性を案Gに足すと改善するか（2026-09-26）

`analyze/distance_aptitude.py` で「同じ距離帯の過去残差 → 今回」の傾き +0.195±0.033（他距離帯は+0.038）
と、距離固有のシグナルを確認した。ただし v3 の条件ブロックに入れると係数が負になる
（θ が同じ情報を吸収するため二重になる）。そこで **案Gの第3項として足す** 形で検証する。

  案G     = w1·z(v3のθ) + w2·z(能力以外の因子合計)
  案G+距離 = 上記 + w3·z(同じ距離帯の残差)

評価: 9馬券種（総合）＋買い条件（10〜13頭・重賞以外）での的中率とROI。
使い方: python3 analyze/distance_blend_test.py
"""
import json, re, sys, tempfile
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import market_residual_model as M
import ability_blend_backtest as B
import verify.bet_analysis2 as ba2
from verify.bet_metrics_standard import sim_bet, BET_SPECS

ND = NormalDist()
TRAIN_END = pd.Timestamp(2025, 7, 1)
K = 2.0


def band(d):
    return "〜1400" if d <= 1400 else "1500-1700" if d <= 1700 else "1800-2000" if d <= 2000 else "2100〜"


def distance_feature():
    """{(馬ID, 日付): 同じ距離帯の過去残差（縮小平均）} を作る（先読みなし）"""
    races = A.load_races()
    ratings = {}
    for s in ("芝", "ダ"):
        obs, hmap, rr = A.build_obs(races, {}, s)
        ratings.update(A.walk_forward(obs, hmap, rr, 365, 2.0, "yr"))
    rows = []
    for r in races:
        n = len(r["ents"])
        th = np.array([ratings.get((e["horse_id"], r["dt"]), (np.nan, 0))[0] for e in r["ents"]])
        if np.isnan(th).mean() > 0.4:
            continue
        thc = np.where(np.isnan(th), np.nanmean(th), th) - np.nanmean(th)
        y = np.array([ND.inv_cdf((n - e["rank"] + 0.5) / n) for e in r["ents"]])
        for e, t, yy, raw in zip(r["ents"], thc, y, th):
            if np.isnan(raw):
                continue
            rows.append({"dt": r["dt"], "hid": e["horse_id"], "key": (e["horse_id"], r["surface"], band(r["dist"])),
                         "e": yy - 1.37 * t})
    d = pd.DataFrame(rows).sort_values("dt")
    acc, out = defaultdict(lambda: [0, 0.0]), {}
    for dt, g in d.groupby("dt", sort=True):
        for r in g.itertuples():
            c, tot = acc[r.key]
            out[(r.hid, dt)] = tot / (c + K)
        for r in g.itertuples():
            acc[r.key][0] += 1
            acc[r.key][1] += r.e
    print(f"距離適性を付与できた (馬,日付): {len(out):,}")
    return out


def main():
    dist_of = distance_feature()
    raw = pd.read_csv(M.CSV, dtype=str)
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"])
    m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)

    id_of = {}
    for q in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(q.read_text())
        for e in d["entries"]:
            if e.get("horse_id"):
                id_of[(e["horse_name"], d.get("date"))] = e["horse_id"]
    df["hid"] = [id_of.get((n, dd)) for n, dd in zip(df["馬名"], df["日付"])]
    df["dist_apt"] = [dist_of.get((h, dt), np.nan) for h, dt in zip(df["hid"], df["dt"])]
    print(f"距離適性の付与率: {df.dist_apt.notna().mean():.0%}")
    mm = df.groupby("rid")["dist_apt"].transform("mean")
    df["dist_c"] = (df["dist_apt"].fillna(mm) - mm).fillna(0.0)

    utils = {}
    for lab, cols in [("G 案G（現行）", ["v3_c", "rest_sum"]),
                      ("G+距離", ["v3_c", "rest_sum", "dist_c"]),
                      ("距離だけ", ["dist_c"])]:
        u, w = B.fit_util(df, cols, 0.5)
        utils[lab] = u
        print(f"  {lab}: {w}")

    test = df[df.dt >= TRAIN_END]
    raw_te = raw.loc[test.index]
    tmp = Path(tempfile.mkdtemp())
    res = {}
    for i, (lab, u) in enumerate(utils.items()):
        t = test.assign(u=pd.Series(u, index=df.index).loc[test.index])
        rk = t.groupby("rid")["u"].rank(ascending=False, method="first").astype(int)
        out = raw_te.copy()
        out["予想順位"] = rk.astype(str)
        out["予想スコア"] = t["u"].round(4).astype(str)
        path = tmp / f"v{i}.csv"
        out.to_csv(path, index=False, encoding="utf-8-sig")
        ba2.CSV_PATH = path
        races = ba2.load_races()
        res[lab] = {n: sim_bet(races, k) for n, k in BET_SPECS}
        top = t[rk == 1]
        res[lab]["_t"] = ((top["実着順"] == 1).mean() * 100, (top["実着順"] <= 3).mean() * 100, len(races))
        # 買い条件（10〜13頭・重賞以外）
        t2 = t.assign(rk=rk)
        t2["n"] = t2.groupby("rid")["馬名"].transform("size")
        band_races = [r for r in races if 10 <= r["n_horses"] <= 13 and r["class"] != "重賞"]
        res[lab]["_buy"] = (len(band_races), sim_bet(band_races, "trio_axis4")["hit_rate"],
                            sim_bet(band_races, "trio_axis4")["roi"])

    labels = list(utils)
    print(f"\n===== 総合（テスト2025/07〜・n={res[labels[0]]['_t'][2]}R）的中率% / ROI% =====")
    print(f"{'馬券種別':<14}" + "".join(f"{l[:12]:>16}" for l in labels))
    print(f"{'予想1位 勝率/複勝':<14}" + "".join(f"{res[l]['_t'][0]:>8.1f}/{res[l]['_t'][1]:>5.1f}  " for l in labels))
    for n, _ in BET_SPECS:
        print(f"{n:<14}" + "".join(f"{res[l][n]['hit_rate']:>8.1f}/{res[l][n]['roi']:>5.0f}  " for l in labels))
    print(f"\n買い条件（10〜13頭・重賞以外）三連複1軸4頭: " +
          " / ".join(f"{l}: n={res[l]['_buy'][0]} 的中{res[l]['_buy'][1]:.1f}% ROI{res[l]['_buy'][2]:.0f}%" for l in labels))


if __name__ == "__main__":
    main()
