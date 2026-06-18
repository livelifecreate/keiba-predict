"""
キャッシュ済み全レース（2勝クラス以上）を新ロジックで再採点してROI比較
cache/race_result/ の全JSONを使用
調教データ: netkeiba（cache/netkeiba_training/{race_id}.json）
"""
import sys, re, json, csv
sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from pathlib import Path
from collections import defaultdict
from jra_scraper import HorseEntry, RaceInfo
from scorer_turf import score_all as score_turf, SCORE_LABELS as LABELS_TURF
from scorer_dart import score_all as score_dart, SCORE_LABELS as LABELS_DART
from cache_store import cache_get, cache_get_before

BASE = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE = BASE / 'cache' / 'race_result'
NETKEIBA_TRAINING_DIR = BASE / 'cache' / 'netkeiba_training'

TARGET_CLASSES = {"2勝クラス", "3勝クラス", "OP", "重賞"}


# ---- 調教データ取得 -------------------------------------------------------

def _fetch_training_cached(race_id: str) -> dict | None:
    """netkeiba調教キャッシュから読み込む"""
    p = NETKEIBA_TRAINING_DIR / f"{race_id}.json"
    if not p.exists():
        return None
    try:
        from netkeiba_scraper import TrainingData as TD
        raw = json.loads(p.read_text())
        if not raw:
            return None
        return {name: TD(horse_name=name, rank=v["rank"], comment=v.get("comment", ""), score=v["score"])
                for name, v in raw.items()}
    except Exception:
        return None


# ---- レース採点 -----------------------------------------------------------

def process_race(data: dict, use_training: bool = True) -> list | None:
    if data.get("race_class") not in TARGET_CLASSES:
        return None
    if data.get("surface") not in ("芝", "ダ"):
        return None

    date_str = data["date"]
    dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not dm:
        return None
    cutoff = f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}"

    race_info = RaceInfo(
        name=data["race_name"], date=date_str, venue=data["venue"],
        race_number=f"{data['race_num_int']}R", distance=data["distance"],
        surface=data["surface"], conditions=data.get("conditions",""),
        start_time=data.get("start_time",""), url="", race_num=data["race_num_int"],
    )

    entries, rank_map, odds_map, pop_map = [], {}, {}, {}
    horse_ids = {}
    for e in data["entries"]:
        hid = e.get("horse_id","")
        recent = cache_get_before("horse_history", hid, cutoff) or []
        sire   = cache_get("sire", hid) or ""
        he = HorseEntry(
            frame_number=e["frame"], horse_number=e["horse_num"],
            horse_name=e["horse_name"], record="", prize_money="",
            owner="", trainer="", age_sex=e.get("age_sex",""),
            weight_carried=e.get("weight_carried",""), jockey=e.get("jockey",""),
            recent_races=recent, sire=sire,
        )
        entries.append(he)
        rank_map[e["horse_name"]] = e.get("rank", 99)
        odds_map[e["horse_name"]] = e.get("odds")
        pop_map[e["horse_name"]]  = e.get("popularity")
        if hid:
            horse_ids[e["horse_name"]] = hid

    if len(entries) < 5:
        return None

    training_data = None
    if use_training:
        training_data = _fetch_training_cached(data.get("race_id", ""))

    fn = score_dart if data["surface"] == "ダ" else score_turf
    tc = data.get("track_condition","")
    scored = fn(entries, race_info, training_data=training_data, track_condition=tc, horse_ids=horse_ids)
    scored.sort(key=lambda x: x[1].total, reverse=True)

    labels = LABELS_DART if data["surface"] == "ダ" else LABELS_TURF
    rows = []
    n = len(scored)
    for pred_rank, (entry, bd) in enumerate(scored, 1):
        row = {
            "日付": date_str, "競馬場": data["venue"],
            "レース名": data["race_name"], "クラス": data["race_class"],
            "コース": data["surface"], "距離": data["distance"], "出走頭数": n,
            "馬名": entry.horse_name, "馬番": entry.horse_number,
            "予想順位": pred_rank, "予想スコア": round(bd.total, 2),
            "単勝オッズ": odds_map.get(entry.horse_name),
            "市場人気": pop_map.get(entry.horse_name),
            "実着順": rank_map.get(entry.horse_name, 99),
            "調教あり": "○" if training_data and entry.horse_name in training_data else "",
        }
        for k, label in labels.items():
            row[label] = round(getattr(bd, k, 0.0), 1)
        rows.append(row)
    return rows


