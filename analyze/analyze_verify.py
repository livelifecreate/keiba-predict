"""
verify_batch_result.csv（全頭ロング形式）を集計して
予想順位別の的中率を表示する。

使い方:
  python3 analyze_verify.py
  python3 analyze_verify.py --csv verify_batch_result.csv
  python3 analyze_verify.py --top 5   # 予想上位5位まで表示
"""

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv
from collections import defaultdict
from pathlib import Path

CSV_PATH = Path(__file__).parent / "verify_batch_result.csv"

def load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def to_int(v, default=99):
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _section(title: str):
    print()
    print("=" * 60)
    print(f"■ {title}")
    print("=" * 60)


def _print_rank_table(rows: list[dict], top_n: int):
    by_rank = defaultdict(list)
    for r in rows:
        pred = to_int(r["予想順位"])
        actual = to_int(r["実着順"])
        by_rank[pred].append(actual)

    print(f"  {'予想順位':>6}  {'出現':>4}  {'1着':>8}  {'2着':>8}  {'3着':>8}  {'連対(1+2)':>10}  {'4着以下':>8}")
    for rank in range(1, top_n + 1):
        actuals = by_rank.get(rank, [])
        if not actuals:
            continue
        n = len(actuals)
        c1 = sum(1 for a in actuals if a == 1)
        c2 = sum(1 for a in actuals if a == 2)
        c3 = sum(1 for a in actuals if a == 3)
        c4 = n - c1 - c2 - c3
        rentan = c1 + c2
        print(f"  予想{rank:2d}位  {n:4d}頭  "
              f"{c1:3d}({c1/n*100:4.1f}%)  "
              f"{c2:3d}({c2/n*100:4.1f}%)  "
              f"{c3:3d}({c3/n*100:4.1f}%)  "
              f"{rentan:3d}({rentan/n*100:4.1f}%)  "
              f"{c4:3d}({c4/n*100:4.1f}%)")


ODDS_BANDS = [
    (0,    2.0,  "〜2.0倍"),
    (2.0,  4.0,  "2〜4倍"),
    (4.0,  8.0,  "4〜8倍"),
    (8.0,  15.0, "8〜15倍"),
    (15.0, 30.0, "15〜30倍"),
    (30.0, 9999, "30倍〜"),
]

def _odds_band(odds) -> str:
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    for lo, hi, label in ODDS_BANDS:
        if lo <= o < hi:
            return label
    return "30倍〜"

def _print_odds_table(rows: list[dict]):
    band_data = defaultdict(list)
    for r in rows:
        band = _odds_band(r.get("単勝オッズ"))
        if band:
            band_data[band].append(to_int(r["実着順"]))

    print(f"  {'オッズ帯':10s}  {'出現':>5}  {'1着':>8}  {'2着':>8}  {'3着':>8}  {'連対':>8}  {'4着以下':>8}")
    for _, _, label in ODDS_BANDS:
        actuals = band_data.get(label, [])
        if not actuals:
            continue
        n = len(actuals)
        c1 = sum(1 for a in actuals if a == 1)
        c2 = sum(1 for a in actuals if a == 2)
        c3 = sum(1 for a in actuals if a == 3)
        rentan = c1 + c2
        c4 = n - c1 - c2 - c3
        print(f"  {label:10s}  {n:5d}頭  "
              f"{c1:3d}({c1/n*100:4.1f}%)  "
              f"{c2:3d}({c2/n*100:4.1f}%)  "
              f"{c3:3d}({c3/n*100:4.1f}%)  "
              f"{rentan:3d}({rentan/n*100:4.1f}%)  "
              f"{c4:3d}({c4/n*100:4.1f}%)")


