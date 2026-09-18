"""
market_residual_model.py のモデルD（市場+予想スコア+Elo）で出たバリューベットの頑健性確認。
fold別・的中数・高配当除外ROI と、「予想が低評価の1番人気」の成績を出す。
使い方: python3 analyze/market_residual_check.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M


def roi(g):
    return (g["単勝オッズ"] * (g["実着順"] == 1)).sum() / max(len(g), 1)


def main():
    df, _ = M.load()
    cols = ["log_mkt", "score_z", "elo_conf"]
    folds = [(pd.Timestamp(2025, 7, 1), pd.Timestamp(2026, 1, 1)),
             (pd.Timestamp(2026, 1, 1), pd.Timestamp(2027, 1, 1))]
    parts = []
    for t0, t1 in folds:
        tr, te = df[df.dt < t0], df[(df.dt >= t0) & (df.dt < t1)]
        mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
        mu["log_mkt"], sd["log_mkt"] = 0.0, 1.0
        rtr, utr = np.unique(tr.rid, return_inverse=True)
        rte, ute = np.unique(te.rid, return_inverse=True)
        w = M.fit(((tr[cols] - mu) / sd).values, (tr["実着順"] == 1).values.astype(float), utr, len(rtr), l2=0.5)
        p = M.predict(((te[cols] - mu) / sd).values, w, ute, len(rte))
        parts.append(te.assign(p=p, fold=str(t0.date())))
    d = pd.concat(parts)
    d["ev"] = d.p * d["単勝オッズ"]

    for th in (1.0, 1.03, 1.05):
        b = d[d.ev > th]
        ret = b["単勝オッズ"] * (b["実着順"] == 1)
        print(f"\nev>{th}: {len(b)}件 的中{int((b['実着順'] == 1).sum())} ROI {ret.sum() / len(b):.0%}"
              f"  最高配当除外 {(ret.sum() - ret.max()) / len(b):.0%}"
              f"  上位2除外 {(ret.sum() - ret.nlargest(2).sum()) / len(b):.0%}")
        for f, g in b.groupby("fold"):
            print(f"   fold {f}: {len(g)}件 的中{int((g['実着順'] == 1).sum())} ROI {roi(g):.0%}")

    b = d[d.ev > 1.0]
    print("\nオッズ min/中央/max:", b["単勝オッズ"].min(), b["単勝オッズ"].median(), b["単勝オッズ"].max(),
          " 予想順位中央値:", b["予想順位"].median(), " 市場人気中央値:", b["市場人気"].median())
    print(b[b["実着順"] == 1][["日付", "レース名", "馬名", "単勝オッズ", "市場人気", "予想順位"]].to_string(index=False))

    print("\n--- 1番人気を予想順位で分けた成績 ---")
    for lab, src in [("テスト期間", d), ("全期間", df)]:
        fav = src[src["市場人気"] == 1]
        for name, g in [("予想1-3位", fav[fav["予想順位"] <= 3]), ("予想4位以下", fav[fav["予想順位"] >= 4])]:
            print(f"[{lab}] 1番人気×{name}: n={len(g)} 勝率{(g['実着順'] == 1).mean():.1%}"
                  f" 複勝率{(g['実着順'] <= 3).mean():.1%} 単ROI{roi(g):.0%}")


if __name__ == "__main__":
    main()
