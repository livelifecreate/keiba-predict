"""
調教コメントは当てになるか（2026-09-22）

ユーザーの疑問「タイムのような数値ならまだしも、コメントだけの調教評価は なんとでも言える」を検証する。
netkeiba の調教欄は A〜D 評価と短評コメント（「好調子」「仕上がる」等）だけで、タイムは無料では取れない。
現行システムはコメント別の実績複勝率をスコア化（training_form.py）し、案D/案Gの「手作り因子」にも入っている。

検証（すべて時点統計・先読みなし。コメントの実績複勝率は各レース日より前の実績のみで算出）:
  ① コメントは市場（オッズ）に対して上乗せの予測力を持つか  ← 最も重要
  ② コメントは能力指数v3のθに対して上乗せの予測力を持つか   ← 我々の順位づけに効くか
  ③ コメントは単に人気の言い換えではないか（人気との相関・人気を揃えた層別）
  ④ A〜D評価（rank）とコメント実績のどちらが効くか
対象: cache/netkeiba_training があるレース（2勝クラス以上が中心）。テストは2025/07〜。
使い方: python3 analyze/training_comment_test.py
"""
import json, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import market_residual_model as M
from training_form import comment_stats_as_of, RANK_SCORE

TRAIN_END = pd.Timestamp(2025, 7, 1)


def main():
    races = A.load_races()
    tdir = BASE / "cache" / "netkeiba_training"
    v3p = BASE / "data" / "v3_eval.parquet"
    v3 = pd.read_parquet(v3p).set_index(["馬名", "dt"])["v3_c"] if v3p.exists() else None
    v3 = v3[~v3.index.duplicated()] if v3 is not None else None

    rows, n_race, n_has = [], 0, 0
    for r in races:
        if r["dt"] < A.EVAL_START:
            continue
        n_race += 1
        p = tdir / f"{r['rid']}.json"
        if not p.exists():
            continue
        try:
            td = json.loads(p.read_text())
        except Exception:
            continue
        if not td:
            continue
        n_has += 1
        n = len(r["ents"])
        as_of = r["dt"].strftime("%Y/%m/%d")
        for e in r["ents"]:
            t = td.get(e["horse_name"])
            if not t or not e.get("odds") or not e.get("popularity"):
                continue
            h, c = comment_stats_as_of(t.get("comment", ""), as_of)
            rate = h / c if c >= 30 else np.nan          # 母数30未満はフォールバック扱い
            rows.append({"rid": r["rid"], "dt": r["dt"], "cls": r["cls"], "surface": r["surface"],
                         "馬名": e["horse_name"], "rank": e["rank"], "odds": e["odds"], "pop": e["popularity"],
                         "comment": t.get("comment", ""), "crate": rate, "n_comment": c,
                         "rank_score": RANK_SCORE.get(t.get("rank", ""), 1)})
    df = pd.DataFrame(rows)
    print(f"調教データのあるレース: {n_has}/{n_race}R（2026-09-22時点）  対象 {len(df)}頭  コメント実績が使える割合 {df['crate'].notna().mean():.0%}")
    print(f"コメント種類: {df['comment'].nunique()}  上位: " +
          ", ".join(f"{k}({v})" for k, v in df['comment'].value_counts().head(6).items()))

    # 欠損はレース内平均で埋め、レース内中心化
    for c in ("crate", "rank_score"):
        m = df.groupby("rid")[c].transform("mean")
        df[c + "_c"] = (df[c].fillna(m) - m).fillna(0.0)
    imp = 1.0 / df["odds"]
    df["log_mkt"] = np.log(imp / imp.groupby(df["rid"]).transform("sum"))
    # 能力指数は v3_eval.parquet の行（= v3 が推定に使った母集団）を土台にし、そこへコメントを結合する。
    # 逆向き（コメント側にθを結合）だと、調教データのある馬だけで母集団が変わり比較が歪む。
    if v3 is not None:
        ab = pd.read_parquet(v3p)[["rid", "dt", "馬名", "rank", "odds", "pop", "cls", "v3_c"]]
        ab = ab[~ab.duplicated(subset=["rid", "馬名"])]
        cm = df[["rid", "馬名", "crate", "rank_score", "n_comment", "comment"]].drop_duplicates(subset=["rid", "馬名"])
        ab = ab.merge(cm, on=["rid", "馬名"], how="left")
        keep = ab.groupby("rid")["crate"].transform(lambda s: s.notna().mean()) >= 0.6   # 調教が揃うレースのみ
        ab = ab[keep].copy()
        imp2 = 1.0 / ab["odds"]
        ab["log_mkt"] = np.log(imp2 / imp2.groupby(ab["rid"]).transform("sum"))
        for c in ("v3_c", "crate", "rank_score"):
            m = ab.groupby("rid")[c].transform("mean")
            ab[c + "_c" if c != "v3_c" else "ability"] = (ab[c].fillna(m) - m).fillna(0.0)
        print(f"能力指数と調教が揃うレース: {ab['rid'].nunique()}R / {len(ab)}頭")
    else:
        ab = None

    print("\n③ 人気の言い換えではないか")
    cor = df.groupby("rid").apply(lambda g: g["crate_c"].corr(-g["pop"].astype(float)), include_groups=False).mean()
    print(f"  レース内での「コメント実績」と人気の相関: {cor:+.3f}（1に近いほど人気の言い換え）")
    te = df[df.dt >= TRAIN_END]
    for lo, hi, lab in [(1, 3, "1〜3番人気"), (4, 7, "4〜7番人気"), (8, 20, "8番人気以下")]:
        g = te[(te["pop"] >= lo) & (te["pop"] <= hi) & te["crate"].notna()]
        if len(g) < 100:
            continue
        q = g["crate"].quantile([0.33, 0.66]).values
        lowg, higg = g[g.crate <= q[0]], g[g.crate >= q[1]]
        print(f"  [{lab}] コメント下位 n={len(lowg)} 複勝率{(lowg['rank'] <= 3).mean():.1%} 単ROI{(lowg['odds'] * (lowg['rank'] == 1)).mean():.0%}"
              f" / 上位 n={len(higg)} 複勝率{(higg['rank'] <= 3).mean():.1%} 単ROI{(higg['odds'] * (higg['rank'] == 1)).mean():.0%}")

    print("\n① 市場への上乗せがあるか（レース内softmax・学習〜2025/06 → テスト2025/07〜）")
    for cols, lab in [(["log_mkt"], "市場のみ"),
                      (["log_mkt", "crate_c"], "市場＋コメント実績"),
                      (["log_mkt", "rank_score_c"], "市場＋A〜D評価"),
                      (["log_mkt", "crate_c", "rank_score_c"], "市場＋コメント＋A〜D")]:
        r = _eval(df, cols, lab)
        print(f"  {lab:<22} n={r['n']}R logloss={r['logloss']:.4f} 1位勝率{r['win']:.1%} 複勝率{r['place']:.1%} 単ROI{r['roi']:.0%}  w={r['w']}")

    if ab is not None:
        print("\n② 我々の順位づけ（市場を使わない）に効くか")
        for cols, lab in [(["ability"], "能力指数v3のみ"),
                          (["ability", "crate_c"], "能力＋コメント実績"),
                          (["ability", "rank_score_c"], "能力＋A〜D評価"),
                          (["ability", "crate_c", "rank_score_c"], "能力＋コメント＋A〜D"),
                          (["crate_c"], "コメント実績のみ")]:
            r = _eval(ab, cols, lab)
            print(f"  {lab:<22} n={r['n']}R logloss={r['logloss']:.4f} 1位勝率{r['win']:.1%} 複勝率{r['place']:.1%} 単ROI{r['roi']:.0%}  w={r['w']}")

    print("\n④ コメント別の実績（テスト期間の実測・出現30回以上）")
    g = te[te["n_comment"] >= 30].groupby("comment").agg(n=("rank", "size"), plc=("rank", lambda s: (s <= 3).mean()),
                                                         avg_pop=("pop", "mean"))
    g = g[g["n"] >= 30].sort_values("plc")
    print("  複勝率が低い: " + ", ".join(f"{k}({v.plc:.0%}/n={int(v.n)}/平均{v.avg_pop:.1f}人気)" for k, v in g.head(4).iterrows()))
    print("  複勝率が高い: " + ", ".join(f"{k}({v.plc:.0%}/n={int(v.n)}/平均{v.avg_pop:.1f}人気)" for k, v in g.tail(4).iterrows()))


