"""
keiba-feature-gate 標準馬券指標の算出・出力。

毎回の検証で以下を総合・クラス別に的中率とROIを出す:
  単勝 / 複勝
  馬連: ランク1-2(1点) / 上位3頭3点 / 5頭BOX(10点)
  三連複: 1-2-3(1点) / 1軸4頭(6点) / 5頭BOX(10点) / 6頭BOX(20点)

使い方:
  python3 verify/bet_metrics_standard.py
  python3 verify/bet_metrics_standard.py --csv data/検証_新ロジック_調教あり.csv
  python3 verify/bet_metrics_standard.py --surface 芝
"""
import sys
import argparse
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verify.bet_analysis2 import load_races, get_payout, parse_horse_nums, parse_amounts  # noqa: E402

CLASSES = ["2勝クラス", "3勝クラス", "OP", "重賞"]

BET_SPECS = [
    ("単勝",           "tan"),
    ("複勝",           "fuku"),
    ("馬連1-2",        "baren12"),
    ("馬連3点",        "baren3"),
    ("ワイド1-2",      "wide12"),
    ("ワイド3点",      "wide3"),
    ("三連複1-2-3",    "trio123"),
    ("三連複1軸4頭",   "trio_axis4"),
    ("三連複5頭BOX",   "trio5box"),
]


def _baren_pairs(hnums, amounts):
    pairs = [(hnums[i * 2], hnums[i * 2 + 1]) for i in range(len(amounts))
             if i * 2 + 1 < len(hnums)]
    return {frozenset([a, b]): amounts[j] for j, (a, b) in enumerate(pairs) if j < len(amounts)}


def sim_bet(races, kind: str) -> dict:
    invest = collect = hits = 0
    valid = 0

    for r in races:
        race_id = r.get("race_id", "")
        p = [r.get(f"p{i}_num") for i in range(1, 7)]
        acts = [r.get(f"p{i}_act", 99) for i in range(1, 7)]
        top5 = r.get("top5_nums") or []
        top6 = (top5 + [p[5]]) if len(top5) >= 5 and p[5] else top5
        if len(top6) < 6 and p[5]:
            top6 = list(dict.fromkeys(top5 + [p[5]]))
        n_horses = r.get("n_horses", 0)

        if kind == "tan":
            valid += 1
            invest += 100
            if acts[0] == 1:
                hits += 1
                collect += r["top1_odds"] * 100
            continue

        if kind == "fuku":
            valid += 1
            invest += 100
            if not race_id or acts[0] > 3:
                continue
            hnums, amounts = get_payout(race_id, "複勝")
            if not hnums or not amounts:
                continue
            try:
                idx = hnums.index(p[0])
                if idx < len(amounts):
                    hits += 1
                    collect += amounts[idx]
            except ValueError:
                pass
            continue

        if kind == "baren12":
            valid += 1
            invest += 100
            if not race_id or p[0] is None or p[1] is None:
                continue
            hnums, amounts = get_payout(race_id, "馬連")
            if not hnums or not amounts:
                continue
            bet = frozenset([p[0], p[1]])
            payout_map = _baren_pairs(hnums, amounts)
            if bet in payout_map:
                hits += 1
                collect += payout_map[bet]
            continue

        if kind == "baren3":
            valid += 1
            invest += 300
            if not race_id:
                continue
            hnums, amounts = get_payout(race_id, "馬連")
            if not hnums or not amounts:
                continue
            payout_map = _baren_pairs(hnums, amounts)
            race_hit = False
            for a, b in [(p[0], p[1]), (p[0], p[2]), (p[1], p[2])]:
                if a and b and frozenset([a, b]) in payout_map:
                    race_hit = True
                    collect += payout_map[frozenset([a, b])]
            if race_hit:
                hits += 1
            continue

        if kind == "baren5box":
            valid += 1
            invest += 1000
            if not race_id or len(top5) < 2:
                continue
            hnums, amounts = get_payout(race_id, "馬連")
            if not hnums or not amounts:
                continue
            payout_map = _baren_pairs(hnums, amounts)
            race_hit = False
            for a, b in combinations(top5, 2):
                bet = frozenset([a, b])
                if bet in payout_map:
                    race_hit = True
                    collect += payout_map[bet]
            if race_hit:
                hits += 1
            continue

        if kind == "wide12":
            valid += 1
            invest += 100
            if not race_id or p[0] is None or p[1] is None:
                continue
            hnums, amounts = get_payout(race_id, "ワイド")
            if not hnums or not amounts:
                continue
            pairs = [(hnums[i*2], hnums[i*2+1]) for i in range(len(amounts)) if i*2+1 < len(hnums)]
            bet = frozenset([p[0], p[1]])
            for j, (a, b) in enumerate(pairs):
                if bet == frozenset([a, b]) and j < len(amounts):
                    hits += 1
                    collect += amounts[j]
                    break
            continue

        if kind == "wide3":
            valid += 1
            invest += 300
            if not race_id:
                continue
            hnums, amounts = get_payout(race_id, "ワイド")
            if not hnums or not amounts:
                continue
            pairs = [(hnums[i*2], hnums[i*2+1]) for i in range(len(amounts)) if i*2+1 < len(hnums)]
            payout_map = {frozenset([a, b]): amounts[j] for j, (a, b) in enumerate(pairs) if j < len(amounts)}
            race_hit = False
            for a, b in [(p[0], p[1]), (p[0], p[2]), (p[1], p[2])]:
                if a and b and frozenset([a, b]) in payout_map:
                    race_hit = True
                    collect += payout_map[frozenset([a, b])]
            if race_hit:
                hits += 1
            continue

        if kind in ("trio123", "trio_axis4", "trio5box"):
            if not race_id:
                continue
            hnums, amounts = get_payout(race_id, "3連複")
            if not hnums or not amounts:
                continue
            winning = frozenset(hnums[:3])
            pay = amounts[0]

            if kind == "trio123":
                if p[0] is None or p[1] is None or p[2] is None:
                    continue
                valid += 1
                invest += 100
                if winning == frozenset([p[0], p[1], p[2]]):
                    hits += 1
                    collect += pay
                continue

            if kind == "trio_axis4":
                if p[0] is None:
                    continue
                aite = [x for x in p[1:5] if x]
                if len(aite) < 2:
                    continue
                pts = len(aite) * (len(aite) - 1) // 2
                valid += 1
                invest += pts * 100
                combos = {frozenset([p[0], a, b]) for a, b in combinations(aite, 2)}
                if winning in combos:
                    hits += 1
                    collect += pay
                continue

            if kind == "trio5box":
                if len(top5) < 3:
                    continue
                valid += 1
                invest += 1000
                if winning.issubset(set(top5)):
                    hits += 1
                    collect += pay
                continue

            if kind == "trio6box":
                nums6 = list(dict.fromkeys([x for x in (top5 + [p[5]]) if x]))[:6]
                if len(nums6) < 3:
                    continue
                pts = len(nums6) * (len(nums6) - 1) * (len(nums6) - 2) // 6
                valid += 1
                invest += pts * 100
                if winning.issubset(set(nums6)):
                    hits += 1
                    collect += pay
                continue

    n = valid
    roi = collect / invest * 100 if invest > 0 else 0.0
    hit_rate = hits / n * 100 if n > 0 else 0.0
    return {"n": n, "hits": hits, "hit_rate": hit_rate, "invest": invest, "collect": collect, "roi": roi}


