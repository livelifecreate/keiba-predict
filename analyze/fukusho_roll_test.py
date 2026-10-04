"""
複勝転がしのバックテスト（2026-10-04）
案Gの予想1位の複勝を、条件に合うレースで時系列に k 回転がす（外れたら1,000円から再開）。
使い方: python3 analyze/fukusho_roll_test.py
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
fuku = load("複勝", 1)
rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}

rows = []
for key, g in df.groupby(["日付", "レース名"]):
    rid = rid_of.get(key)
    if rid not in fuku: continue
    g = g.sort_values("rank_G")
    top = g.iloc[0]
    c, a = fuku[rid]
    num = int(top["馬番"])
    pay = next((x for cc, x in zip(c, a) if cc == frozenset([num])), 0)
    rows.append(dict(dt=top["dt"], rid=rid, rno=int(rid[-2:]), pop=float(top["市場人気"]), odds=float(top["単勝オッズ"]), pay=pay,
                     fav_odds=float(g.loc[g["市場人気"].astype(float).idxmin(), "単勝オッズ"]),
                     fav_pay=next((x for cc, x in zip(c, a) if cc == frozenset([int(g.loc[g["市場人気"].astype(float).idxmin(), "馬番"])])), 0)))
d = pd.DataFrame(rows).sort_values(["dt", "rno", "rid"]).reset_index(drop=True)

sel = {
    "S1 予想1位すべて":             (d["pop"] > 0, "pay"),
    "S2 予想1位=1番人気":           (d["pop"] == 1, "pay"),
    "S3 予想1位=1人気・2.0倍未満":  ((d["pop"] == 1) & (d.odds < 2.0), "pay"),
    "S4 予想1位・3.0倍未満":        (d.odds < 3.0, "pay"),
    "参考 1番人気2.0倍未満(予想なし)": (d.fav_odds < 2.0, "fav_pay"),
}

def simulate(pays, k):
    """pays: 100円あたり払戻の時系列。k回転がす。成功/失敗で1,000円から再スタート"""
    chains = wins = 0; staked = returned = 0.0; mult = []
    i = 0
    while i + k <= len(pays):
        chains += 1; staked += 1000; bank = 1000.0; ok = True
        for j in range(k):
            p = pays[i + j]
            if p == 0:
                ok = False; i += j + 1; break
            bank *= p / 100
        else:
            i += k
        if ok:
            wins += 1; returned += bank; mult.append(bank / 1000)
    return chains, wins, staked, returned, (np.mean(mult) if mult else 0)

for name, (mask, col) in sel.items():
    x = d[mask]
    p = (x[col] > 0).mean(); r = x[col].sum() / (len(x) * 100)
    print(f"\n■ {name}: 対象{len(x)}R  1回ごと 的中{p*100:.1f}% 回収率{r*100:.0f}%（学習{x[x.dt<TRAIN_END][col].sum()/((x.dt<TRAIN_END).sum()*100)*100:.0f} / テスト{x[x.dt>=TRAIN_END][col].sum()/((x.dt>=TRAIN_END).sum()*100)*100:.0f}） 平均払戻{x[col][x[col]>0].mean():.0f}円")
    for k in (2, 3, 5):
        out = []
        for lab, y in (("全", x), ("学習", x[x.dt < TRAIN_END]), ("テスト", x[x.dt >= TRAIN_END])):
            ch, w, st, rt, m = simulate(list(y[col]), k)
            out.append(f"{lab} 回収{rt/st*100 if st else 0:4.0f}%")
            if lab == "全": head = f"   {k}回転がし: {ch}回挑戦 成功{w}回({w/ch*100 if ch else 0:4.1f}%) 成功時 平均{m:.2f}倍"
        print(head + " | " + " / ".join(out))
