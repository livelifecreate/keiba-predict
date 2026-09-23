"""
道悪ハイブリッドの検証（2026-09-23）

手作りの道悪適性（±0.5〜2.0）は能力指数v3に対して上乗せの価値がないと判明した
（全期間の残差回帰で係数 +0.018 ± 0.040）。代わりに v3 が推定した道悪効果
（重不良 × 馬の道悪実績 +0.295 / 父の道悪傾向 +0.131）を使う案を比較する。

比較する順位づけ（重みは学習期間〜2025/06のみで決定・テスト2025/07〜で評価）:
  G  現行運用   : v3のθ + 能力以外の因子合計（道悪適性を含む）
  G- 道悪抜き   : v3のθ + 能力以外の因子合計（道悪適性を除く）
  X  ハイブリッド: v3のθ + (能力以外 − 道悪適性) + v3が推定した道悪項
  X2 騎手も     : X にさらに v3が推定した騎手効果を足す
評価: 9馬券種（総合）＋重・不良レース限定の予想1位成績。
使い方: python3 analyze/hybrid_wet_backtest.py
"""
import json, sys, tempfile
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M
import ability_blend_backtest as B
import wet_track_calibration as WET
import verify.bet_analysis2 as ba2
from verify.bet_metrics_standard import sim_bet, BET_SPECS

TRAIN_END = pd.Timestamp(2025, 7, 1)


def main():
    raw = pd.read_csv(M.CSV, dtype=str)
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c", "wet_c", "jockey_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"])
    print(f"v3付与率: {j['v3_c'].notna().mean():.1%}")
    for c in ("v3_c", "wet_c", "jockey_c"):
        m = j.groupby("rid")[c].transform("mean")
        df[c] = (j[c].fillna(m) - m).fillna(0.0)

    rest = [c for c in factors if c not in B.ABILITY_FACTORS]
    df["rest_sum"] = df[rest].sum(axis=1)
    df["rest_no_wet"] = df["rest_sum"] - df["道悪適性"]
    print(f"手作りの道悪適性が0でない馬: {(df['道悪適性'].abs() > 1e-9).mean():.1%}"
          f" / v3の道悪項が0でない馬: {(df['wet_c'].abs() > 1e-9).mean():.1%}")

    utils, weights = {}, {}
    for lab, cols in [("G 現行(道悪あり)", ["v3_c", "rest_sum"]),
                      ("G- 道悪抜き", ["v3_c", "rest_no_wet"]),
                      ("X ハイブリッド", ["v3_c", "rest_no_wet", "wet_c"]),
                      ("X2 ハイブリッド+騎手", ["v3_c", "rest_no_wet", "wet_c", "jockey_c"])]:
        u, w = B.fit_util(df, cols, 0.5)
        utils[lab], weights[lab] = u, w
    for k, v in weights.items():
        print(f"  {k}: {v}")

    full = WET.going_from_full_history()
    fb = {}
    for q in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(q.read_text())
        if d.get("date"):
            fb[(M.jp_date(d["date"]), d.get("venue", ""), d.get("surface", ""))] = WET.NORM.get(d.get("track_condition") or "", "")
    surf = np.where(df["コース"].astype(str).str.startswith("芝"), "芝", "ダ")
    df["going"] = [full.get(k) or fb.get(k, "") for k in zip(df["dt"], df["競馬場"], surf)]

    test = df[df.dt >= TRAIN_END]
    raw_te = raw.loc[test.index]
    tmp = Path(tempfile.mkdtemp())
    rows_all, rows_wet = {}, {}
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
        rows_all[lab] = {n: sim_bet(races, k) for n, k in BET_SPECS}
        top = t[rk == 1]
        rows_all[lab]["_t"] = ((top["実着順"] == 1).mean() * 100, (top["実着順"] <= 3).mean() * 100, len(races))
        w = top[top["going"].isin(["重", "不良"])]
        rows_wet[lab] = (len(w), (w["実着順"] == 1).mean() * 100, (w["実着順"] <= 3).mean() * 100,
                         (w["単勝オッズ"] * (w["実着順"] == 1)).mean() * 100)

    labels = list(utils)
    print(f"\n===== 総合（テスト2025/07〜・払戻ありn={rows_all[labels[0]]['_t'][2]}R）的中率% / ROI% =====")
    print(f"{'馬券種別':<14}" + "".join(f"{l[:16]:>18}" for l in labels))
    print(f"{'予想1位 勝率/複勝':<14}" + "".join(f"{rows_all[l]['_t'][0]:>9.1f}/{rows_all[l]['_t'][1]:>6.1f}  " for l in labels))
    for n, _ in BET_SPECS:
        print(f"{n:<14}" + "".join(f"{rows_all[l][n]['hit_rate']:>9.1f}/{rows_all[l][n]['roi']:>6.0f}  " for l in labels))

    print("\n===== 重・不良レースでの予想1位（テスト期間）=====")
    print(f"{'順位づけ':<24}{'頭数':>6}{'勝率':>8}{'複勝率':>8}{'単勝ROI':>9}")
    for l in labels:
        n, w, p, r = rows_wet[l]
        print(f"{l:<24}{n:>6}{w:>7.1f}%{p:>7.1f}%{r:>8.0f}%")


if __name__ == "__main__":
    main()
