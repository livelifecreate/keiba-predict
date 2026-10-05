"""
着差入り能力指数を案Gに入れたときの比較（2026-10-05）

ability_margin_test.py で、v3 の走りの評価を「着順0.5＋秒差0.5」にすると θ単体の予測力が上がった
（対数損失 -0.03・予想1位複勝率 +1.6pt）。これを案G（v3_c + rest_sum + ace の3変数）に入れて、
重みを学習（〜2025/06）し直し、テスト2025/07〜で買い条件（10〜13頭・重賞以外）の馬券成績を比べる。
rank版も最新の race_result で作り直し、同じ条件で比べる（data/v3_eval.parquet は上書きしない）。
使い方: python3 analyze/margin_blend_test.py
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import ability_index_v3 as V
import ability_margin_test as M
import front_ace_blend_test as FA
import ability_blend_backtest as B


def theta_table(alpha, races, prevs, going, sires, margins):
    rows = []
    for surface in ("芝", "ダ"):
        obs0, hmap, jmap, rr = V.build(races, surface, prevs)
        M.apply_margin(obs0, rr, margins, alpha)
        byday0, _ = V.walk_forward(obs0, hmap, jmap, rr)
        obs, hmap, jmap, rr = V.build(races, surface, prevs, going, sires, byday0)
        M.apply_margin(obs, rr, margins, alpha)
        byday, _ = V.walk_forward(obs, hmap, jmap, rr)
        for ri, e in obs["meta"]:
            r = rr[ri]
            if r["dt"] not in byday:
                continue
            theta, W, a, beta = byday[r["dt"]]
            j = hmap[e["horse_id"]]
            rows.append({"馬名": e["horse_name"], "dt": r["dt"], "v3": theta[j] if W[j] > 0 else np.nan})
    t = pd.DataFrame(rows)
    return t[~t.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])["v3"]


def main():
    races = A.load_races()
    prevs, going, sires = V.prev_map(), V.going_map(races), V.sire_map()
    margins = M.load_margins()
    base = FA.build()
    pays = FA.payouts()
    evals, names = {}, []
    print("■ 学習した重み（〜2025/06）")
    for alpha, lab in ((0.0, "G 着順のみ（現行）"), (0.5, "G 着順+秒差")):
        th = theta_table(alpha, races, prevs, going, sires, margins)
        df = base.copy()
        v = df.join(th.rename("v3n"), on=["馬名", "dt"])["v3n"]
        df["cover"] = v.notna()
        m = v.groupby(df["rid"]).transform("mean")
        df["v3_c"] = (v.fillna(m) - m).fillna(0.0)
        print(f"   {lab}: 指数付与率 {df['cover'].mean():.1%}")
        for cols, suf in ((["v3_c", "rest_sum", "ace"], ""), (["v3_c", "rest_sum"], "（巧者なし）")):
            name = lab + suf
            u, w = B.fit_util(df, cols, 0.5)
            df["r"] = pd.Series(-u, index=df.index).groupby(df["rid"]).rank(method="first")
            evals[name] = FA.evaluate(df, "r", pays)
            names.append(name)
            print(f"   {name:<24} {w}")
    for scope, f in (("買い条件（10〜13頭・重賞以外）", lambda e: e[e.n.between(10, 13) & ~e.g]), ("2勝以上 全レース", lambda e: e)):
        print(f"\n■ {scope}   ※（学習/テスト）・除3=上位3件除外")
        for name in names:
            FA.report(f(evals[name]), name)


if __name__ == "__main__":
    main()
