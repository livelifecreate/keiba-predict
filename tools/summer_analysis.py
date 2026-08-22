#!/usr/bin/env python3
"""
2024年7月・2025年7月の夏レース結果を直接分析
キャッシュデータから統計情報を抽出
"""
import json
import glob
from collections import defaultdict

print("=" * 80)
print("【夏競馬分析】2024年・2025年7月レース（小倉・函館・福島）")
print("=" * 80)

# キャッシュからデータ抽出
summer_data = []
for f in sorted(glob.glob('cache/race_result/*.json')):
    try:
        with open(f) as fp:
            data = json.load(fp)
            date_str = data.get('date', '')
            venue = data.get('venue', '')

            if ('2024年7月' in date_str or '2025年7月' in date_str) and venue in {'小倉', '函館', '福島'}:
                summer_data.append(data)
    except:
        pass

print(f"\n【データセット】 {len(summer_data)}レース")

# 1. レース分布
print("\n【1. レース分布】")
date_counter = defaultdict(int)
venue_counter = defaultdict(int)
class_counter = defaultdict(int)
surface_counter = defaultdict(int)

for race in summer_data:
    date_str = race.get('date', '')
    date_counter[date_str] += 1
    venue_counter[race.get('venue', '')] += 1
    class_counter[race.get('race_class', '')] += 1
    surface_counter[race.get('surface', '')] += 1

print(f"  総レース数: {len(summer_data)}")
print(f"  日付別:")
for date in sorted(date_counter.keys()):
    print(f"    {date}: {date_counter[date]}R")

print(f"  場所別:")
for venue in sorted(venue_counter.keys()):
    print(f"    {venue}: {venue_counter[venue]}R")

print(f"  クラス別:")
for cls in sorted(class_counter.keys()):
    print(f"    {cls}: {class_counter[cls]}R")

print(f"  コース別:")
for surface in sorted(surface_counter.keys()):
    print(f"    {surface}: {surface_counter[surface]}R")

# 2. 1着馬のオッズ分布（ポピュラリティ）
print("\n【2. 1着馬の人気度分析】")
win_popularity = []
win_odds = []

for race in summer_data:
    for entry in race.get('entries', []):
        if entry.get('rank') == 1:  # 1着
            pop = entry.get('popularity', 0)
            odds = entry.get('odds', 0)
            if pop > 0:
                win_popularity.append(pop)
            if odds > 0:
                win_odds.append(odds)

if win_popularity:
    print(f"  1着馬の平均人気: {sum(win_popularity)/len(win_popularity):.1f}人気")
    print(f"  1着馬の平均オッズ: {sum(win_odds)/len(win_odds):.1f}倍")

    # 人気別の勝利数
    pop_dist = defaultdict(int)
    for pop in win_popularity:
        if pop <= 3:
            pop_dist['1-3人気'] += 1
        elif pop <= 5:
            pop_dist['4-5人気'] += 1
        else:
            pop_dist['6人気以下'] += 1

    print(f"  1着馬の人気分布:")
    for pop_range in sorted(pop_dist.keys()):
        print(f"    {pop_range}: {pop_dist[pop_range]}件")

# 3. 馬場状態の分布
print("\n【3. 馬場状態の分布】")
track_condition = defaultdict(int)
for race in summer_data:
    tc = race.get('track_condition', '不明')
    track_condition[tc] += 1

for condition in sorted(track_condition.keys()):
    pct = track_condition[condition]/len(summer_data)*100
    print(f"  {condition}: {track_condition[condition]}R ({pct:.1f}%)")

# 4. コース別・クラス別の出走頭数（ボリューム確認）
print("\n【4. 出走頭数統計】")
for surface in ['芝', 'ダ']:
    races_by_surface = [r for r in summer_data if r.get('surface') == surface]
    if races_by_surface:
        entries_by_surface = sum(len(r.get('entries', [])) for r in races_by_surface)
        avg_heads = entries_by_surface / len(races_by_surface)
        print(f"  {surface}: {len(races_by_surface)}R × 平均{avg_heads:.1f}頭 = 計{entries_by_surface}頭")

# 5. 次のステップの推奨
print("\n【推奨される次の検証項目】")
print("  ✓ 小倉・函館・福島の3場が summer.config で特別な係数を持つか確認")
print("  ✓ 夏季特有の脚質別成績（逃げ馬・先行馬が有利か）")
print("  ✓ 馬体重変動が激しい季節との相関")
print("  ✓ 出走条件別の采配（未勝利vs1勝クラスの難易度差）")

print("\n" + "=" * 80)