def _print_umaren_table(rows: list[dict]):
    races = defaultdict(dict)
    for r in rows:
        key = (r["日付"], r["レース名"])
        pred = to_int(r["予想順位"])
        actual = to_int(r["実着順"])
        races[key][pred] = actual

    total = len(races)
    if total == 0:
        return
    print(f"  {'上位N頭':>8}  {'馬連的中':>14}  {'3連複的中':>14}")
    for n in range(2, 9):
        umaren = 0
        sanfuku = 0
        for race_preds in races.values():
            top_actuals = {race_preds[p] for p in range(1, n + 1) if p in race_preds}
            if 1 in top_actuals and 2 in top_actuals:
                umaren += 1
            if 1 in top_actuals and 2 in top_actuals and 3 in top_actuals:
                sanfuku += 1
        umaren_s  = f"{umaren:3d}/{total}({umaren/total*100:4.1f}%)"
        sanfuku_s = f"{sanfuku:3d}/{total}({sanfuku/total*100:4.1f}%)" if n >= 3 else "     -"
        print(f"  上位{n}頭     {umaren_s}      {sanfuku_s}")


def _print_winner_dist(rows: list[dict], top_n: int):
    winners = [r for r in rows if to_int(r["実着順"]) == 1]
    if not winners:
        return
    rank_dist = defaultdict(int)
    for w in winners:
        rank_dist[to_int(w["予想順位"])] += 1
    total_races = len(winners)
    cumsum = 0
    for rank in sorted(rank_dist):
        if rank > top_n * 2:
            break
        cnt = rank_dist[rank]
        cumsum += cnt
        print(f"  予想{rank:2d}位が1着: {cnt:2d}レース  累計: {cumsum}/{total_races} ({cumsum/total_races*100:.0f}%)")
    rest = sum(v for k, v in rank_dist.items() if k > top_n * 2)
    if rest:
        print(f"  予想{top_n*2+1}位以下が1着: {rest}レース")


SYS_RANK_BANDS = [
    (1, 1, "システム1位"),
    (2, 2, "システム2位"),
    (3, 4, "システム3〜4位"),
    (5, 6, "システム5〜6位"),
    (7, 99,"システム7位以下"),
]

POP_BANDS = [
    (1, 1,  "1番人気"),
    (2, 3,  "2〜3番人気"),
    (4, 6,  "4〜6番人気"),
    (7, 99, "7番人気以下"),
]


def _print_fav_by_sys_rank(rows: list[dict]):
    races = defaultdict(dict)
    for r in rows:
        key = (r["日付"], r["レース名"])
        pop = to_int(r.get("市場人気", 99))
        if pop == 1:
            races[key]["sys_rank"] = to_int(r["予想順位"])
            races[key]["actual"]   = to_int(r["実着順"])

    by_band = defaultdict(list)
    for data in races.values():
        if "sys_rank" not in data:
            continue
        sr = data["sys_rank"]
        for lo, hi, label in SYS_RANK_BANDS:
            if lo <= sr <= hi:
                by_band[label].append(data["actual"])
                break

    if not any(by_band.values()):
        return
    print(f"  {'システム順位':12s}  {'レース':>5}  {'1着':>8}  {'連対(1+2)':>10}  {'複勝(3着内)':>12}  判定")
    for _, _, label in SYS_RANK_BANDS:
        actuals = by_band.get(label, [])
        if not actuals:
            continue
        n = len(actuals)
        c1  = sum(1 for a in actuals if a == 1)
        ren = sum(1 for a in actuals if a <= 2)
        fuku= sum(1 for a in actuals if a <= 3)
        judge = "◎ 軸有力" if ren/n >= 0.5 else "○ 軸候補" if ren/n >= 0.35 else "△ 要注意" if ren/n >= 0.2 else "× 疑わしい"
        print(f"  {label:12s}  {n:5d}  "
              f"{c1:3d}({c1/n*100:4.1f}%)  "
              f"{ren:3d}({ren/n*100:4.1f}%)    "
              f"{fuku:3d}({fuku/n*100:4.1f}%)    {judge}")


