"""
馬連の買い方の比較（2026-10-12）

実戦で「馬連のほうが三連複より良い気がする」というユーザーの感覚から。
案G（巧者入り3変数・重みは〜2025/06で学習）の順位で、馬連の買い方を事前に固定して比べる。
  馬連: 1-2(1点) / 1軸流し 相手2〜3,2〜4,2〜5,2〜6 / 上位3,4,5,6頭BOX / 1・2位軸フォーメーション(1,2-3,4,5 +1-2 =7点)
  参考: ワイド1軸2〜5・ワイド5頭BOX・三連複1軸6点
指標: 的中率・ROI（学習/テスト）・上位3件除外ROI・1R収支・最長連敗。
使い方: python3 analyze/umaren_pattern_test.py
"""
import sys
from itertools import combinations
from pathlib import Path
import pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import front_ace_blend_test as FA
import ability_blend_backtest as B


def pairs_axis(n, k):           # 1軸流し 相手2〜k位
    return {frozenset((n[0], n[i])) for i in range(1, k)}


def pairs_box(n, k):
    return {frozenset(c) for c in combinations(n[:k], 2)}


PATTERNS = {
    "馬連 1-2": ("馬連", lambda n: {frozenset(n[:2])}),
    "馬連 1軸-2〜3位": ("馬連", lambda n: pairs_axis(n, 3)),
    "馬連 1軸-2〜4位": ("馬連", lambda n: pairs_axis(n, 4)),
    "馬連 1軸-2〜5位": ("馬連", lambda n: pairs_axis(n, 5)),
    "馬連 1軸-2〜6位": ("馬連", lambda n: pairs_axis(n, 6)),
    "馬連 上位3頭BOX": ("馬連", lambda n: pairs_box(n, 3)),
    "馬連 上位4頭BOX": ("馬連", lambda n: pairs_box(n, 4)),
    "馬連 上位5頭BOX": ("馬連", lambda n: pairs_box(n, 5)),
    "馬連 上位6頭BOX": ("馬連", lambda n: pairs_box(n, 6)),
    "馬連 1,2位-3〜5位+1-2": ("馬連", lambda n: {frozenset(n[:2])} | {frozenset((a, b)) for a in n[:2] for b in n[2:5]}),
    "ワイド 1軸-2〜5位": ("ワイド", lambda n: pairs_axis(n, 5)),
    "ワイド 上位5頭BOX": ("ワイド", lambda n: pairs_box(n, 5)),
    "三連複 1軸-2〜5位": ("3連複", lambda n: {frozenset((n[0],) + c) for c in combinations(n[1:5], 2)}),
}


def per_race(df, pays):
    trio, uma, wide = pays
    tbl = {"3連複": trio, "馬連": uma, "ワイド": wide}
    rows = []
    for key, g in df.groupby(["日付", "レース名"]):
        if key not in trio or key not in uma or key not in wide: continue
        g = g.sort_values("r")
        nums = [int(x) for x in g["馬番"]]
        if len(set(nums)) != len(nums) or len(nums) < 7: continue
        t = g.iloc[0]
        row = dict(dt=t["dt"], n=len(g), g=t["クラス"] == "重賞")
        for name, (kind, f) in PATTERNS.items():
            bets = f(nums)
            c, a = tbl[kind][key]
            row[name] = sum(x for cc, x in zip(c, a) if cc in bets)
            row[name + "_pts"] = len(bets)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("dt").reset_index(drop=True)


def streak(hit):
    best = cur = 0
    for h in hit:
        cur = 0 if h else cur + 1
        best = max(best, cur)
    return best


def report(e, title):
    print(f"\n■ {title}（n={len(e)}R・学習{(e.dt < FA.TRAIN_END).sum()} / テスト{(e.dt >= FA.TRAIN_END).sum()}）")
    print("   買い方                   点数 | 的中率   ROI（学習/テスト）  上位3除外  1R収支   最長連敗")
    tr, te = e.dt < FA.TRAIN_END, e.dt >= FA.TRAIN_END
    for name in PATTERNS:
        pay, inv = e[name], e[name + "_pts"] * 100
        roi = lambda m: pay[m].sum() / inv[m].sum() * 100
        top3 = pay.nlargest(3).index
        ex3 = pay.drop(top3).sum() / inv.drop(top3).sum() * 100
        hit = pay > 0
        print(f"   {name:<22} {inv.mean()/100:4.1f} | {hit.mean()*100:5.1f}%  {pay.sum()/inv.sum()*100:4.0f}%（{roi(tr):.0f}/{roi(te):.0f}）"
              f"   {ex3:4.0f}%   {(pay - inv).mean():+5.0f}円   {streak(hit)}")


def main():
    df = FA.build()
    pays = FA.payouts()
    u, w = B.fit_util(df, ["v3_c", "rest_sum", "ace"], 0.5)
    df["r"] = pd.Series(-u, index=df.index).groupby(df["rid"]).rank(method="first")
    print(f"重み {w}")
    e = per_race(df, pays)
    report(e[e.n.between(10, 13) & ~e.g], "買い条件（10〜13頭・重賞以外）")
    report(e[~e.g], "2勝以上 重賞以外 全頭数")
    report(e[e.n >= 14], "14頭以上（参考）")


if __name__ == "__main__":
    main()
