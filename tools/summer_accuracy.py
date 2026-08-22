#!/usr/bin/env python3
"""
夏レースの採点精度を逆算
実着順1位の馬の平均スコア vs その他の馬で、判別精度を推定
"""
import json
import glob
from collections import defaultdict
import statistics

print("=" * 80)
print("【夏競馬 採点精度分析】勝馬スコア vs 敗馬スコア")
print("=" * 80)

# キャッシュからデータ抽出
summer_races = []
for f in sorted(glob.glob('cache/race_result/*.json')):
    try:
        with open(f) as fp:
            data = json.load(fp)
            date_str = data.get('date', '')
            venue = data.get('venue', '')

            if ('2024年7月' in date_str or '2025年7月' in date_str) and venue in {'小倉', '函館', '福島'}:
                summer_races.append(data)
    except:
        pass

# 1位馬と下位馬のオッズ・人気を比較（代理指標として使用）
print("\n【1. オッズによる勝敗予測精度】")

accuracy_by_osd = defaultdict(list)  # オッズ順位別

for race in summer_races:
    entries = race.get('entries', [])
    if not entries:
        continue

    # オッズでソート
    entries_with_odds = [(e, e.get('odds', 0)) for e in entries if e.get('odds', 0) > 0]
    entries_with_odds.sort(key=lambda x: x[1])

    # オッズ順位付け
    for rank, (entry, odds) in enumerate(entries_with_odds, 1):
        actual_rank = entry.get('rank', 99)
        is_in_three = actual_rank <= 3
        accuracy_by_osd[rank].append(is_in_three)

print("  オッズ順位別の3着以内的中率:")
for rank in sorted(accuracy_by_osd.keys())[:10]:
    hit_rate = sum(accuracy_by_osd[rank]) / len(accuracy_by_osd[rank]) * 100
    print(f"    オッズ1位～{rank}位中の{rank}位: {hit_rate:.1f}% (n={len(accuracy_by_osd[rank])})")

# 2位馬（市場の人気）による分析
print("\n【2. 人気順位による勝敗予測精度】")

accuracy_by_pop = defaultdict(list)

for race in summer_races:
    entries = race.get('entries', [])
    if not entries:
        continue

    # 人気でソート
    entries_with_pop = [(e, e.get('popularity', 99)) for e in entries if e.get('popularity', 99) < 99]
    entries_with_pop.sort(key=lambda x: x[1])

    for rank, (entry, pop) in enumerate(entries_with_pop, 1):
        actual_rank = entry.get('rank', 99)
        is_in_three = actual_rank <= 3
        accuracy_by_pop[rank].append(is_in_three)

print("  人気順位別の3着以内的中率:")
for rank in sorted(accuracy_by_pop.keys())[:10]:
    hit_rate = sum(accuracy_by_pop[rank]) / len(accuracy_by_pop[rank]) * 100
    print(f"    人気1位～{rank}位中の{rank}位: {hit_rate:.1f}% (n={len(accuracy_by_pop[rank])})")

# 3. 場所別の市場精度
print("\n【3. 場所別の市場精度（オッズ1位→3着以内）】")

venue_accuracy = {}
for venue in ['小倉', '函館', '福島']:
    venue_races = [r for r in summer_races if r.get('venue') == venue]
    hits = 0
    total = 0

    for race in venue_races:
        entries = race.get('entries', [])
        if not entries:
            continue

        # オッズ1位馬を特定
        entries_with_odds = [(e, e.get('odds', 0)) for e in entries if e.get('odds', 0) > 0]
        if not entries_with_odds:
            continue

        entries_with_odds.sort(key=lambda x: x[1])
        favorite = entries_with_odds[0][0]

        actual_rank = favorite.get('rank', 99)
        if actual_rank <= 3:
            hits += 1
        total += 1

    if total > 0:
        accuracy = hits / total * 100
        venue_accuracy[venue] = (accuracy, total)
        print(f"  {venue}: {accuracy:.1f}% (n={total}R)")

# 4. クラス別の市場精度
print("\n【4. クラス別の市場精度（オッズ1位→3着以内）】")

class_accuracy = {}
for race_class in ['未勝利', '1勝クラス', '2勝クラス', '3勝クラス', 'OP', '重賞']:
    class_races = [r for r in summer_races if r.get('race_class') == race_class]
    hits = 0
    total = 0

    for race in class_races:
        entries = race.get('entries', [])
        if not entries:
            continue

        entries_with_odds = [(e, e.get('odds', 0)) for e in entries if e.get('odds', 0) > 0]
        if not entries_with_odds:
            continue

        entries_with_odds.sort(key=lambda x: x[1])
        favorite = entries_with_odds[0][0]

        actual_rank = favorite.get('rank', 99)
        if actual_rank <= 3:
            hits += 1
        total += 1

    if total > 0:
        accuracy = hits / total * 100
        class_accuracy[race_class] = (accuracy, total)
        print(f"  {race_class}: {accuracy:.1f}% (n={total}R)")

# 5. コース別の市場精度
print("\n【5. コース別の市場精度（オッズ1位→3着以内）】")

surface_accuracy = {}
for surface in ['芝', 'ダ']:
    surface_races = [r for r in summer_races if r.get('surface') == surface]
    hits = 0
    total = 0

    for race in surface_races:
        entries = race.get('entries', [])
        if not entries:
            continue

        entries_with_odds = [(e, e.get('odds', 0)) for e in entries if e.get('odds', 0) > 0]
        if not entries_with_odds:
            continue

        entries_with_odds.sort(key=lambda x: x[1])
        favorite = entries_with_odds[0][0]

        actual_rank = favorite.get('rank', 99)
        if actual_rank <= 3:
            hits += 1
        total += 1

    if total > 0:
        accuracy = hits / total * 100
        surface_accuracy[surface] = (accuracy, total)
        print(f"  {surface}: {accuracy:.1f}% (n={total}R)")

# 6. 結論
print("\n【結論】")
print("  市場（オッズ）の予測精度:")
print(f"    全体: {sum(accuracy_by_osd[1]) / len(accuracy_by_osd[1]) * 100:.1f}%")
print("\n  採点システムの課題（推定）:")
print("    - 市場（オッズ）より精度が落ちる場合: スコア計算に場所別・季節別の補正が不足")
print("    - 特定の場所・クラスで弱い場合: その条件下での過去データが不足している可能性")

print("\n" + "=" * 80)
