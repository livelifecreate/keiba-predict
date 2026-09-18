"""
市場の歪み探索（2026-09-19）

「予想」を使わず、市場人気・オッズだけで機械的に買った場合のROIを馬券種×人気パターン別に出す。
控除率（単複20%・馬連ワイド22.5%・三連複25%）を超えて100%に届く領域が構造的に存在するかを見る。

データ（外部アクセスなし）: cache/race_result（全クラス）+ cache/payouts
的中判定は race_result の着順から行う（払戻の馬番文字列は '11718' のように分割が曖昧なため使わない）。
払戻の並びは 複勝=[1着,2着,3着]、ワイド=[1-2着,1-3着,2-3着] を仮定し、冒頭で整合を検証する。

再現性確認のため 前半(〜2025/08) / 後半(2025/09〜) に分けて両方で出す。片方だけ高いものは偶然扱い。
使い方: python3 analyze/market_bias.py
"""
import glob, json, re, sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from verify.bet_analysis2 import parse_amounts, parse_horse_nums  # noqa: E402

SPLIT = pd.Timestamp(2025, 9, 1)


def jp_date(s):
    m = re.match(r"(\d+)年(\d+)月(\d+)日", s)
    return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def all_splits(s, count):
    out = []

    def rec(i, acc):
        if len(acc) > count:
            return
        if i == len(s):
            if len(acc) == count:
                out.append(tuple(acc))
            return
        for w in (1, 2):
            if i + w <= len(s) and not (w == 2 and s[i] == "0") and 1 <= int(s[i:i + w]) <= 18:
                rec(i + w, acc + [int(s[i:i + w])])

    rec(0, [])
    return out


def load():
    races, stats = [], defaultdict(int)
    for p in glob.glob(str(BASE / "cache" / "race_result" / "*.json")):
        d = json.load(open(p))
        rid = d.get("race_id") or Path(p).stem
        pp = BASE / "cache" / "payouts" / f"{rid}.json"
        if not pp.exists() or "障害" in (d.get("race_name", "") + d.get("conditions", "") + d.get("surface", "")):
            stats["払戻なし/障害"] += 1
            continue
        pay = json.load(open(pp))
        ents = [e for e in d["entries"] if isinstance(e.get("rank"), int) and e["rank"] > 0
                and e.get("odds") and e.get("popularity")]
        if len(ents) < 5:
            stats["頭数不足"] += 1
            continue
        ents.sort(key=lambda e: e["rank"])
        ranks = [e["rank"] for e in ents[:4]]
        if ranks[:3] != [1, 2, 3]:
            stats["同着(上位3)"] += 1
            continue
        amt = {}
        for k in ("複勝", "馬連", "ワイド", "3連複", "馬単", "3連単"):
            raw = pay.get(k, {}).get("raw", [])
            amt[k] = parse_amounts(raw[2]) if len(raw) >= 3 and raw[2] else []
        n = len(d["entries"])
        n_place = 3 if n >= 8 else 2
        if len(amt["複勝"]) != n_place or len(amt["馬連"]) != 1 or len(amt["3連複"]) != 1 or len(amt["ワイド"]) != 3:
            stats["払戻件数不整合"] += 1
            continue

        # 並び仮定の検証 + 既存パーサの誤読率
        top3 = [int(e["horse_num"]) for e in ents[:3]]
        raw_f = pay["複勝"]["raw"][1]
        stats["複勝並びOK"] += tuple(top3[:n_place]) in all_splits(raw_f, n_place)
        raw_w = pay["ワイド"]["raw"][1]
        exp = (top3[0], top3[1], top3[0], top3[2], top3[1], top3[2])
        stats["ワイド並びOK"] += any(
            all(set(c[i:i + 2]) == set(exp[i:i + 2]) for i in (0, 2, 4)) for c in all_splits(raw_w, 6))
        raw_t = pay["3連複"]["raw"][1]
        parsed = parse_horse_nums(raw_t, count=3, group=3)
        stats["3連複パーサ一致"] += set(parsed) == set(top3)
        stats["検証母数"] += 1

        races.append({
            "rid": rid, "dt": jp_date(d["date"]), "cls": d.get("race_class"), "surface": d.get("surface"),
            "n": n, "pop": [e["popularity"] for e in ents], "odds": [e["odds"] for e in ents],
            "pop_by_rank": [e["popularity"] for e in ents[:3]], "amt": amt,
        })
    print("読込:", len(races), "R  除外:", {k: v for k, v in stats.items() if "OK" not in k and "一致" not in k and k != "検証母数"})
    m = stats["検証母数"]
    print(f"並び仮定の整合: 複勝 {stats['複勝並びOK'] / m:.2%} / ワイド {stats['ワイド並びOK'] / m:.2%}"
          f"   既存パーサ(3連複)が着順と一致: {stats['3連複パーサ一致'] / m:.2%}（不一致 {m - stats['3連複パーサ一致']}件）")
    return races


