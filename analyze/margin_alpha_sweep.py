"""
着順と秒差の混ぜ方の比較（2026-10-05）

「順位の価値は人の心理で、本当は着差の秒数こそ能力では」という仮説の検証。
v3 の走りの評価 y = (1-α)×着順の標準化 + α×秒差の標準化（秒差は1600m換算・cap秒で頭打ち）を
  α = 0 / 0.25 / 0.5 / 0.75 / 1.0（cap=2秒） と、α=1.0 で cap = 1 / 3 / 5秒
で推定し直し、
 ① 能力指数だけで順位をつけたときの予測力（対数損失・予想1位の勝率/複勝率・2勝以上/全クラス）
 ② 案G（v3_c + rest_sum + ace）に入れて重みを学習し直したときの馬券成績（買い条件・2勝以上全レース）
を比べる。学習〜2025/06、テスト2025/07〜。
使い方: python3 analyze/margin_alpha_sweep.py
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

UPPER = ["2勝クラス", "3勝クラス", "OP", "重賞"]


def apply_margin(obs, rr, margins, alpha, cap):
    """M.apply_margin の頭打ち幅を変えられる版"""
    if alpha == 0:
        return
    y = obs["y"].copy()
    by_race = {}
    for k, (ri, e) in enumerate(obs["meta"]):
        by_race.setdefault(ri, []).append((k, e))
    for ri, items in by_race.items():
        m = margins.get(rr[ri]["rid"])
        if not m:
            continue
        vals = [m.get(e["horse_id"]) for _, e in items]
        if sum(v is not None for v in vals) < len(items) * 0.8:
            continue
        scale = 1600.0 / max(rr[ri]["dist"], 1000)
        s = np.array([-(min(v, cap) * scale) if v is not None else np.nan for v in vals], dtype=float)
        s = np.where(np.isnan(s), np.nanmin(s), s)
        sd = s.std()
        if sd < 1e-6:
            continue
        z = (s - s.mean()) / sd
        idx = [k for k, _ in items]
        y[idx] = (1 - alpha) * obs["y"][idx] + alpha * z
    obs["y"] = y


def estimate(alpha, cap, races, prevs, going, sires, margins):
    """(θのみ評価用の表, 馬名×日付→θ)"""
    ev, tab = [], []
    for surface in ("芝", "ダ"):
        obs0, hmap, jmap, rr = V.build(races, surface, prevs)
        apply_margin(obs0, rr, margins, alpha, cap)
        byday0, _ = V.walk_forward(obs0, hmap, jmap, rr)
        obs, hmap, jmap, rr = V.build(races, surface, prevs, going, sires, byday0)
        apply_margin(obs, rr, margins, alpha, cap)
        byday, _ = V.walk_forward(obs, hmap, jmap, rr)
        for ri, e in obs["meta"]:
            r = rr[ri]
            if r["dt"] not in byday:
                continue
            theta, W, a, beta = byday[r["dt"]]
            j = hmap[e["horse_id"]]
            v = theta[j] if W[j] > 0 else np.nan
            tab.append({"馬名": e["horse_name"], "dt": r["dt"], "v3": v})
            if r["cls"] != "新馬" and e.get("odds"):
                ev.append({"rid": r["rid"], "dt": r["dt"], "cls": r["cls"], "rank": e["rank"], "odds": e["odds"], "v3": v})
    ev = pd.DataFrame(ev)
    ev = ev[ev.groupby("rid")["v3"].transform(lambda s: s.notna().mean()) >= 0.6].copy()
    m = ev.groupby("rid")["v3"].transform("mean")
    ev["v3_c"] = (ev["v3"].fillna(m) - m).fillna(0.0)
    tab = pd.DataFrame(tab)
    tab = tab[~tab.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])["v3"]
    return ev, tab


INV = dict(trio6=600, trio5=1000, uma5=1000, wide5=1000)


def bets(e, inv=INV):
    out = {"p1": e.p1_t3.mean() * 100, "win": e.p1_win.mean()}
    for k, v in inv.items():
        out[k] = e[k].sum() / (len(e) * v) * 100
        out[k + "_hit"] = (e[k] > 0).mean() * 100
        out[k + "_ex"] = e[k].drop(e[k].nlargest(3).index).sum() / ((len(e) - 3) * v) * 100
    return out


def main():
    races = A.load_races()
    prevs, going, sires = V.prev_map(), V.going_map(races), V.sire_map()
    margins = M.load_margins()
    base = FA.build()
    pays = FA.payouts()
    settings = [(0.0, 2.0), (0.25, 2.0), (0.5, 2.0), (0.75, 2.0), (1.0, 2.0), (1.0, 1.0), (1.0, 3.0), (1.0, 5.0)]
    res = []
    for alpha, cap in settings:
        lab = f"α={alpha:.2f} cap={cap:.0f}秒"
        ev, tab = estimate(alpha, cap, races, prevs, going, sires, margins)
        r_all = V._eval(ev, ["v3_c"], "θ")
        r_up = V._eval(ev[ev.cls.isin(UPPER)], ["v3_c"], "θ")
        df = base.copy()
        v = df.join(tab.rename("v3n"), on=["馬名", "dt"])["v3n"]
        m = v.groupby(df["rid"]).transform("mean")
        df["v3_c"] = (v.fillna(m) - m).fillna(0.0)
        u, w = B.fit_util(df, ["v3_c", "rest_sum", "ace"], 0.5)
        df["r"] = pd.Series(-u, index=df.index).groupby(df["rid"]).rank(method="first")
        e = FA.evaluate(df, "r", pays)
        buy = e[e.n.between(10, 13) & ~e.g]
        res.append(dict(lab=lab, all=r_all, up=r_up, w=w, buy=bets(buy), buy_tr=bets(buy[buy.dt < FA.TRAIN_END]),
                        buy_te=bets(buy[buy.dt >= FA.TRAIN_END]), full=bets(e), nbuy=len(buy), nfull=len(e)))
        print(f"[済] {lab}  θのみ(2勝以上) 対数損失{r_up['logloss']:.4f} 複勝率{r_up['place']:.1%}  重み{w}", flush=True)

    print("\n■ 能力指数だけの予測力（テスト2025/07〜）")
    print("   設定                 | 全クラス 対数損失 / 1位勝率 / 1位複勝率 | 2勝以上 対数損失 / 1位勝率 / 1位複勝率")
    for r in res:
        a, u = r["all"], r["up"]
        print(f"   {r['lab']:<18} | {a['logloss']:.4f} / {a['win']:.1%} / {a['place']:.1%} | {u['logloss']:.4f} / {u['win']:.1%} / {u['place']:.1%}")
    for key, title, n in (("buy", "買い条件（10〜13頭・重賞以外）", "nbuy"), ("full", "2勝以上 全レース", "nfull")):
        print(f"\n■ 案Gに入れたとき: {title}  ※ROI（学習/テスト）・除3=上位3件除外")
        for r in res:
            b = r[key]
            line = f"   {r['lab']:<18} n={r[n]} 1位3着内{b['p1']:4.1f}% 単勝{b['win']:4.0f}%"
            for k in ("trio6", "trio5", "uma5", "wide5"):
                tt = f"（{r['buy_tr'][k]:.0f}/{r['buy_te'][k]:.0f}）" if key == "buy" else ""
                line += f" | {k} {b[k+'_hit']:4.1f}%/{b[k]:4.0f}%{tt}除3 {b[k+'_ex']:.0f}"
            print(line)


if __name__ == "__main__":
    main()
