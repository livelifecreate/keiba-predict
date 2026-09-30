"""
予想1位が1番人気でないとき、三連複の軸を「予想1位」と「1番人気」のどちらにすべきか（2026-09-30）
使い方: python3 analyze/axis_favorite_test.py   条件A/Bと、広げた条件（C/D・1番人気の予想順位別）を学習/テスト別に出す
"""
import sys
from itertools import combinations
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path("/Users/du/Documents/競馬予想システム")
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(BASE / "analyze"))
import market_residual_model as M, ability_blend_backtest as B, verify.bet_analysis2 as ba2
TRAIN_END = pd.Timestamp(2025, 7, 1)

df, factors = M.load()
v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
j = df.join(v3, on=["馬名", "dt"]); m = j.groupby("rid")["v3_c"].transform("mean")
df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)
u, _ = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
df["rank_G"] = df.assign(u=u).groupby("rid")["u"].rank(ascending=False, method="first")

def load(kind, k):
    out = {}
    for p in (BASE / "cache" / "payouts").glob("*.json"):
        nums, am = ba2.get_payout(p.stem, kind)
        if am and len(nums) >= k * len(am):
            out[p.stem] = ([frozenset(nums[k*i:k*i+k]) for i in range(len(am))], am)
    return out
trio = load("3連複", 3)
rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}

rows = []
for key, g in df.groupby(["日付", "レース名"]):
    rid = rid_of.get(key)
    if rid not in trio: continue
    g = g.sort_values("rank_G")
    if len(g) < 8: continue
    pop = g["市場人気"].astype(float).values
    if not (pop == 1).any(): continue
    nums = [int(x) for x in g["馬番"]]; fin = g["実着順"].astype(float).values
    fav_i = int(np.where(pop == 1)[0][0])            # 1番人気の予想順位-1
    combos, am = trio[rid]
    def trio_pay(axis, others):
        bets = {frozenset((axis,) + c) for c in combinations(others, 2)}
        return sum(a for c, a in zip(combos, am) if c in bets), 100 * len(bets)
    top5 = nums[:5]
    gA, iA = trio_pay(nums[0], tuple(top5[1:]))                   # 予想1位軸（現行）
    fav = nums[fav_i]
    oth = tuple(x for x in top5 if x != fav)[:4] if fav in top5 else tuple(top5[:4])
    gF, iF = trio_pay(fav, oth)                                   # 1番人気軸・相手=予想上位の残り4頭
    rows.append(dict(dt=g["dt"].iloc[0], n=len(g), cls=g["クラス"].iloc[0],
        p1pop=pop[0], p2pop=pop[1], fav_rank=fav_i + 1, fav_odds=float(g["単勝オッズ"].values[fav_i]),
        p1_fin=fin[0], fav_fin=fin[fav_i], p1_odds=float(g["単勝オッズ"].values[0]),
        gA=gA, iA=iA, gF=gF, iF=iF))
d = pd.DataFrame(rows)
d["buy"] = d.n.between(10, 13) & (d.cls != "重賞")

def rep(x, lab):
    if len(x) < 20:
        print(f"  {lab}: n={len(x)}（少数）"); return
    tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
    roi = lambda y, g, i: y[g].sum() / y[i].sum() * 100 if len(y) else np.nan
    ex = lambda y, g, i: roi(y.drop(y[g].nlargest(3).index), g, i)
    print(f"  {lab}: n={len(x)}（学習{len(tr)}/テスト{len(te)}）")
    print(f"    勝率  予想1位 {(x.p1_fin==1).mean()*100:5.1f}% / 1番人気 {(x.fav_fin==1).mean()*100:5.1f}%"
          f"   複勝率 予想1位 {(x.p1_fin<=3).mean()*100:5.1f}% / 1番人気 {(x.fav_fin<=3).mean()*100:5.1f}%")
    print(f"    単勝ROI 予想1位 {(x.p1_odds*(x.p1_fin==1)).mean()*100:5.0f}% / 1番人気 {(x.fav_odds*(x.fav_fin==1)).mean()*100:5.0f}%")
    for nm, g, i in (("三連複 予想1位軸", "gA", "iA"), ("三連複 1番人気軸", "gF", "iF")):
        print(f"    {nm}: 的中{(x[g]>0).mean()*100:5.1f}% ROI{roi(x,g,i):5.0f}% 学習{roi(tr,g,i):5.0f}% テスト{roi(te,g,i):5.0f}% 上位3除外{ex(x,g,i):5.0f}%")
    tr_diff = ((tr.fav_fin<=3).mean() - (tr.p1_fin<=3).mean())*100
    te_diff = ((te.fav_fin<=3).mean() - (te.p1_fin<=3).mean())*100
    print(f"    複勝率の差(1番人気−予想1位): 学習{tr_diff:+.1f}pt / テスト{te_diff:+.1f}pt")

def short(x, lab):
    if len(x) < 20:
        print(f"  {lab:<30} n={len(x)}（少数）"); return
    tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
    roi = lambda y, g, i: y[g].sum() / y[i].sum() * 100 if len(y) else float("nan")
    ex = lambda y, g, i: roi(y.drop(y[g].nlargest(3).index), g, i)
    dp = lambda y: ((y.fav_fin <= 3).mean() - (y.p1_fin <= 3).mean()) * 100
    print(f"  {lab:<30} n={len(x):>4}({len(tr)}/{len(te)}) 3着内 予想1位{(x.p1_fin<=3).mean()*100:5.1f}% 1人気{(x.fav_fin<=3).mean()*100:5.1f}%"
          f" 差 学習{dp(tr):+5.1f}/テスト{dp(te):+5.1f}pt | 三連複 的中{(x.gA>0).mean()*100:.1f}→{(x.gF>0).mean()*100:.1f}%"
          f" ROI 予想1位軸{roi(x,'gA','iA'):.0f}%({roi(tr,'gA','iA'):.0f}/{roi(te,'gA','iA'):.0f}) 1人気軸{roi(x,'gF','iF'):.0f}%({roi(tr,'gF','iF'):.0f}/{roi(te,'gF','iF'):.0f}) 上位3除外 {ex(x,'gA','iA'):.0f}/{ex(x,'gF','iF'):.0f}")

for scope, s in (("全レース(2勝以上・8頭以上)", d), ("買い条件(10〜13頭・重賞以外)", d[d.buy])):
    print(f"\n■ {scope}")
    in5 = s.fav_rank <= 5
    short(s[(s.p1pop == 2) & (s.fav_rank == 2)], "A 予想1位=2人気・予想2位=1人気")
    short(s[s.p1pop == 2], "B 予想1位=2人気")
    short(s[(s.p1pop >= 3) & in5], "C 予想1位=3人気以下・1人気が上位5内")
    short(s[(s.p1pop != 1) & in5], "D 予想1位≠1人気・1人気が上位5内")
    for k in (2, 3, 4, 5):
        short(s[(s.p1pop != 1) & (s.fav_rank == k)], f"  1番人気=予想{k}位")
