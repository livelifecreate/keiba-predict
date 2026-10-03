"""
地方での実績は中央でどれくらい通用するか（2026-10-03）

案Gの能力指数は中央（race_result）のレースだけで計算し、地方の過去走は数えていない。
地方を走ってきた馬が、案Gの順位や人気から期待される以上/以下に走るかを確認する。

群（レース日より前の直近5走で判定・先読みなし）:
  地方なし / 地方を走ったが勝ちなし / 地方で勝ちあり / 地方デビュー（初出走が地方）
指標: 3着内率の実績と期待値の差。期待値は「同じ頭数帯で同じ案G順位（または同じ人気）の平均3着内率」。
学習(〜2025/06)/テスト(2025/07〜)の両方で同じ向きかを見る。
使い方: python3 analyze/nar_history_test.py
"""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M
import ability_blend_backtest as B

TRAIN_END = pd.Timestamp(2025, 7, 1)
NAR = {"門別", "帯広", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢", "笠松", "名古屋", "園田", "姫路", "高知", "佐賀"}


def histories():
    """{馬名: [(日付, 地方か, 着順)]}（馬名は race_result の horse_id 経由で対応づけ）"""
    id2name = {}
    for p in (BASE / "cache" / "race_result").glob("*.json"):
        for e in json.loads(p.read_text()).get("entries", []):
            if e.get("horse_id"):
                id2name[e["horse_id"]] = e.get("horse_name", "")
    out = {}
    for p in (BASE / "cache" / "horse_full_history").glob("*.json"):
        name = id2name.get(p.stem)
        if not name:
            continue
        rows = []
        for r in json.loads(p.read_text()):
            m = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
            if not m:
                continue
            pos = int(r["pos_raw"]) if str(r.get("pos_raw", "")).isdigit() else 99
            rows.append((pd.Timestamp(*map(int, m.groups())), re.sub(r"\d", "", r.get("kaisan", "")) in NAR, pos))
        out[name] = sorted(rows)
    return out


def main():
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"]); m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    df["v3_missing"] = j["v3_c"].isna()
    df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)
    u, _ = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["rank_G"] = df.assign(u=u).groupby("rid")["u"].rank(ascending=False, method="first")
    df["pop"] = df["市場人気"].astype(float)
    df["top3"] = (df["実着順"].astype(float) <= 3).astype(float)
    df["nbin"] = pd.cut(df["出走頭数"].astype(int), [0, 12, 15, 18], labels=["〜12", "13-15", "16〜"])

    H = histories()
    grp = []
    for name, dt in zip(df["馬名"], df["dt"]):
        h = [x for x in H.get(name, []) if x[0] < dt]
        last5 = h[-5:]
        if not h:
            grp.append("通算成績なし")
        elif h[0][1] and sum(1 for x in h if not x[1]) <= 3:
            grp.append("地方デビュー(中央3走以内)")
        elif any(x[1] and x[2] == 1 for x in last5):
            grp.append("近5走に地方で勝ち")
        elif any(x[1] for x in last5):
            grp.append("近5走に地方(勝ちなし)")
        else:
            grp.append("地方なし")
    df["grp"] = grp

    # 期待値: 同じ頭数帯×同じ順位（案G / 人気）の平均3着内率（全期間）
    df["exp_G"] = df.groupby(["nbin", "rank_G"], observed=True)["top3"].transform("mean")
    df["exp_M"] = df.groupby(["nbin", "pop"], observed=True)["top3"].transform("mean")
    df["win_ret"] = np.where(df["実着順"].astype(float) == 1, df["単勝オッズ"].astype(float) * 100, 0)

    print(f"\n対象: 2勝クラス以上 {df['rid'].nunique()}R / {len(df)}頭\n")
    print(f"{'群':<22}{'頭数':>6}{'3着内':>8}{'案G期待':>8}{'差':>7}{'人気期待':>8}{'差':>7}"
          f"{'差(案G) 学習/テスト':>20}{'平均人気':>8}{'v3欠損':>7}{'単勝ROI':>8}")
    for g in ["地方なし", "近5走に地方(勝ちなし)", "近5走に地方で勝ち", "地方デビュー(中央3走以内)", "通算成績なし"]:
        x = df[df.grp == g]
        if len(x) < 30:
            print(f"{g:<22}{len(x):>6}  （少数）"); continue
        tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
        dG = lambda y: (y.top3.mean() - y.exp_G.mean()) * 100
        print(f"{g:<22}{len(x):>6}{x.top3.mean()*100:>7.1f}%{x.exp_G.mean()*100:>7.1f}%{dG(x):>+6.1f}"
              f"{x.exp_M.mean()*100:>7.1f}%{(x.top3.mean()-x.exp_M.mean())*100:>+6.1f}"
              f"{dG(tr):>+11.1f} /{dG(te):>+6.1f}{x['pop'].mean():>8.1f}{x.v3_missing.mean()*100:>6.0f}%"
              f"{x.win_ret.mean():>7.0f}%")


if __name__ == "__main__":
    main()
