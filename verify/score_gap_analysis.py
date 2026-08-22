"""
予想1位・2位のスコア差と予想1位が1着になる率の関係を分析
cache/race_result/ 全JSONを使用（外部アクセスなし）

使い方:
  python3 verify/score_gap_analysis.py
  python3 verify/score_gap_analysis.py --surface 芝
  python3 verify/score_gap_analysis.py --surface ダ
"""
import sys, re, json, argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from jra_scraper import HorseEntry, RaceInfo
from scorer_turf import score_all as score_turf
from scorer_dart import score_all as score_dart
from scorer_turf import parse_race_class
from cache_store import cache_get_before, cache_get

BASE = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE = BASE / 'cache' / 'race_result'

TARGET_CLASSES = {"2勝クラス", "3勝クラス", "OP", "重賞"}

# スコア差bin定義: (下限, 上限, ラベル)
BINS = [
    (0.0, 1.0,  "0〜1pt"),
    (1.0, 2.0,  "1〜2pt"),
    (2.0, 3.0,  "2〜3pt"),
    (3.0, 5.0,  "3〜5pt"),
    (5.0, 8.0,  "5〜8pt"),
    (8.0, 999.0,"8pt以上"),
]


def get_bin_label(gap: float) -> str:
    for lo, hi, label in BINS:
        if lo <= gap < hi:
            return label
    return "8pt以上"


