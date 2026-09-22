"""
案Gのパラメータを学習して data/plan_g_params.json に保存する（2026-09-23）

案G = w1·z(能力指数v3の純粋な能力θ) + w2·z(現行スコアから能力系16因子を除いた残り)
  重みは学習期間（〜2025/06）のみで決定。テスト2025/07〜の成績は CLAUDE.md 参照。
使い方: python3 analyze/make_plan_g_params.py
"""
import json, sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M
import ability_blend_backtest as B


def main():
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"])
    print(f"v3付与率: {j['v3_c'].notna().mean():.1%}")
    m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    rest = [c for c in factors if c not in B.ABILITY_FACTORS]
    df["rest_sum"] = df[rest].sum(axis=1)

    _, w = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    p = B.PARAMS[("v3_c", "rest_sum")]
    out = BASE / "data" / "plan_g_params.json"
    out.write_text(json.dumps({
        "note": "案G: u = Σ w·(x-mu)/sd, x=[v3_c(能力指数v3の純粋な能力・レース内中心化), "
                "rest_sum(能力系16因子を除いた現行スコアのレース内中心化)]。学習 〜2025/06",
        "tau": 365, "lam": 2.0, "ykey": "yr", "ability_factors": B.ABILITY_FACTORS, **p},
        ensure_ascii=False, indent=1))
    print("保存:", out, w)


if __name__ == "__main__":
    main()
