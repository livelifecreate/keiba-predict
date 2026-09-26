"""
予測ペースと脚質の「相性」は着順を予測するか（2026-09-26）

仮説: 前傾（前半が速い）レースでは差し・追込が有利、後傾では逃げ・先行が有利。
検証: 能力指数v3で説明できる分を引いた残差に対して、相性項が効くかを見る（乖離方式・先読みなし）。
  相性 = 予測ペース（標準化）× その馬の脚質（前に行くほど小さい値）
  対照として ①予測ペース単体 ②脚質単体 も入れ、相互作用が独立に効くかを確かめる。
使い方: python3 analyze/pace_fit_test.py
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
import market_residual_model as M
import pace_model as P

ND = NormalDist()
TRAIN_END = pd.Timestamp(2025, 7, 1)


def main():
    runs = P.load_runs()
    runs["rid"] = (runs["dt"].astype(str) + "_" + runs["venue"] + "_" + runs["surface"]
                   + runs["dist"].astype(str) + "_" + runs["field"].astype(str))
    runs["pos_rate"] = (runs["first_corner"] - 1) / (runs["field"] - 1)
    runs = runs.sort_values("dt")
    hist = defaultdict(list)
    for r in runs.dropna(subset=["pos_rate"]).itertuples():
        hist[r.hid].append((r.dt, r.pos_rate))

    def style_before(hid, dt, k=5):
        v = [p for d, p in hist.get(hid, []) if d < dt]
        return float(np.mean(v[-k:])) if v else np.nan

    f = pd.read_parquet(BASE / "data" / "pace_features.parquet")
    cols = ["n_front", "front_min", "front_top2", "front_mean", "field", "dist_z", "is_turf"]
    tr = f[f.dt < TRAIN_END]
    X = lambda d: np.column_stack([d[c] for c in cols] + [np.ones(len(d))])
    coef, *_ = np.linalg.lstsq(X(tr), tr.pace_gap.values, rcond=None)
    f["pred_pace"] = X(f) @ coef
    pace_of = dict(zip(f.rid, f.pred_pace))
    print(f"予測ペースのあるレース: {len(pace_of):,}")

    # race_result の会場名（A.load_races は venue を持たない）
    venue_of = {}
    for q in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(q.read_text())
        venue_of[d.get("race_id") or q.stem] = d.get("venue") or ""

    # 能力指数（芝ダ別・開催日ごと）
    cache_races = A.load_races()
    ratings = {}
    for s in ("芝", "ダ"):
        obs, hmap, rr = A.build_obs(cache_races, {}, s)
        ratings.update(A.walk_forward(obs, hmap, rr, 365, 2.0, "yr"))

    # cache/race_result のレースに、予測ペースと脚質を結合する
    rows = []
    for r in cache_races:
        if r["dt"] < A.EVAL_START:
            continue
        key_dt = str(r["dt"].date())
        n = len(r["ents"])
        th = np.array([ratings.get((e["horse_id"], r["dt"]), (np.nan, 0))[0] for e in r["ents"]])
        if np.isnan(th).mean() > 0.4:
            continue
        thc = np.where(np.isnan(th), np.nanmean(th), th) - np.nanmean(th)
        y = np.array([ND.inv_cdf((n - e["rank"] + 0.5) / n) for e in r["ents"]])
        # rid を作って予測ペースを引く（日付_場_レース名の先頭12文字）
        key = f"{key_dt}_{venue_of.get(r['rid'], '')}_{r['surface']}{r['dist']}_{n}"
        pp = pace_of.get(key, np.nan)
        for e, t, yy, raw in zip(r["ents"], thc, y, th):
            if np.isnan(raw):
                continue
            st = style_before(e["horse_id"], r["dt"])
            rows.append({"rid": r["rid"], "dt": r["dt"], "cls": r["cls"], "y": yy, "thc": t,
                         "rank": e["rank"], "pop": e.get("popularity") or 99, "leg": st, "pace": pp})
    df = pd.DataFrame(rows)
    print(f"対象: {len(df):,}頭  脚質あり{df["leg"].notna().mean():.0%} / 予測ペースあり{df.pace.notna().mean():.0%}")
    d = df.dropna(subset=["leg", "pace"]).copy()
    if len(d) < 500:
        print("結合できた行が少なすぎる。レース名の突合を見直す必要あり。")
        print("  race_result 側のキー例:", [f"{r['dt'].date()}_{venue_of.get(r['rid'], '')}_{r['surface']}{r['dist']}_{len(r['ents'])}" for r in cache_races[:3]])
        print("  通算成績側のキー例:", list(pace_of)[:3])
        return
    good = d[d.dt < TRAIN_END]
    b = float((good.y * good.thc).sum() / (good.thc ** 2).sum())
    d["e"] = d.y - b * d.thc
    d["pace_z"] = (d.pace - d.pace.mean()) / d.pace.std()
    d["style_z"] = (d["leg"] - d["leg"].mean()) / d["leg"].std()      # 大きいほど後方
    d["fit"] = d.pace_z * d.style_z                                 # 前傾(小)×後方(大) の符号に注目
    print(f"検証対象: {len(d):,}頭 / {d.rid.nunique():,}R")

    te = d[d.dt >= TRAIN_END]
    print("\n■ 残差を説明できるか（テスト期間・係数±は95%区間）")
    for lab, cs in [("脚質だけ", ["style_z"]), ("予測ペースだけ", ["pace_z"]),
                    ("脚質＋ペース", ["style_z", "pace_z"]), ("脚質＋ペース＋相性", ["style_z", "pace_z", "fit"])]:
        Xm = np.column_stack([te[c] for c in cs] + [np.ones(len(te))])
        cf, *_ = np.linalg.lstsq(Xm, te.e.values, rcond=None)
        res = te.e.values - Xm @ cf
        se = np.sqrt(np.sum(res ** 2) / (len(te) - len(cs) - 1) * np.diag(np.linalg.inv(Xm.T @ Xm)))
        print(f"  {lab:<18} " + " / ".join(f"{c}{cf[i]:+.4f}±{1.96 * se[i]:.4f}" for i, c in enumerate(cs)))

    print("\n■ 予測ペース × 脚質 の9分割（テスト期間の平均残差・3着内率）")
    te = te.assign(pb=pd.qcut(te.pace_z, 3, labels=["前傾", "中間", "後傾"]),
                   sb=pd.qcut(te.style_z, 3, labels=["先行", "中団", "後方"]))
    print(f"{'':<6}" + "".join(f"{s:>16}" for s in ("先行", "中団", "後方")))
    for p in ("前傾", "中間", "後傾"):
        line = f"{p:<6}"
        for s in ("先行", "中団", "後方"):
            g = te[(te.pb == p) & (te.sb == s)]
            line += f"{g.e.mean():>+8.3f}/{(g['rank'] <= 3).mean():>6.0%}" if len(g) > 30 else f"{'—':>16}"
        print(line)


if __name__ == "__main__":
    main()