def halves(rows):
    """rows: list of (dt, 投資, 払戻, 的中) → 全体/前半/後半の (件数, 的中率, ROI)"""
    out = []
    for sel in (lambda t: True, lambda t: t < SPLIT, lambda t: t >= SPLIT):
        r = [x for x in rows if sel(x[0])]
        inv = sum(x[1] for x in r)
        out.append((len(r), sum(x[3] for x in r) / max(len(r), 1), sum(x[2] for x in r) / max(inv, 1)))
    return out


def fmt(label, rows, ex_top=True):
    a, h1, h2 = halves(rows)
    s = f"{label:<22} n={a[0]:>5} 的中{a[1]:>6.1%} ROI{a[2]:>5.0%} | 前半{h1[2]:>5.0%} 後半{h2[2]:>5.0%}"
    if ex_top and rows:
        pays = sorted((x[2] for x in rows), reverse=True)
        inv = sum(x[1] for x in rows)
        s += f" | 上位3除外{(sum(pays) - sum(pays[:3])) / inv:>5.0%}"
    return s


def main():
    races = load()
    print(f"期間: {min(r['dt'] for r in races).date()}〜{max(r['dt'] for r in races).date()}  分割点 {SPLIT.date()}")

    # 1. 単勝: オッズ帯別
    print("\n== 単勝 オッズ帯別（全頭を買った場合）==")
    bins = [1, 1.5, 2, 3, 5, 7, 10, 15, 20, 30, 50, 100, 1000]
    rows = defaultdict(list)
    for r in races:
        for i, (o, p) in enumerate(zip(r["odds"], r["pop"])):
            b = np.searchsorted(bins, o, side="right") - 1
            rows[b].append((r["dt"], 100, o * 100 if i == 0 else 0, i == 0))
    for b in sorted(rows):
        print(fmt(f"{bins[b]}〜{bins[min(b + 1, len(bins) - 1)]}倍", rows[b], ex_top=False))

    # 2. 単勝・複勝: 人気別
    print("\n== 単勝 / 複勝 人気別 ==")
    for k in range(1, 9):
        tan, fuku = [], []
        for r in races:
            for i, p in enumerate(r["pop"]):
                if p != k:
                    continue
                tan.append((r["dt"], 100, r["odds"][i] * 100 if i == 0 else 0, i == 0))
                hit = i < len(r["amt"]["複勝"])
                fuku.append((r["dt"], 100, r["amt"]["複勝"][i] if hit else 0, hit))
        print(fmt(f"単勝 {k}番人気", tan, False))
        print(fmt(f"複勝 {k}番人気", fuku, False))

    # 3. 馬連・ワイド: 人気ペア
    print("\n== 馬連 / ワイド 人気ペア別（1〜7番人気）==")
    pair_rows = {"馬連": defaultdict(list), "ワイド": defaultdict(list)}
    for r in races:
        pr = r["pop_by_rank"]
        win_pairs = {frozenset((pr[0], pr[1])): r["amt"]["ワイド"][0], frozenset((pr[0], pr[2])): r["amt"]["ワイド"][1],
                     frozenset((pr[1], pr[2])): r["amt"]["ワイド"][2]}
        for a, b in combinations(range(1, 8), 2):
            if max(a, b) > r["n"]:
                continue
            key = frozenset((a, b))
            hit_u = key == frozenset((pr[0], pr[1]))
            pair_rows["馬連"][(a, b)].append((r["dt"], 100, r["amt"]["馬連"][0] if hit_u else 0, hit_u))
            pair_rows["ワイド"][(a, b)].append((r["dt"], 100, win_pairs.get(key, 0), key in win_pairs))
    for bt in ("馬連", "ワイド"):
        res = sorted(pair_rows[bt].items(), key=lambda kv: -halves(kv[1])[0][2])
        for (a, b), rows_ in res[:8]:
            print(fmt(f"{bt} {a}-{b}番人気", rows_))
        print("   …下位:", ", ".join(f"{a}-{b}:{halves(v)[0][2]:.0%}" for (a, b), v in res[-4:]))

    # 4. 三連複: 人気トリプル（1〜7番人気）
    print("\n== 三連複 人気トリプル別（1〜7番人気・ROI上位10と定番）==")
    tri = defaultdict(list)
    for r in races:
        win = frozenset(r["pop_by_rank"])
        for c in combinations(range(1, 8), 3):
            if max(c) > r["n"]:
                continue
            hit = frozenset(c) == win
            tri[c].append((r["dt"], 100, r["amt"]["3連複"][0] if hit else 0, hit))
    res = sorted(tri.items(), key=lambda kv: -halves(kv[1])[0][2])
    for c, rows_ in res[:10]:
        print(fmt("三連複 " + "-".join(map(str, c)), rows_))
    all_roi = [halves(v)[0][2] for v in tri.values()]
    print(f"   35パターンのROI: 平均{np.mean(all_roi):.0%} 最小{min(all_roi):.0%} 最大{max(all_roi):.0%}"
          f" / 前半・後半とも100%超のパターン数: {sum(1 for v in tri.values() if halves(v)[1][2] > 1 and halves(v)[2][2] > 1)}")

    # 5. フォーメーション（人気順）
    print("\n== 人気順フォーメーション ==")
    forms = {
        "三連複 1人気軸-2〜6人気(10点)": lambda: [(1,) + c for c in combinations(range(2, 7), 2)],
        "三連複 1-5人気BOX(10点)": lambda: list(combinations(range(1, 6), 3)),
        "三連複 2人気軸-1,3〜6人気(10点)": lambda: [tuple(sorted((2,) + c)) for c in combinations([1, 3, 4, 5, 6], 2)],
        "三連複 3-7人気BOX(10点)": lambda: list(combinations(range(3, 8), 3)),
        "三連複 4-9人気BOX(20点)": lambda: list(combinations(range(4, 10), 3)),
    }
    for name, f in forms.items():
        combos = [frozenset(c) for c in f()]
        rows_ = []
        for r in races:
            cs = [c for c in combos if max(c) <= r["n"]]
            if not cs:
                continue
            hit = frozenset(r["pop_by_rank"]) in cs
            rows_.append((r["dt"], 100 * len(cs), r["amt"]["3連複"][0] if hit else 0, hit))
        print(fmt(name, rows_))

    # 6. 条件別: 1番人気の単複
    print("\n== 条件別: 1番人気 単勝/複勝 ROI ==")
    def cond_rows(sel):
        tan, fuku = [], []
        for r in races:
            if not sel(r) or 1 not in r["pop"]:
                continue
            i = r["pop"].index(1)
            tan.append((r["dt"], 100, r["odds"][i] * 100 if i == 0 else 0, i == 0))
            hit = i < len(r["amt"]["複勝"])
            fuku.append((r["dt"], 100, r["amt"]["複勝"][i] if hit else 0, hit))
        return tan, fuku
    conds = {f"クラス={c}": (lambda r, c=c: r["cls"] == c) for c in ["新馬", "未勝利", "1勝クラス", "2勝クラス", "3勝クラス", "OP", "重賞"]}
    conds.update({"芝": lambda r: r["surface"] == "芝", "ダ": lambda r: r["surface"] != "芝",
                  "〜10頭": lambda r: r["n"] <= 10, "11〜15頭": lambda r: 11 <= r["n"] <= 15, "16頭〜": lambda r: r["n"] >= 16,
                  "1人気オッズ<2.0": lambda r: r["odds"][r["pop"].index(1)] < 2.0 if 1 in r["pop"] else False,
                  "1人気オッズ≥3.5": lambda r: r["odds"][r["pop"].index(1)] >= 3.5 if 1 in r["pop"] else False})
    for name, sel in conds.items():
        tan, fuku = cond_rows(sel)
        print(fmt(f"単 {name}", tan, False))
        print(fmt(f"複 {name}", fuku, False))


if __name__ == "__main__":
    main()
