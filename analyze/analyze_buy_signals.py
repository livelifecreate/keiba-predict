"""
買いサイン・外れサイン分析
- フォームB（1-2軸 × 3〜9位相手）での命中/外れを各条件で層別化
- データ: 3〜5月 + 1〜2月（全期間）
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, json
from collections import defaultdict
import statistics

# ─────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────
def form_b_triples(sorted_horses: list) -> set:
    nums = [h["馬番"] for h in sorted_horses]
    if len(nums) < 5:
        return set()
    ax0, ax1 = nums[0], nums[1]
    result = set()
    for b in nums[2:9]:
        if b != ax0 and b != ax1:
            result.add(tuple(sorted([ax0, ax1, b], key=lambda x: int(x))))
    return result

def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def load_cache(path):
    data = json.load(open(path))
    idx = {}
    for e in data:
        idx[(e["date"], e["venue"], e["race_name"])] = e
    return idx

def bucket(val, breaks):
    """val がどの区間に入るか返す"""
    for lo, hi, label in breaks:
        if lo <= val < hi:
            return label
    return breaks[-1][2]

# ─────────────────────────────────────────
# データ読み込み
# ─────────────────────────────────────────
rows_mar = load_csv("data/検証_芝_2026年3〜5月_騎手ボーナスあり.csv")
rows_jan = load_csv("data/検証_芝_2026年1〜2月.csv")
rows_all = rows_mar + rows_jan

cache_mar = load_cache("data/trio_cache_bonus.json")
cache_jan = load_cache("data/trio_cache_jan_feb.json")

def get_cache(date, venue, race_name):
    return cache_mar.get((date, venue, race_name)) or cache_jan.get((date, venue, race_name))

# ─────────────────────────────────────────
# レース単位に集約
# ─────────────────────────────────────────
race_groups = defaultdict(list)
for r in rows_all:
    race_groups[(r["日付"], r["競馬場"], r["レース名"])].append(r)

# 各レースの統計を収集
records = []
for key, horses in race_groups.items():
    date, venue, race_name = key
    c = get_cache(date, venue, race_name)
    if not c:
        continue

    trio_nums = tuple(sorted(c["trio_nums"], key=lambda x: int(x)))
    trio_pay  = c["trio_pay"]

    sorted_h = sorted(horses, key=lambda h: float(h["予想スコア"]), reverse=True)
    combos   = form_b_triples(sorted_h)
    if not combos:
        continue

    hit = trio_nums in combos
    bet = len(combos) * 100

    h1 = sorted_h[0]  # 1位
    h2 = sorted_h[1]  # 2位
    h3 = sorted_h[2] if len(sorted_h) > 2 else None

    score1 = float(h1["予想スコア"])
    score2 = float(h2["予想スコア"])
    score3 = float(h3["予想スコア"]) if h3 else score2

    odds1 = float(h1["単勝オッズ"]) if h1["単勝オッズ"] else 0
    odds2 = float(h2["単勝オッズ"]) if h2["単勝オッズ"] else 0

    # フラグ系（1位馬に関して）
    has_training_a  = float(h1.get("調教A評価", 0) or 0) >= 3
    has_same_course = float(h1.get("同コース実績", 0) or 0) >= 4
    has_high_grade  = float(h1.get("前走重賞近差", 0) or 0) > 0

    records.append({
        "date": date, "venue": venue, "name": race_name,
        "hit": hit, "bet": bet, "pay": trio_pay if hit else 0, "trio_pay": trio_pay,
        "score1": score1, "score2": score2, "score3": score3,
        "score_gap_12": score1 - score2,   # 1〜2位スコア差
        "score_gap_13": score1 - score3,   # 1〜3位スコア差
        "odds1": odds1, "odds2": odds2,
        "odds_sum_12": odds1 + odds2,
        "n_horses": len(horses),
        "has_training_a": has_training_a,
        "has_same_course": has_same_course,
        "has_high_grade": has_high_grade,
    })

N = len(records)
print(f"分析対象レース数: {N}\n")

# ─────────────────────────────────────────
# 層別分析ヘルパー
# ─────────────────────────────────────────
def analyze(groups: dict, title: str):
    print(f"{'─'*60}")
    print(f"【{title}】")
    print(f"  {'条件':<22} {'N':>4}  {'命中率':>6}  {'ROI':>7}  {'払戻中央値':>9}")
    print(f"  {'-'*22} {'----':>4}  {'------':>6}  {'-------':>7}  {'---------':>9}")
    for label, recs in sorted(groups.items(), key=lambda x: x[0]):
        if not recs:
            continue
        n    = len(recs)
        hits = sum(r["hit"] for r in recs)
        bet  = sum(r["bet"] for r in recs)
        pay  = sum(r["pay"] for r in recs)
        pays_hit = [r["trio_pay"] for r in recs if r["hit"]]
        median_pay = statistics.median(pays_hit) if pays_hit else 0
        roi  = pay / bet * 100 if bet else 0
        hr   = hits / n * 100
        print(f"  {str(label):<22} {n:>4}  {hr:>5.1f}%  {roi:>6.1f}%  {median_pay:>9,.0f}円")
    print()

# ─────────────────────────────────────────
# 1. 軸1位オッズ別
# ─────────────────────────────────────────
breaks_odds = [
    (0,  2,   "1.x倍（断然人気）"),
    (2,  3,   "2倍台"),
    (3,  5,   "3〜4倍台"),
    (5,  8,   "5〜7倍台"),
    (8,  15,  "8〜14倍台"),
    (15, 999, "15倍以上"),
]
g = defaultdict(list)
for r in records:
    g[bucket(r["odds1"], breaks_odds)].append(r)
# 順序固定
ordered = {b[2]: g[b[2]] for b in breaks_odds}
analyze(ordered, "軸1位の単勝オッズ別")

# ─────────────────────────────────────────
# 2. 1位-2位スコア乖離別
# ─────────────────────────────────────────
breaks_gap = [
    (-99, 0,   "1位<2位（逆転）"),
    (0,  1,    "乖離 0〜1点"),
    (1,  2,    "乖離 1〜2点"),
    (2,  3,    "乖離 2〜3点"),
    (3,  5,    "乖離 3〜5点"),
    (5,  99,   "乖離 5点以上"),
]
g = defaultdict(list)
for r in records:
    g[bucket(r["score_gap_12"], breaks_gap)].append(r)
ordered = {b[2]: g[b[2]] for b in breaks_gap}
analyze(ordered, "1位-2位 スコア乖離別")

# ─────────────────────────────────────────
# 3. 軸1位スコア絶対値別
# ─────────────────────────────────────────
breaks_score = [
    (-99, 5,   "5点未満"),
    (5,  8,    "5〜7点"),
    (8,  10,   "8〜9点"),
    (10, 13,   "10〜12点"),
    (13, 99,   "13点以上"),
]
g = defaultdict(list)
for r in records:
    g[bucket(r["score1"], breaks_score)].append(r)
ordered = {b[2]: g[b[2]] for b in breaks_score}
analyze(ordered, "軸1位スコア絶対値別")

# ─────────────────────────────────────────
# 4. 特定フラグ別（調教A/同コース/重賞好走）
# ─────────────────────────────────────────
print("─"*60)
print("【軸1位のフラグ別】")
print(f"  {'条件':<30} {'N':>4}  {'命中率':>6}  {'ROI':>7}")
print(f"  {'-'*30} {'----':>4}  {'------':>6}  {'-------':>7}")
for label, fn in [
    ("調教A評価あり",       lambda r: r["has_training_a"]),
    ("調教A評価なし",       lambda r: not r["has_training_a"]),
    ("同コース実績(+4)あり", lambda r: r["has_same_course"]),
    ("同コース実績(+4)なし", lambda r: not r["has_same_course"]),
    ("前走重賞近差あり",    lambda r: r["has_high_grade"]),
    ("前走重賞近差なし",    lambda r: not r["has_high_grade"]),
]:
    recs = [r for r in records if fn(r)]
    if not recs: continue
    n   = len(recs)
    h   = sum(r["hit"] for r in recs)
    bet = sum(r["bet"] for r in recs)
    pay = sum(r["pay"] for r in recs)
    roi = pay / bet * 100 if bet else 0
    print(f"  {label:<30} {n:>4}  {h/n*100:>5.1f}%  {roi:>6.1f}%")
print()

# ─────────────────────────────────────────
# 5. 出走頭数別
# ─────────────────────────────────────────
breaks_n = [
    (0,  10, "少頭数(〜9頭)"),
    (10, 14, "中頭数(10〜13頭)"),
    (14, 18, "多頭数(14〜17頭)"),
    (18, 99, "フル(18頭)"),
]
g = defaultdict(list)
for r in records:
    g[bucket(r["n_horses"], breaks_n)].append(r)
ordered = {b[2]: g[b[2]] for b in breaks_n}
analyze(ordered, "出走頭数別")

# ─────────────────────────────────────────
# 6. 軸1位オッズ × スコア乖離 クロス集計（買いサイン候補）
# ─────────────────────────────────────────
print("─"*60)
print("【買いサイン候補: 軸1位オッズ × スコア乖離 クロス集計】")
print(f"  {'オッズ × 乖離':<32} {'N':>4}  {'命中率':>6}  {'ROI':>7}")
print(f"  {'-'*32} {'----':>4}  {'------':>6}  {'-------':>7}")

cross_groups = defaultdict(list)
for r in records:
    o_label = bucket(r["odds1"], breaks_odds)
    g_label = bucket(r["score_gap_12"], breaks_gap)
    cross_groups[(o_label, g_label)].append(r)

# ROI降順で表示
sorted_cross = sorted(cross_groups.items(), key=lambda x: (
    sum(r["pay"] for r in x[1]) / max(sum(r["bet"] for r in x[1]), 1) * 100
), reverse=True)

for (ol, gl), recs in sorted_cross[:15]:
    n   = len(recs)
    if n < 3: continue
    h   = sum(r["hit"] for r in recs)
    bet = sum(r["bet"] for r in recs)
    pay = sum(r["pay"] for r in recs)
    roi = pay / bet * 100 if bet else 0
    label = f"{ol} / {gl}"
    print(f"  {label:<32} {n:>4}  {h/n*100:>5.1f}%  {roi:>6.1f}%")
print()

# ─────────────────────────────────────────
# 7. 払戻分布（命中レース）
# ─────────────────────────────────────────
hit_pays = sorted([r["trio_pay"] for r in records if r["hit"]])
print("─"*60)
print("【命中時の払戻分布】")
if hit_pays:
    print(f"  件数: {len(hit_pays)}, 最小: {hit_pays[0]:,}円, 最大: {hit_pays[-1]:,}円")
    print(f"  中央値: {statistics.median(hit_pays):,.0f}円, 平均: {statistics.mean(hit_pays):,.0f}円")
    brackets = [(0,500),(500,1000),(1000,2000),(2000,5000),(5000,10000),(10000,99999)]
    for lo, hi in brackets:
        cnt = sum(1 for p in hit_pays if lo*10 <= p < hi*10)
        if cnt:
            print(f"  {lo*10:>6,}〜{hi*10:>7,}円: {cnt}件")