def _eval_frame(df, cols):
    """指定の特徴量で選んだ予想1位の行を返す（診断用）"""
    tr, te = df[df.dt < TRAIN_END], df[df.dt >= TRAIN_END]
    mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
    _, utr = np.unique(tr.rid, return_inverse=True)
    rte, ute = np.unique(te.rid, return_inverse=True)
    w = M.fit(((tr[cols] - mu) / sd).values, (tr["rank"] == 1).values.astype(float), utr, utr.max() + 1, l2=0.5, iters=1000)
    p = M.predict(((te[cols] - mu) / sd).values, w, ute, len(rte))
    d = te.assign(p=p)
    return d.loc[d.groupby("rid")["p"].idxmax()]


def _eval(df, cols, label):
    tr, te = df[df.dt < TRAIN_END], df[df.dt >= TRAIN_END]
    mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
    if "log_mkt" in cols:
        mu["log_mkt"], sd["log_mkt"] = 0.0, 1.0
    _, utr = np.unique(tr.rid, return_inverse=True)
    rte, ute = np.unique(te.rid, return_inverse=True)
    w = M.fit(((tr[cols] - mu) / sd).values, (tr["rank"] == 1).values.astype(float), utr, utr.max() + 1, l2=0.5, iters=1000)
    p = M.predict(((te[cols] - mu) / sd).values, w, ute, len(rte))
    d = te.assign(p=p)
    top = d.loc[d.groupby("rid")["p"].idxmax()]
    return {"n": len(rte), "logloss": -np.log(d.loc[d["rank"] == 1, "p"]).mean(),
            "win": (top["rank"] == 1).mean(), "place": (top["rank"] <= 3).mean(),
            "roi": (top["odds"] * (top["rank"] == 1)).mean(), "w": dict(zip(cols, np.round(w, 3)))}


if __name__ == "__main__":
    main()
