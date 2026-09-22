"""
レースレベルと着差を能力指数に入れる（2026-09-22）

ユーザーの要望:
  「このレースに誰が出ていてレベルはどれくらい」「5着でも着差が小さければ見た目以上に強い」
  「レベルの低いレースの1着は大したことない」を数値化して能力指数に反映したい。

現状の確認:
  - レースレベル（出走馬の平均能力）は **すでに能力指数の中に入っている**。
    θ_i = 対戦相手の平均θ + 相対パフォーマンス を全馬同時に解いているため、
    「レベルの低いレースの1着」は自動的に割り引かれる。ただし数値として外に出していなかった。
  - 一方 **着差は使っていない**（走りの評価が着順のみ）。「5着0.1差」と「5着3秒差」が同じ。

このスクリプトがやること:
  ① レースレベル（出走馬θの加重平均）を算出して偏差値化し、レース単位で出力・保存
  ② 着差ベースの評価（1着からの秒差・1600m換算・上限つき）と着順ベースを比較
     着差は cache/horse_history のスナップショット + cache/horse_full_history の両方から集める
  ③ 着順と着差を混ぜた評価（着順スコア + 係数×着差の補正）も試す
使い方: python3 analyze/race_level_margin.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import market_residual_model as M

BASE = Path(__file__).resolve().parent.parent
FULL_DIR = BASE / "cache" / "horse_full_history"
TRAIN_END = pd.Timestamp(2025, 7, 1)


def margins_all() -> dict:
    """{(馬ID, 日付): 勝ち馬からの秒差} をスナップショットと通算成績の両方から集める"""
    m = A.load_margins()                       # スナップショット（近5走）
    n0 = len(m)
    for p in FULL_DIR.glob("*.json"):
        try:
            recs = json.loads(p.read_text())
        except Exception:
            continue
        for r in recs:
            d = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
            v = (r.get("margin") or "").strip()
            if d and re.match(r"^-?[\d.]+$", v):
                m[(p.stem, pd.Timestamp(int(d.group(1)), int(d.group(2)), int(d.group(3))))] = max(float(v), 0.0)
    print(f"着差データ: スナップショット {n0}件 → 通算成績を足して {len(m)}件")
    return m


def evaluate(df, col, label, sub=None):
    d = df if sub is None else df[sub]
    tr, te = d[d.dt < TRAIN_END], d[d.dt >= TRAIN_END]
    if len(te) == 0:
        return None
    mu, sd = tr[col].mean(), tr[col].std() + 1e-9
    _, utr = np.unique(tr.rid, return_inverse=True)
    rte, ute = np.unique(te.rid, return_inverse=True)
    w = M.fit(((tr[[col]] - mu) / sd).values, (tr["rank"] == 1).values.astype(float), utr, utr.max() + 1, l2=0.5, iters=800)
    p = M.predict(((te[[col]] - mu) / sd).values, w, ute, len(rte))
    dd = te.assign(p=p)
    top = dd.loc[dd.groupby("rid")["p"].idxmax()]
    return {"label": label, "n": len(rte), "logloss": -np.log(dd.loc[dd["rank"] == 1, "p"]).mean(),
            "win": (top["rank"] == 1).mean(), "place": (top["rank"] <= 3).mean(),
            "roi": (top["odds"] * (top["rank"] == 1)).mean()}


def main():
    races = A.load_races()
    margins = margins_all()

    rows = []
    for surface in ("芝", "ダ"):
        obs_r, hmap, rr = A.build_obs(races, {}, surface)              # 着順のみ
        obs_m, _, _ = A.build_obs(races, margins, surface)             # 着差つき
        obs_r["ym"] = obs_m["ym"]                                      # 同じ並びなので差し替え可能
        # 着順と着差の混合（着順スコア + 0.5×着差スコア）
        obs_r["mix"] = obs_r["yr"] + 0.5 * obs_m["ym"]
        ratings = {}
        for key in ("yr", "ym", "mix"):
            ratings[key] = A.walk_forward(obs_r, hmap, rr, 365, 2.0, key)
        # 着差が取れた割合（レース単位）
        have = defaultdict(lambda: [0, 0])
        for r in rr:
            for e in r["ents"]:
                have[r["rid"]][1] += 1
                have[r["rid"]][0] += (e["horse_id"], r["dt"]) in margins
        for r in rr:
            if r["dt"] < A.EVAL_START or r["cls"] == "新馬":
                continue
            for e in r["ents"]:
                if not e.get("odds"):
                    continue
                row = {"rid": r["rid"], "dt": r["dt"], "cls": r["cls"], "surface": surface,
                       "馬名": e["horse_name"], "rank": e["rank"], "odds": e["odds"], "pop": e["popularity"],
                       "mcov": have[r["rid"]][0] / max(have[r["rid"]][1], 1)}
                for key in ("yr", "ym", "mix"):
                    th, _ = ratings[key].get((e["horse_id"], r["dt"]), (np.nan, 0))
                    row[key] = th
                rows.append(row)
    df = pd.DataFrame(rows)
    for key in ("yr", "ym", "mix"):
        ok = df.groupby("rid")[key].transform(lambda s: s.notna().mean()) >= 0.6
        m = df.groupby("rid")[key].transform("mean")
        df[key + "_c"] = (df[key].fillna(m) - m).fillna(0.0).where(ok, 0.0)

    print("\n===== ② 着順ベース vs 着差ベース（テスト2025/07〜）=====")
    target = df["cls"].isin(["2勝クラス", "3勝クラス", "OP", "重賞"])
    for sub, lab in [(None, "全クラス"), (target, "2勝クラス以上"), (target & (df["mcov"] >= 0.6), "2勝以上×着差6割以上")]:
        print(f"--- {lab} ---")
        for key, name in [("yr_c", "着順ベース（現行）"), ("ym_c", "着差ベース"), ("mix_c", "着順＋着差の混合")]:
            r = evaluate(df, key, name, sub)
            if r:
                print(f"  {name:<20} n={r['n']}R logloss={r['logloss']:.4f} 1位勝率{r['win']:.1%} 複勝率{r['place']:.1%} 単ROI{r['roi']:.0%}")

    # ① レースレベル
    print("\n===== ① レースレベル（出走馬の平均能力・偏差値50が全馬平均）=====")
    lv = df.groupby(["rid", "cls"], as_index=False)["yr"].mean().rename(columns={"yr": "level"})
    mu, sd = lv["level"].mean(), lv["level"].std()
    lv["偏差値"] = 50 + 10 * (lv["level"] - mu) / sd
    for cls, g in lv.groupby("cls"):
        print(f"  {cls:<8} n={len(g):>5} レースレベル 平均{g['偏差値'].mean():>5.1f} / 下位10%{g['偏差値'].quantile(0.1):>5.1f} / 上位10%{g['偏差値'].quantile(0.9):>5.1f}")
    out = BASE / "data" / "race_level.csv"
    lv[["rid", "cls", "偏差値"]].to_csv(out, index=False)
    print(f"  保存: {out}（同クラスでもレベル差が大きいことの確認用）")


if __name__ == "__main__":
    main()
