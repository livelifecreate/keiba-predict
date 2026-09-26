"""
なぜ外れるのか／穴はどういう時に来るのか（2026-09-26）

① 外れの解剖: 買い条件（10〜13頭・重賞以外）で三連複を外したとき、
   買い目から漏れた3着内馬は何者だったか（人気・我々の順位・オッズ）。
② 穴の条件: 人気薄（8番人気以下）が3着内に入る率を、レース条件別に比較する。
③ 穴馬の正体: 3着内に入った人気薄と、入らなかった人気薄で、事前に分かる特徴がどう違うか。
   （34因子＋能力指数＋脚質＋ペース。標準化した差の大きい順に並べる）
使い方: python3 analyze/upset_profile.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M
import ability_blend_backtest as B
import wet_track_calibration as WET
import pace_model as P
import verify.bet_analysis2 as ba2


def build():
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"])
    m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)
    u, _ = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["u_G"] = u
    df["rank_G"] = df.groupby("rid")["u_G"].rank(ascending=False, method="first")
    df["pop"] = df["市場人気"].astype(float)
    df["odds"] = df["単勝オッズ"].astype(float)
    df["n"] = df.groupby("rid")["馬名"].transform("size")

    # 会場・馬場・脚質・ペース
    venue_of, surf_of, dist_of, id_of = {}, {}, {}, {}
    for q in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(q.read_text())
        rid = d.get("race_id") or q.stem
        venue_of[rid], surf_of[rid] = d.get("venue") or "", d.get("surface") or ""
        mm = re.search(r"(\d+)", str(d.get("distance") or ""))
        dist_of[rid] = int(mm.group(1)) if mm else 0
        for e in d["entries"]:
            if e.get("horse_id"):
                id_of[(e["horse_name"], d.get("date"))] = e["horse_id"]
    rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}
    df["rr_id"] = [rid_of.get(k) for k in zip(df["日付"], df["レース名"])]
    df["hid"] = [id_of.get((n, d)) for n, d in zip(df["馬名"], df["日付"])]
    df["venue"] = df["rr_id"].map(venue_of)
    full = WET.going_from_full_history()
    surf = np.where(df["コース"].astype(str).str.startswith("芝"), "芝", "ダ")
    df["going"] = [full.get(k, "") for k in zip(df["dt"], df["venue"], surf)]
    df["surface"] = surf

    runs = P.load_runs().sort_values("dt")
    h1, h4 = defaultdict(list), defaultdict(list)
    for r in runs.dropna(subset=["first_corner"]).itertuples():
        h1[r.hid].append((r.dt, (r.first_corner - 1) / (r.field - 1)))
    def before(h, hid, dt, k=5):
        v = [p for d, p in h.get(hid, []) if d < dt]
        return float(np.mean(v[-k:])) if v else np.nan
    df["leg"] = [before(h1, h, dt) for h, dt in zip(df["hid"], df["dt"])]
    return df, factors


def main():
    df, factors = build()
    buy = df[(df.n.between(10, 13)) & (df["クラス"] != "重賞")]
    print(f"全体 {df.rid.nunique():,}R / 買い条件 {buy.rid.nunique():,}R\n")

    # ---------- ① 外れの解剖
    print("■ ① 買い条件のレースで、三連複の買い目から漏れた3着内馬は何者か")
    miss, covered = [], []
    for rid, g in buy.groupby("rid"):
        g = g.sort_values("rank_G")
        picked = set(g["馬名"].iloc[:5])           # 軸1位＋相手2〜5位
        for _, r in g[g["実着順"] <= 3].iterrows():
            (covered if r["馬名"] in picked else miss).append(r)
    miss, covered = pd.DataFrame(miss), pd.DataFrame(covered)
    tot = len(miss) + len(covered)
    print(f"  3着内馬 {tot:,}頭のうち、買い目に入っていた {len(covered):,}頭（{len(covered) / tot:.0%}）／"
          f"漏れた {len(miss):,}頭（{len(miss) / tot:.0%}）")
    print(f"  漏れた馬の 平均人気 {miss['pop'].mean():.1f}（拾えた馬 {covered['pop'].mean():.1f}）"
          f"／平均オッズ {miss['odds'].median():.1f}倍（{covered['odds'].median():.1f}倍）")
    print("  漏れた馬の我々の順位:", ", ".join(f"{k}位{v}頭" for k, v in miss["rank_G"].astype(int).value_counts().sort_index().head(8).items()))
    print("  漏れた馬の人気:", ", ".join(f"{int(k)}番人気{v}頭" for k, v in miss["pop"].value_counts().sort_index().head(8).items()))

    # ---------- ② 穴が来る条件
    print("\n■ ② 人気薄（8番人気以下）が3着内に入る率 — レース条件別")
    df["is_upset"] = (df["pop"] >= 8) & (df["実着順"] <= 3)
    race = df.groupby("rid").agg(n=("n", "first"), cls=("クラス", "first"), going=("going", "first"),
                                 surface=("surface", "first"), venue=("venue", "first"),
                                 upset=("is_upset", "sum"), dt=("dt", "first")).reset_index()
    race["has_upset"] = race.upset > 0
    print(f"  全体: {race.has_upset.mean():.1%} のレースで8番人気以下が3着内に入る（1レース平均{race.upset.mean():.2f}頭）")
    for title, col, order in [("頭数", "n", None), ("クラス", "cls", ["2勝クラス", "3勝クラス", "OP", "重賞"]),
                              ("馬場", "going", ["良", "稍重", "重", "不良"]), ("芝ダ", "surface", ["芝", "ダ"])]:
        print(f"  【{title}】", end=" ")
        keys = order or sorted(race[col].dropna().unique())
        out = []
        for k in keys:
            g = race[race[col] == k]
            if len(g) >= 40:
                out.append(f"{k}: {g.has_upset.mean():.0%}({len(g)}R)")
        print(" / ".join(out))

    # ---------- ③ 穴馬の正体
    print("\n■ ③ 3着内に来た人気薄と、来なかった人気薄の違い（8番人気以下・標準化した差）")
    u = df[df["pop"] >= 8].copy()
    hit, non = u[u["実着順"] <= 3], u[u["実着順"] > 3]
    print(f"  対象 {len(u):,}頭（うち3着内 {len(hit):,}頭 = {len(hit) / len(u):.1%}）")
    cands = factors + ["v3_c", "rest_sum", "leg", "odds", "rank_G"]
    rows = []
    for c in cands:
        a, b = pd.to_numeric(hit[c], errors="coerce"), pd.to_numeric(non[c], errors="coerce")
        if a.notna().sum() < 100 or a.std() == 0 and b.std() == 0:
            continue
        sd = np.sqrt((a.var() + b.var()) / 2)
        if not sd or np.isnan(sd):
            continue
        rows.append({"因子": c, "3着内": a.mean(), "着外": b.mean(), "差": (a.mean() - b.mean()) / sd})
    r = pd.DataFrame(rows).sort_values("差", key=abs, ascending=False)
    print(f"{'因子':<20}{'3着内の平均':>12}{'着外の平均':>12}{'標準化した差':>12}")
    for _, x in r.head(14).iterrows():
        print(f"{x['因子']:<20}{x['3着内']:>12.3f}{x['着外']:>12.3f}{x['差']:>+12.3f}")


if __name__ == "__main__":
    main()
