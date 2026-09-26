"""
「展開で選ぶ5頭」は、能力指数のランキング5頭とどう違うか（2026-09-26）

やること:
  ① 4角での位置を予測する（過去の通過順から「そのレースで何番手あたりにいるか」）
  ② 予測ペースと4角位置から「残りそう・届きそう」な馬を能力指数と組み合わせて5頭選ぶ
  ③ ランキング上位5頭と、どれだけ重なるか／どちらが3着内馬をよく拾うかを比べる

選び方（展開型）: スコア = 能力指数 + a×(4角で前にいる度合い) + b×(予測ペースとの相性)
  a, b は学習期間（〜2025/06）で「3着内に入る確率」を最大化するように決める。
  検証（pace_fit_test）で相性は効かなかったが、4角位置そのものは強い（どのペースでも先行有利）。
  ここではその知見をそのまま使い、ランキングとの違いを見る。
使い方: python3 analyze/pace_pick_test.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import market_residual_model as M
import ability_blend_backtest as B
import pace_model as P
import verify.bet_analysis2 as ba2

TRAIN_END = pd.Timestamp(2025, 7, 1)


def main():
    # ---- 脚質（1角）と4角位置の履歴を作る
    runs = P.load_runs()
    runs = runs.sort_values("dt")
    hist1, hist4 = defaultdict(list), defaultdict(list)
    for p in (BASE / "cache" / "horse_full_history").glob("*.json"):
        try:
            recs = json.loads(p.read_text())
        except Exception:
            continue
        hid = p.stem
        for r in recs:
            d = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
            c = re.findall(r"\d+", r.get("corner", "") or "")
            try:
                field = int(r.get("field") or 0)
            except ValueError:
                continue
            if not d or not c or field < 5:
                continue
            dt = pd.Timestamp(int(d.group(1)), int(d.group(2)), int(d.group(3)))
            hist1[hid].append((dt, (int(c[0]) - 1) / (field - 1)))
            hist4[hid].append((dt, (int(c[-1]) - 1) / (field - 1)))     # 最終コーナー

    def before(h, hid, dt, k=5):
        v = [p for d, p in h.get(hid, []) if d < dt]
        return float(np.mean(v[-k:])) if v else np.nan

    # ---- 予測ペース
    f = pd.read_parquet(BASE / "data" / "pace_features.parquet")
    cols = ["n_front", "front_min", "front_top2", "front_mean", "field", "dist_z", "is_turf"]
    tr = f[f.dt < TRAIN_END]
    X = lambda d: np.column_stack([d[c] for c in cols] + [np.ones(len(d))])
    coef, *_ = np.linalg.lstsq(X(tr), tr.pace_gap.values, rcond=None)
    f["pred"] = X(f) @ coef
    pace_of = dict(zip(f.rid, f.pred))

    # ---- 案Gの順位
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"])
    m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)
    u, w = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["u_G"] = u
    print("案Gの重み:", w)

    # 馬ID・会場を race_result から引く
    id_of, venue_of, surf_of, dist_of = {}, {}, {}, {}
    for q in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(q.read_text())
        rid = d.get("race_id") or q.stem
        venue_of[rid] = d.get("venue") or ""
        surf_of[rid] = d.get("surface") or ""
        mm = re.search(r"(\d+)", str(d.get("distance") or ""))
        dist_of[rid] = int(mm.group(1)) if mm else 0
        for e in d["entries"]:
            if e.get("horse_id"):
                id_of[(e["horse_name"], d.get("date"))] = e["horse_id"]

    rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}
    df["rr_id"] = [rid_of.get(k) for k in zip(df["日付"], df["レース名"])]
    df["hid"] = [id_of.get((n, d)) for n, d in zip(df["馬名"], df["日付"])]
    df["pos4"] = [before(hist4, h, dt) for h, dt in zip(df["hid"], df["dt"])]
    df["pos1"] = [before(hist1, h, dt) for h, dt in zip(df["hid"], df["dt"])]
    df["pace"] = [pace_of.get(f"{dt.date()}_{venue_of.get(r, '')}_{surf_of.get(r, '')}{dist_of.get(r, 0)}_{n}", np.nan)
                  for dt, r, n in zip(df["dt"], df["rr_id"], df.groupby("rid")["馬名"].transform("size"))]
    print(f"4角位置あり {df.pos4.notna().mean():.0%} / 予測ペースあり {df.pace.notna().mean():.0%}")

    d = df[df.pos4.notna() & df.pace.notna()].copy()
    for c in ("pos4", "pace"):
        mm = d.groupby("rid")[c].transform("mean")
        d[c + "_c"] = (d[c] - mm).fillna(0.0)
    d["fit"] = d["pace_c"] * d["pos4_c"]
    d["u_z"] = d.groupby("rid")["u_G"].transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))
    d["p4_z"] = d.groupby("rid")["pos4_c"].transform(lambda s: (s - s.mean()) / (s.std() + 1e-9))

    # 展開型スコアの重みを学習期間で決める（3着内かどうかを説明する線形回帰）
    trd = d[d.dt < TRAIN_END]
    Xtr = np.column_stack([trd.u_z, -trd.p4_z, trd.fit, np.ones(len(trd))])
    cf, *_ = np.linalg.lstsq(Xtr, (trd["実着順"] <= 3).astype(float).values, rcond=None)
    print(f"展開型スコアの重み: 能力{cf[0]:+.3f} / 4角で前{cf[1]:+.3f} / 相性{cf[2]:+.3f}")
    d["u_pace"] = cf[0] * d.u_z + cf[1] * (-d.p4_z) + cf[2] * d.fit

    te = d[d.dt >= TRAIN_END]
    print(f"\n検証: テスト期間 {te.rid.nunique():,}R / {len(te):,}頭")
    res = []
    for rid, g in te.groupby("rid"):
        if len(g) < 8:
            continue
        top_rank = set(g.nlargest(5, "u_G")["馬名"])
        top_pace = set(g.nlargest(5, "u_pace")["馬名"])
        in3 = set(g[g["実着順"] <= 3]["馬名"])
        res.append({"overlap": len(top_rank & top_pace),
                    "rank_hit": len(top_rank & in3), "pace_hit": len(top_pace & in3),
                    "rank_all3": int(len(top_rank & in3) == 3), "pace_all3": int(len(top_pace & in3) == 3),
                    "n3": len(in3)})
    r = pd.DataFrame(res)
    print(f"\n■ 5頭の重なり具合（{len(r):,}R）")
    for k in range(6):
        c = (r.overlap == k).sum()
        if c:
            print(f"  {k}頭が一致: {c:>5}R ({c / len(r):.0%})")
    print(f"  平均 {r.overlap.mean():.2f}頭が一致")
    print(f"\n■ 3着内馬を何頭拾えたか（1レースあたり・最大3頭）")
    print(f"  ランキング上位5頭 : {r.rank_hit.mean():.3f}頭   3頭すべて拾えた率 {r.rank_all3.mean():.1%}")
    print(f"  展開型の5頭      : {r.pace_hit.mean():.3f}頭   3頭すべて拾えた率 {r.pace_all3.mean():.1%}")


if __name__ == "__main__":
    main()