def process_race(data: dict) -> dict | None:
    """1レースを採点し、分析用データを返す"""
    rc = data.get("race_class", "")
    if rc not in TARGET_CLASSES:
        return None
    surface = data.get("surface", "")
    if surface not in ("芝", "ダ"):
        return None

    entries_raw = data.get("entries", [])
    if len(entries_raw) <= 2:
        return None

    date_str = data.get("date", "")
    dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not dm:
        return None
    cutoff = f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}"

    race_info = RaceInfo(
        name=data["race_name"],
        date=date_str,
        venue=data["venue"],
        race_number=f"{data.get('race_num_int', 0)}R",
        distance=data["distance"],
        surface=surface,
        conditions=data.get("conditions", ""),
        start_time=data.get("start_time", ""),
        url="",
        race_num=data.get("race_num_int", 0),
        track_condition=data.get("track_condition", ""),
    )

    entries = []
    rank_map = {}
    horse_ids = {}

    for e in entries_raw:
        hid = e.get("horse_id", "")
        recent = cache_get_before("horse_history", hid, cutoff) or [] if hid else []
        sire = cache_get("sire", hid) or "" if hid else ""
        he = HorseEntry(
            frame_number=e.get("frame", ""),
            horse_number=e.get("horse_num", ""),
            horse_name=e["horse_name"],
            record="", prize_money="", owner="", trainer="",
            age_sex=e.get("age_sex", ""),
            weight_carried=e.get("weight_carried", ""),
            jockey=e.get("jockey", ""),
            recent_races=recent,
            sire=sire,
        )
        entries.append(he)
        rank_map[e["horse_name"]] = e.get("rank", 99)
        if hid:
            horse_ids[e["horse_name"]] = hid

    if len(entries) <= 2:
        return None

    try:
        fn = score_dart if surface == "ダ" else score_turf
        tc = data.get("track_condition", "")
        scored = fn(entries, race_info, track_condition=tc, horse_ids=horse_ids)
        scored.sort(key=lambda x: x[1].total, reverse=True)
    except Exception as ex:
        return {"error": str(ex)}

    if len(scored) < 2:
        return None

    top1_entry, top1_bd = scored[0]
    top2_entry, top2_bd = scored[1]
    gap = top1_bd.total - top2_bd.total

    top1_horse_num = top1_entry.horse_number
    # 実際の1着・2着の馬番を取得
    actual_rank1_num = None
    actual_rank2_num = None
    for e in entries_raw:
        if e.get("rank") == 1:
            actual_rank1_num = str(e["horse_num"])
        if e.get("rank") == 2:
            actual_rank2_num = str(e["horse_num"])

    top1_wins    = str(top1_horse_num) == str(actual_rank1_num)
    top1_place   = str(top1_horse_num) in (str(actual_rank1_num), str(actual_rank2_num))

    return {
        "race_id": data.get("race_id", ""),
        "race_name": data["race_name"],
        "race_class": rc,
        "surface": surface,
        "gap": gap,
        "top1_score": top1_bd.total,
        "top2_score": top2_bd.total,
        "top1_horse_num": top1_horse_num,
        "actual_rank1_num": actual_rank1_num,
        "top1_wins": top1_wins,
        "top1_place": top1_place,
        "n_entries": len(entries),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", choices=["芝", "ダ"], default=None,
                        help="絞り込む馬場（省略時は両方）")
    args = parser.parse_args()

    files = sorted(CACHE_RACE.glob("*.json"))
    total = len(files)
    print(f"キャッシュファイル数: {total}")

    results = []
    skipped = 0
    error_count = 0

    for i, fp in enumerate(files):
        if i % 200 == 0:
            print(f"  {i}/{total} 処理中...", flush=True)
        try:
            data = json.loads(fp.read_text())
        except Exception:
            skipped += 1
            continue

        if args.surface and data.get("surface") != args.surface:
            continue

        ret = process_race(data)
        if ret is None:
            skipped += 1
        elif "error" in ret:
            error_count += 1
        else:
            results.append(ret)

    print(f"\n有効レース数: {len(results)}  スキップ: {skipped}  エラー: {error_count}\n")

    # ── bin別集計 ────────────────────────────────────────────
    bin_stats = {label: {"count": 0, "wins": 0, "place": 0}
                 for _, _, label in BINS}

    for r in results:
        label = get_bin_label(r["gap"])
        bin_stats[label]["count"] += 1
        if r["top1_wins"]:
            bin_stats[label]["wins"] += 1
        if r["top1_place"]:
            bin_stats[label]["place"] += 1

    # ── 出力 ─────────────────────────────────────────────────
    surface_label = args.surface if args.surface else "芝+ダ"
    print(f"=== スコア差 vs 予想1位精度  [{surface_label}  2勝クラス以上] ===")
    print(f"{'スコア差bin':<12}  {'レース数':>8}  {'1位→1着率':>10}  {'1位→2着内率':>12}")
    print("-" * 52)

    total_races = 0
    total_wins  = 0
    total_place = 0

    for _, _, label in BINS:
        s = bin_stats[label]
        n = s["count"]
        if n == 0:
            print(f"{label:<12}  {'0':>8}  {'—':>10}  {'—':>12}")
            continue
        win_pct   = 100 * s["wins"]  / n
        place_pct = 100 * s["place"] / n
        print(f"{label:<12}  {n:>8}  {win_pct:>9.1f}%  {place_pct:>11.1f}%")
        total_races += n
        total_wins  += s["wins"]
        total_place += s["place"]

    print("-" * 52)
    if total_races > 0:
        print(f"{'全体':.<12}  {total_races:>8}  "
              f"{100*total_wins/total_races:>9.1f}%  "
              f"{100*total_place/total_races:>11.1f}%")

    # ── クラス別サブ集計 ──────────────────────────────────────
    print(f"\n=== クラス別 全体精度 ===")
    class_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "wins": 0, "place": 0})
    for r in results:
        cs = class_stats[r["race_class"]]
        cs["count"] += 1
        if r["top1_wins"]:  cs["wins"]  += 1
        if r["top1_place"]: cs["place"] += 1

    print(f"{'クラス':<12}  {'レース数':>8}  {'1位→1着率':>10}  {'1位→2着内率':>12}")
    print("-" * 52)
    for cls in ["2勝クラス", "3勝クラス", "OP", "重賞"]:
        s = class_stats.get(cls, {"count": 0, "wins": 0, "place": 0})
        n = s["count"]
        if n == 0:
            print(f"{cls:<12}  {'0':>8}  {'—':>10}  {'—':>12}")
            continue
        print(f"{cls:<12}  {n:>8}  {100*s['wins']/n:>9.1f}%  {100*s['place']/n:>11.1f}%")

    # ── 芝/ダート別サブ集計 ───────────────────────────────────
    print(f"\n=== 芝/ダート別 スコア差 vs 精度 ===")
    for surf in ["芝", "ダ"]:
        surf_results = [r for r in results if r["surface"] == surf]
        surf_bin_stats = {label: {"count": 0, "wins": 0, "place": 0}
                          for _, _, label in BINS}
        for r in surf_results:
            label = get_bin_label(r["gap"])
            surf_bin_stats[label]["count"] += 1
            if r["top1_wins"]:  surf_bin_stats[label]["wins"]  += 1
            if r["top1_place"]: surf_bin_stats[label]["place"] += 1

        surf_total = len(surf_results)
        surf_wins  = sum(1 for r in surf_results if r["top1_wins"])
        surf_place = sum(1 for r in surf_results if r["top1_place"])

        print(f"\n[{surf}  {surf_total}レース  全体1着率:{100*surf_wins/surf_total:.1f}%  2着内:{100*surf_place/surf_total:.1f}%]" if surf_total else f"\n[{surf} 0レース]")
        if surf_total == 0:
            continue
        print(f"{'スコア差bin':<12}  {'レース数':>8}  {'1位→1着率':>10}  {'1位→2着内率':>12}")
        print("-" * 52)
        for _, _, label in BINS:
            s = surf_bin_stats[label]
            n = s["count"]
            if n == 0:
                continue
            print(f"{label:<12}  {n:>8}  {100*s['wins']/n:>9.1f}%  {100*s['place']/n:>11.1f}%")

    # ── CSV出力 ───────────────────────────────────────────────
    import csv
    out_path = BASE / "data" / "score_gap_analysis.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = ["スコア差bin", "レース数", "1位→1着率(%)", "1位→2着内率(%)"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for _, _, label in BINS:
            s = bin_stats[label]
            n = s["count"]
            if n == 0:
                writer.writerow({"スコア差bin": label, "レース数": 0,
                                  "1位→1着率(%)": "", "1位→2着内率(%)": ""})
            else:
                writer.writerow({
                    "スコア差bin": label,
                    "レース数": n,
                    "1位→1着率(%)": round(100*s["wins"]/n, 1),
                    "1位→2着内率(%)": round(100*s["place"]/n, 1),
                })
    print(f"\n→ CSV保存: {out_path}")


if __name__ == "__main__":
    main()