def print_metrics_table(label: str, races: list, prefix: str = ""):
    if not races:
        print(f"{prefix}【{label}】 データなし")
        return
    print(f"{prefix}【{label}】 n={len(races)}レース")
    print(f"{prefix}{'馬券種別':<16} {'点数/R':>6} {'的中率':>8} {'ROI':>8} {'投資':>10} {'回収':>10}")
    print(f"{prefix}{'-' * 62}")
    pts_map = {
        "単勝": "1", "複勝": "1", "馬連1-2": "1", "馬連3点": "3",
        "ワイド1-2": "1", "ワイド3点": "3",
        "三連複1-2-3": "1", "三連複1軸4頭": "6", "三連複5頭BOX": "10",
    }
    for name, kind in BET_SPECS:
        m = sim_bet(races, kind)
        print(
            f"{prefix}{name:<16} {pts_map[name]:>6} "
            f"{m['hit_rate']:>7.1f}% {m['roi']:>7.1f}% "
            f"{m['invest']:>9,} {m['collect']:>9,.0f}"
        )
    print()


def run_report(races: list, title: str = "検証結果"):
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}")
    print_metrics_table("総合", races)
    print("  ── クラス別 ──")
    for cls in CLASSES:
        subset = [r for r in races if r.get("class") == cls]
        if subset:
            print_metrics_table(cls, subset, prefix="  ")


def main():
    parser = argparse.ArgumentParser(description="keiba-feature-gate 標準馬券指標")
    parser.add_argument("--csv", default="", help="採点済みCSV（未指定時は bet_analysis2 既定パス）")
    parser.add_argument("--surface", choices=["芝", "ダ"], default="", help="芝/ダート絞り込み")
    parser.add_argument("--label", default="検証結果", help="レポートタイトル")
    args = parser.parse_args()

    if args.csv:
        import verify.bet_analysis2 as ba2
        ba2.CSV_PATH = Path(args.csv)

    races = load_races(surface_filter=args.surface or None)
    surf = f" [{args.surface}]" if args.surface else ""
    run_report(races, title=f"{args.label}{surf}")


if __name__ == "__main__":
    main()