# ---- 統計計算 -------------------------------------------------------------

def calc_stats(rows_csv):
    races = defaultdict(list)
    for r in rows_csv:
        key = (r["日付"], r["レース名"])
        races[key].append(r)

    stats = {"races": 0, "tan": 0, "fuku": 0, "box5": 0, "box6": 0, "formb": 0, "cover_sum": 0}
    for key, horses in races.items():
        horses.sort(key=lambda x: x["予想順位"])
        actual_top3 = {h["馬名"] for h in horses if h["実着順"] <= 3}
        if len(actual_top3) < 3:
            continue

        top5_names = {h["馬名"] for h in horses[:5]}
        top6_names = {h["馬名"] for h in horses[:6]}
        top5_in = len(top5_names & actual_top3)
        top6_in = len(top6_names & actual_top3)
        pred1 = horses[0]["馬名"]
        top1_rank = horses[0]["実着順"]

        stats["races"] += 1
        stats["cover_sum"] += top5_in
        if top1_rank == 1: stats["tan"] += 1
        if top1_rank <= 3: stats["fuku"] += 1
        if top5_in == 3: stats["box5"] += 1
        if top6_in == 3: stats["box6"] += 1
        if pred1 in actual_top3 and top5_in >= 2: stats["formb"] += 1

    n = stats["races"]
    if n == 0:
        return stats
    avg = stats["cover_sum"] / n
    print(f"  レース数: {n}")
    print(f"  単勝命中(予想1位が1着): {stats['tan']}/{n} ({100*stats['tan']/n:.1f}%)")
    print(f"  複勝命中(予想1位が3着内): {stats['fuku']}/{n} ({100*stats['fuku']/n:.1f}%)")
    print(f"  三連複5頭BOX的中:    {stats['box5']}/{n} ({100*stats['box5']/n:.1f}%)")
    print(f"  三連複6頭BOX的中:    {stats['box6']}/{n} ({100*stats['box6']/n:.1f}%)")
    print(f"  フォームB的中:  {stats['formb']}/{n} ({100*stats['formb']/n:.1f}%)")
    print(f"  上位5頭カバー平均: {avg:.2f}頭/3頭中")
    return stats


# ---- メイン ---------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-training", action="store_true", help="調教データなしで採点")
    args = parser.parse_args()
    use_training = not args.no_training

    print(f"全キャッシュ済みレースを新ロジックで再採点中... (調教データ: {'あり(netkeiba)' if use_training else 'なし'})")
    all_rows = []
    skipped = 0
    target_files = sorted(CACHE_RACE.glob("*.json"))
    total = len(target_files)
    training_hit = 0

    for i, f in enumerate(target_files):
        if i % 50 == 0:
            print(f"  {i}/{total}件処理中... (調教HIT: {training_hit})", flush=True)
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        rows = process_race(data, use_training=use_training)
        if rows:
            if use_training and any(r["調教あり"] == "○" for r in rows):
                training_hit += 1
            all_rows.extend(rows)
        else:
            skipped += 1

    print(f"\n対象レース行数: {len(all_rows)}行 (スキップ: {skipped})")
    if use_training:
        races_total = len(set((r["日付"], r["レース名"]) for r in all_rows))
        print(f"調教データあり: {training_hit}/{races_total}レース")

    turf_rows = [r for r in all_rows if "芝" in str(r.get("クラス","") + r.get("レース名",""))
                  or any(f.stem.endswith("芝") for f in [])]
    # 面を正確に判定するため race_result の surface を使う
    # ここでは距離文字列から判定（例: "芝1600m" / "ダ1600m"）
    turf_rows = [r for r in all_rows if r.get("コース") == "芝"]
    dart_rows = [r for r in all_rows if r.get("コース") == "ダ"]

    print("\n=== 芝 ===")
    calc_stats(turf_rows)
    print("\n=== ダート ===")
    calc_stats(dart_rows)
    print("\n=== 全体 ===")
    calc_stats(all_rows)

    suffix = "調教あり" if use_training else "調教なし"
    if all_rows:
        out = BASE / "data" / f"検証_新ロジック_{suffix}.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nCSV保存: {out} ({len(all_rows)}行)")