def _print_sys1_by_popularity(rows: list[dict]):
    races = defaultdict(dict)
    for r in rows:
        key = (r["日付"], r["レース名"])
        pred = to_int(r["予想順位"])
        if pred == 1:
            races[key]["popularity"] = to_int(r.get("市場人気", 99))
            races[key]["actual"]     = to_int(r["実着順"])

    by_band = defaultdict(list)
    for data in races.values():
        if "popularity" not in data:
            continue
        pop = data["popularity"]
        for lo, hi, label in POP_BANDS:
            if lo <= pop <= hi:
                by_band[label].append(data["actual"])
                break

    if not any(by_band.values()):
        return
    print(f"  {'市場人気':12s}  {'レース':>5}  {'1着':>8}  {'連対(1+2)':>10}  {'複勝(3着内)':>12}  判定")
    for _, _, label in POP_BANDS:
        actuals = by_band.get(label, [])
        if not actuals:
            continue
        n = len(actuals)
        c1  = sum(1 for a in actuals if a == 1)
        ren = sum(1 for a in actuals if a <= 2)
        fuku= sum(1 for a in actuals if a <= 3)
        judge = "◎ 信頼して軸" if ren/n >= 0.5 else "○ 軸候補" if ren/n >= 0.35 else "△ 流しで対応" if ren/n >= 0.2 else "× 荒れサイン"
        print(f"  {label:12s}  {n:5d}  "
              f"{c1:3d}({c1/n*100:4.1f}%)  "
              f"{ren:3d}({ren/n*100:4.1f}%)    "
              f"{fuku:3d}({fuku/n*100:4.1f}%)    {judge}")


def _by_class_header(cls: str, n_races: int):
    print(f"\n  【{cls}  {n_races}レース】")


