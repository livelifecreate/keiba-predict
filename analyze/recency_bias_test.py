"""
市場は前走の結果に過剰反応するか（2026-10-04）

ネットで多い説「前走で人気になって凡走した馬は次走で過小評価される／人気薄で好走した馬は過大評価される」を検証。
期待値＝同じ頭数帯×同じ人気の平均（3着内率・単勝回収）。案Gの順位との組み合わせも見る。学習/テスト別。
使い方: python3 analyze/recency_bias_test.py
"""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M, ability_blend_backtest as B
TRAIN_END = pd.Timestamp(2025, 7, 1)

def prev_runs():
    id2name = {}
    for p in (BASE / "cache" / "race_result").glob("*.json"):
        for e in json.loads(p.read_text()).get("entries", []):
            if e.get("horse_id"): id2name[e["horse_id"]] = e.get("horse_name", "")
    out = {}
    for p in (BASE / "cache" / "horse_full_history").glob("*.json"):
        nm = id2name.get(p.stem)
        if not nm: continue
        rows = []
        for r in json.loads(p.read_text()):
            m = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
            if not m or not str(r.get("pos_raw", "")).isdigit() or not str(r.get("pop", "")).isdigit(): continue
            rows.append((pd.Timestamp(*map(int, m.groups())), int(r["pos_raw"]), int(r["pop"]), int(r["field"]) if str(r.get("field","")).isdigit() else 0))
        out[nm] = sorted(rows)
    return out

def main():
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"]); m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)
    u, _ = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["rank_G"] = df.assign(u=u).groupby("rid")["u"].rank(ascending=False, method="first")
    df["pop"] = df["市場人気"].astype(float)
    df["top3"] = (df["実着順"].astype(float) <= 3).astype(float)
    df["win"] = np.where(df["実着順"].astype(float) == 1, df["単勝オッズ"].astype(float) * 100, 0.0)
    df["nbin"] = pd.cut(df["出走頭数"].astype(int), [0, 12, 15, 18])
    df["exp3"] = df.groupby(["nbin", "pop"], observed=True)["top3"].transform("mean")
    df["expW"] = df.groupby(["nbin", "pop"], observed=True)["win"].transform("mean")

    P = prev_runs()
    pp, ppop = [], []
    for nm, dt in zip(df["馬名"], df["dt"]):
        h = [x for x in P.get(nm, []) if x[0] < dt]
        pp.append(h[-1][1] if h else np.nan); ppop.append(h[-1][2] if h else np.nan)
    df["ppos"], df["ppop"] = pp, ppop

    def line(x, lab):
        if len(x) < 40: print(f"  {lab:<34} n={len(x)}（少数）"); return
        tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
        d3 = lambda y: (y.top3.mean() - y.exp3.mean()) * 100
        roi = lambda y: y.win.mean()
        print(f"  {lab:<34} n={len(x):>5} 3着内 {x.top3.mean()*100:5.1f}% 人気期待{x.exp3.mean()*100:5.1f}% 差{d3(x):+5.1f}（学習{d3(tr):+5.1f}/テスト{d3(te):+5.1f}）"
              f" 単勝ROI {roi(x):4.0f}%（学習{roi(tr):4.0f}/テスト{roi(te):4.0f}・人気期待{x.expW.mean():4.0f}%）")

    print("\n■ 前走の人気と着順（今回の人気に対する上振れ/下振れ）")
    line(df[df.ppop.notna()], "全体（前走あり）")
    line(df[(df.ppop <= 3) & (df.ppos >= 6)], "前走1-3番人気で6着以下（人気で凡走）")
    line(df[(df.ppop == 1) & (df.ppos >= 4)], "前走1番人気で4着以下")
    line(df[(df.ppop >= 7) & (df.ppos <= 3)], "前走7番人気以下で3着内（人気薄で好走）")
    line(df[(df.ppos >= 10)], "前走10着以下")
    line(df[(df.ppos.between(4, 6))], "前走4-6着")
    print("\n■ 案Gの評価との組み合わせ（案G上位3頭に限定）")
    t = df[df.rank_G <= 3]
    line(t, "案G上位3頭 全体")
    line(t[(t.ppop <= 3) & (t.ppos >= 6)], "案G上位3×前走人気で凡走")
    line(t[(t.ppos >= 10)], "案G上位3×前走10着以下")
    line(t[(t.ppop >= 7) & (t.ppos <= 3)], "案G上位3×前走人気薄で好走")

if __name__ == "__main__":
    main()
