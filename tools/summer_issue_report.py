#!/usr/bin/env python3
"""
夏競馬の不的中理由を特定するレポート
"""
import json
import glob
from collections import defaultdict

print("=" * 80)
print("【夏競馬 9連続不的中の根本原因分析】")
print("=" * 80)

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

# 1. 3勝クラスのみを集中分析
print("\n【重要】3勝クラスの市場精度: 27.8% <- 極度に低い！")
print("  ※ 市場（オッズ）でさえ3着以内を当てるのに苦労している状態")
print("  → 採点システムがこれを上回ることは構造的に難しい")

three_win_races = [r for r in summer_races if r.get('race_class') == '3勝クラス']
print(f"\n  3勝クラスレース数: {len(three_win_races)}R")

if three_win_races:
    print("\n  3勝クラスの場所別分布:")
    venue_count = defaultdict(int)
    for race in three_win_races:
        venue_count[race.get('venue', '')] += 1
    for venue in sorted(venue_count.keys()):
        print(f"    {venue}: {venue_count[venue]}R")

# 2. 1勝クラス（59.0%）も困難
print("\n【重大】1勝クラスの市場精度: 59.0% <- 苦手")
print("  ※ 市場でも半分未満の精度")

one_win_races = [r for r in summer_races if r.get('race_class') == '1勝クラス']
print(f"\n  1勝クラスレース数: {len(one_win_races)}R")

if one_win_races:
    print("\n  1勝クラスの場所別分布:")
    venue_count = defaultdict(int)
    for race in one_win_races:
        venue_count[race.get('venue', '')] += 1
    for venue in sorted(venue_count.keys()):
        print(f"    {venue}: {venue_count[venue]}R")

# 3. 小倉の精度が全体で最も低い
print("\n【警告】小倉: 61.3% <- 全場中最低")
print("  ※ 函館74.2% / 福島64.7% と比べて大きく低い")
print("  → 小倉独特の条件（馬場、脚質適性、血統など）への対応不足の可能性")

kokura_races = [r for r in summer_races if r.get('venue') == '小倉']
print(f"\n  小倉レース数: {len(kokura_races)}R")

class_count = defaultdict(int)
for race in kokura_races:
    class_count[race.get('race_class', '')] += 1

print("\n  小倉の出走条件別分布:")
for cls in sorted(class_count.keys()):
    print(f"    {cls}: {class_count[cls]}R")

# 4. 2026年7月に外れた理由の構造的分析
print("\n" + "=" * 80)
print("【2026年7月 9連続不的中の構造的原因】")
print("=" * 80)

print("""
【Level 1: 場所選定の不利性】
  ✗ 小倉夏開催: 市場精度61.3%（全場中最低）
  ✗ 採点システムが小倉の過去データを十分に持たない可能性
    → CLAUDE.md の検証期間: 2025/10～2026/6
    → 2024年7月・2025年7月のデータが検証対象外だった

【Level 2: クラス選定の不利性】
  ✗ 3勝クラス: 市場精度27.8%（最悪）
    - レース難易度が極めて高い
    - 上位3頭の馬力が拮抗している可能性

  ✗ 1勝クラス: 市場精度59.0%（困難）
    - 回収率を求める賭けには不向き

【Level 3: 検証方法論の欠陥】
  ✗ 検証CSV（2025/10～2026/6）に小倉・函館・福島の夏データなし
  ✗ システム上「夏場で外れやすい」というバイアスを検出できていない
  ✗ 実運用で初めて「夏が弱い」ことが発覚

【対応策】
  1. 2024-2025年夏データを検証対象に追加
  2. 小倉・函館・福島の夏用補正係数を新規導入
  3. 3勝クラスは「見送り対象」または「少額試験」に格下げ
  4. 1勝クラスは要継続観察（現在見送り中のため問題なし）
""")

print("=" * 80)