def analyze(rows: list[dict], top_n: int = 5):
    classes = sorted({r["クラス"] for r in rows})
    n_races_total = len({(r["日付"], r["レース名"]) for r in rows})
    has_odds = any(r.get("単勝オッズ") for r in rows)
    has_pop  = any(r.get("市場人気")  for r in rows)

    print(f"対象レース数: {n_races_total}  クラス: {classes}")
    print()

    # ────────────────────────────────────────
    # 1. クラス別サマリー
    # ────────────────────────────────────────
    _section("クラス別サマリー（予想1位基準）")
    races_by_class = defaultdict(set)
    hits_by_class  = defaultdict(lambda: {"tan":0,"fuku":0,"umaren":0,"sanfuku":0})
    race_preds_all = defaultdict(dict)
    race_class_map = {}
    for r in rows:
        key = (r["日付"], r["レース名"])
        race_preds_all[key][to_int(r["予想順位"])] = to_int(r["実着順"])
        races_by_class[r["クラス"]].add(key)
        race_class_map[key] = r["クラス"]

    for key, preds in race_preds_all.items():
        cls = race_class_map[key]
        top1 = preds.get(1, 99)
        top2 = {preds.get(1,99), preds.get(2,99)}
        top3 = {preds.get(i,99) for i in range(1,4)}
        if top1 == 1: hits_by_class[cls]["tan"] += 1
        if top1 <= 3: hits_by_class[cls]["fuku"] += 1
        if 1 in top2 and 2 in top2: hits_by_class[cls]["umaren"] += 1
        if 1 in top3 and 2 in top3 and 3 in top3: hits_by_class[cls]["sanfuku"] += 1

    print(f"  {'クラス':8s}  {'レース':>5}  {'単勝':>8}  {'複勝':>8}  {'馬連':>8}  {'3連複':>8}")
    for cls in classes:
        n = len(races_by_class[cls])
        h = hits_by_class[cls]
        print(f"  {cls:8s}  {n:5d}  "
              f"{h['tan']:3d}({h['tan']/n*100:.0f}%)  "
              f"{h['fuku']:3d}({h['fuku']/n*100:.0f}%)  "
              f"{h['umaren']:3d}({h['umaren']/n*100:.0f}%)  "
              f"{h['sanfuku']:3d}({h['sanfuku']/n*100:.0f}%)")

    # ────────────────────────────────────────
    # 2. 予想順位別 着順分布（全体 + クラス別）
    # ────────────────────────────────────────
    _section("予想順位別 着順分布")
    print(f"  ── 全クラス（{n_races_total}レース）")
    _print_rank_table(rows, top_n)
    for cls in classes:
        cls_rows = [r for r in rows if r["クラス"] == cls]
        n_cls = len({(r["日付"], r["レース名"]) for r in cls_rows})
        _by_class_header(cls, n_cls)
        _print_rank_table(cls_rows, top_n)

    # ────────────────────────────────────────
    # 3. 単勝オッズ帯別 着順分布（全体 + クラス別）
    # ────────────────────────────────────────
    if has_odds:
        _section("単勝オッズ帯別 着順分布")
        print("  ── 全クラス")
        _print_odds_table(rows)
        for cls in classes:
            cls_rows = [r for r in rows if r["クラス"] == cls]
            n_cls = len({(r["日付"], r["レース名"]) for r in cls_rows})
            _by_class_header(cls, n_cls)
            _print_odds_table(cls_rows)

    # ────────────────────────────────────────
    # 4. N頭BOX 馬連・3連複的中率（全体 + クラス別）
    # ────────────────────────────────────────
    _section("予想上位N頭ボックス 馬連・3連複的中率")
    print("  ── 全クラス")
    _print_umaren_table(rows)
    for cls in classes:
        cls_rows = [r for r in rows if r["クラス"] == cls]
        n_cls = len({(r["日付"], r["レース名"]) for r in cls_rows})
        _by_class_header(cls, n_cls)
        _print_umaren_table(cls_rows)

    # ────────────────────────────────────────
    # 5. 実1着馬の予想順位分布（全体 + クラス別）
    # ────────────────────────────────────────
    _section("実1着馬の予想順位分布（勝者はシステムで何位に見えていたか）")
    print("  ── 全クラス")
    _print_winner_dist(rows, top_n)
    for cls in classes:
        cls_rows = [r for r in rows if r["クラス"] == cls]
        n_cls = len({(r["日付"], r["レース名"]) for r in cls_rows})
        _by_class_header(cls, n_cls)
        _print_winner_dist(cls_rows, top_n)

    # ────────────────────────────────────────
    # 6. 1番人気のシステム順位 → 連対率（全体 + クラス別）
    # ────────────────────────────────────────
    if has_pop:
        _section("1番人気馬のシステム順位 → 連対率")
        print("  ── 全クラス")
        _print_fav_by_sys_rank(rows)
        for cls in classes:
            cls_rows = [r for r in rows if r["クラス"] == cls]
            n_cls = len({(r["日付"], r["レース名"]) for r in cls_rows})
            _by_class_header(cls, n_cls)
            _print_fav_by_sys_rank(cls_rows)

        # ────────────────────────────────────────
        # 7. システム1位の市場人気 → 連対率（全体 + クラス別）
        # ────────────────────────────────────────
        _section("システム1位馬の市場人気 → 連対率")
        print("  ── 全クラス")
        _print_sys1_by_popularity(rows)
        for cls in classes:
            cls_rows = [r for r in rows if r["クラス"] == cls]
            n_cls = len({(r["日付"], r["レース名"]) for r in cls_rows})
            _by_class_header(cls, n_cls)
            _print_sys1_by_popularity(cls_rows)


def main():
    args = sys.argv[1:]

    path = CSV_PATH
    if "--csv" in args:
        path = Path(args[args.index("--csv") + 1])

    top_n = 5
    if "--top" in args:
        try:
            top_n = int(args[args.index("--top") + 1])
        except (ValueError, IndexError):
            pass

    filter_class = None
    if "--class" in args:
        filter_class = args[args.index("--class") + 1]

    if not path.exists():
        print(f"CSVが見つかりません: {path}")
        print("verify_batch.py を先に実行してください。")
        return

    rows = load(path)
    if filter_class:
        rows = [r for r in rows if r["クラス"] == filter_class]

    analyze(rows, top_n)


if __name__ == "__main__":
    main()
