"""
頭数の多いレースで買い目を広げると回収率は上がるか（2026-10-04）
三連複・馬連・ワイドのBOX（5〜8頭）と三連複1軸流し（相手2〜5位〜2〜8位）を、頭数帯×重賞別に比較。
使い方: python3 analyze/field_width_test.py
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
trio, uma = load("3連複", 3), load("馬連", 2)
rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}

races = []
for key, g in df.groupby(["日付", "レース名"]):
    rid = rid_of.get(key)
    if rid not in trio or rid not in uma: continue
    g = g.sort_values("rank_G")
    if not 10 <= len(g) <= 13 or g["クラス"].iloc[0] == "重賞": continue
    races.append({"dt": g["dt"].iloc[0], "n": [int(x) for x in g["馬番"]], "trio": trio[rid], "uma": uma[rid]})
print(f"対象: 10〜13頭・重賞以外・2勝以上・払戻あり {len(races)}R（学習{sum(r['dt']<TRAIN_END for r in races)} / テスト{sum(r['dt']>=TRAIN_END for r in races)}）\n")

wide = load("ワイド", 2); tan = load("単勝", 1); fuku = load("複勝", 1)
rows = []
for key, g in df.groupby(["日付", "レース名"]):
    rid = rid_of.get(key)
    if not all(rid in x for x in (wide, uma, trio)): continue
    g = g.sort_values("rank_G"); nums = [int(x) for x in g["馬番"]]
    def got(tbl, bets):
        c, a = tbl[rid]; return sum(x for cc, x in zip(c, a) if cc in bets)
    rec = dict(dt=g["dt"].iloc[0], n=len(g), g=g["クラス"].iloc[0] == "重賞")
    for k in (5, 6, 7, 8):
        rec[f"三連複{k}頭BOX"] = (got(trio, {frozenset(c) for c in combinations(nums[:k], 3)}), len(list(combinations(range(k), 3))))
        rec[f"馬連{k}頭BOX"] = (got(uma, {frozenset(c) for c in combinations(nums[:k], 2)}), len(list(combinations(range(k), 2))))
        rec[f"ワイド{k}頭BOX"] = (got(wide, {frozenset(c) for c in combinations(nums[:k], 2)}), len(list(combinations(range(k), 2))))
    for e in (5, 6, 7, 8):
        bets = {frozenset((nums[0],) + c) for c in combinations(nums[1:e], 2)}
        rec[f"三連複1軸-2〜{e}位"] = (got(trio, bets), len(bets))
    rows.append(rec)
d = pd.DataFrame(rows)
keys = [k for k in d.columns if k not in ("dt", "n", "g")]
def table(x, title):
    print(f"\n■ {title}  n={len(x)}（学習{(x.dt<TRAIN_END).sum()}/テスト{(x.dt>=TRAIN_END).sum()}）")
    print(f"   {'買い方':<16}{'点数':>4}{'的中率':>8}{'ROI':>7}{'学習':>6}{'テスト':>7}{'上位3除外':>9}")
    for k in keys:
        got = x[k].apply(lambda t: t[0]); ptr = x[k].apply(lambda t: t[1]); pts = int(ptr.mode()[0])
        r = lambda m: got[m].sum() / (ptr[m].sum() * 100) * 100
        allm = pd.Series(True, index=x.index)
        drop = got.nlargest(3).index
        ex = got.drop(drop).sum() / (ptr.drop(drop).sum() * 100) * 100
        print(f"   {k:<16}{pts:>4}{(got>0).mean()*100:>7.1f}%{r(allm):>6.0f}%{r(x.dt<TRAIN_END):>6.0f}{r(x.dt>=TRAIN_END):>7.0f}{ex:>8.0f}%")
table(d[d.n.between(10, 13) & ~d.g], "参考: 10〜13頭・重賞以外（今の買い条件）")
table(d[(d.n >= 15) & ~d.g], "15頭以上・重賞以外")
table(d[(d.n >= 15) & d.g], "15頭以上・重賞")
