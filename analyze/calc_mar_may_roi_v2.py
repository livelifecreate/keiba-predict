"""
3〜5月の三連複ROI再計算（東京外枠後半加点ロジック追加後）
- trio_cache_bonus.json の払戻データを使用
- 検証_芝_2026年3〜5月_騎手ボーナスあり.csv のスコアに outer_post_tokyo_late を加算
- race_id[8:10] から開催日目を取得（ネットアクセス不要）
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, json, re
from collections import defaultdict


def get_day_of(race_id: str) -> int:
    try:
        return int(race_id[8:10])
    except (ValueError, IndexError):
        return 0


def check_outer_post_tokyo_late(horse_number: str, venue: str, day_of: int) -> float:
    if venue != "東京" or day_of < 6:
        return 0.0
    try:
        return 1.5 if int(horse_number) >= 10 else 0.0
    except (ValueError, TypeError):
        return 0.0


def form_b_triples(sorted_horses: list[dict], score_key: str) -> set[tuple]:
    """予想1〜2位軸 × 3〜9位相手 のフォームB"""
    nums = [h["馬番"] for h in sorted_horses]
    if len(nums) < 5:
        return set()
    ax0, ax1 = nums[0], nums[1]
    others   = nums[2:9]
    result   = set()
    for b in others:
        if b != ax0 and b != ax1:
            combo = tuple(sorted([ax0, ax1, b], key=lambda x: int(x)))
            result.add(combo)
    return result


def main():
    cache = json.load(open("data/trio_cache_bonus.json"))
    rows  = []
    with open("data/検証_芝_2026年3〜5月_騎手ボーナスあり.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # cache を (date, venue, race_name) でインデックス
    cache_by_key = {}
    for e in cache:
        key = (e["date"], e["venue"], e["race_name"])
        cache_by_key[key] = e

    # race_id と日目のマッピング
    race_id_map = {(e["date"], e["venue"], e["race_name"]): e.get("race_id", "") for e in cache}

    # CSVをレース単位にグループ化
    race_groups = defaultdict(list)
    for r in rows:
        key = (r["日付"], r["競馬場"], r["レース名"])
        race_groups[key].append(r)

    # 集計
    stats = {"old": {"races":0,"hit":0,"bet":0,"pay":0},
             "new": {"races":0,"hit":0,"bet":0,"pay":0}}
    no_cache = 0
    change_details = []

    for key, horses in sorted(race_groups.items()):
        date, venue, race_name = key
        c = cache_by_key.get((date, venue, race_name))
        if not c:
            no_cache += 1
            continue

        trio_nums = tuple(sorted(c["trio_nums"], key=lambda x: int(x)))
        trio_pay  = c["trio_pay"]
        race_id   = race_id_map.get((date, venue, race_name), "")
        day_of    = get_day_of(race_id)

        # 新スコア加算
        for h in horses:
            base = float(h["予想スコア"])
            add  = check_outer_post_tokyo_late(h["馬番"], venue, day_of)
            h["_old"] = base
            h["_new"] = base + add

        sorted_old = sorted(horses, key=lambda h: h["_old"], reverse=True)
        sorted_new = sorted(horses, key=lambda h: h["_new"], reverse=True)

        combos_old = form_b_triples(sorted_old, "_old")
        combos_new = form_b_triples(sorted_new, "_new")

        hit_old = trio_nums in combos_old
        hit_new = trio_nums in combos_new
        bet_old = len(combos_old) * 100
        bet_new = len(combos_new) * 100

        stats["old"]["races"] += 1
        stats["old"]["hit"]   += hit_old
        stats["old"]["bet"]   += bet_old
        stats["old"]["pay"]   += trio_pay if hit_old else 0
        stats["new"]["races"] += 1
        stats["new"]["hit"]   += hit_new
        stats["new"]["bet"]   += bet_new
        stats["new"]["pay"]   += trio_pay if hit_new else 0

        if combos_old != combos_new:
            change_details.append({
                "date": date, "venue": venue, "name": race_name,
                "day": day_of, "trio_pay": trio_pay,
                "old_hit": hit_old, "new_hit": hit_new,
            })

    print("=== 3〜5月 東京外枠後半ロジック追加 ROI比較 ===\n")
    print(f"{'項目':<16} {'旧（騎手ボーナスのみ）':>22} {'新（+外枠後半）':>18}")
    print("-" * 60)

    o, n = stats["old"], stats["new"]
    roi_old = o["pay"] / o["bet"] * 100 if o["bet"] else 0
    roi_new = n["pay"] / n["bet"] * 100 if n["bet"] else 0

    print(f"{'検証レース数':<16} {o['races']:>22} {n['races']:>18}")
    print(f"{'命中数':<16} {o['hit']:>22} {n['hit']:>18}")
    print(f"{'命中率':<16} {o['hit']/o['races']*100:>21.1f}% {n['hit']/n['races']*100:>17.1f}%")
    print(f"{'総賭け金':<16} {o['bet']:>22,} {n['bet']:>18,}")
    print(f"{'総払戻':<16} {o['pay']:>22,} {n['pay']:>18,}")
    print(f"{'ROI':<16} {roi_old:>21.1f}% {roi_new:>17.1f}%")
    print(f"\ntrio_cacheなし（除外）: {no_cache}レース")

    if change_details:
        print(f"\n=== 組み合わせが変化したレース ({len(change_details)}件) ===")
        for d in change_details:
            old_m = "◎" if d["old_hit"] else "×"
            new_m = "◎" if d["new_hit"] else "×"
            chg = ""
            if not d["old_hit"] and d["new_hit"]:
                chg = " ← 新規命中!"
            elif d["old_hit"] and not d["new_hit"]:
                chg = " ← 命中消滅!"
            print(f"  {d['date']} {d['venue']} {d['name']} "
                  f"({d['day']}日目) 旧:{old_m} 新:{new_m} 払戻={d['trio_pay']:,}円{chg}")
    else:
        print("\n組み合わせ変化なし（外枠後半ロジックは順位に影響しなかった）")


if __name__ == "__main__":
    main()
