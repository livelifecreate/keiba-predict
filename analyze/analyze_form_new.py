"""
新フォーメーション「1軸 × 2〜6 × 2〜6」（10点）の検証
既存フォーム（7点・22点）と比較
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, json
from collections import defaultdict
from itertools import combinations

def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def load_cache(path):
    data = json.load(open(path))
    return {(e["date"], e["venue"], e["race_name"]): e for e in data}

rows = load_csv("data/検証_芝_2026年3〜5月_騎手ボーナスあり.csv") + load_csv("data/検証_芝_2026年1〜2月.csv")
cache_mar = load_cache("data/trio_cache_bonus.json")
cache_jan = load_cache("data/trio_cache_jan_feb.json")

def get_cache(date, venue, name):
    return cache_mar.get((date, venue, name)) or cache_jan.get((date, venue, name))

race_groups = defaultdict(list)
for r in rows:
    race_groups[(r["日付"], r["競馬場"], r["レース名"])].append(r)

# ── フォーメーション定義 ──────────────────────────────────────

def form_7pt(nums):
    """1位・2位軸 × 3〜9位 = 最大7点"""
    if len(nums) < 3: return set()
    ax0, ax1 = nums[0], nums[1]
    return {tuple(sorted([ax0, ax1, b], key=lambda x: int(x)))
            for b in nums[2:9] if b not in (ax0, ax1)}

def form_b_22(nums):
    """1位軸 × 2〜5位 × 2〜9位 = 最大22点"""
    if len(nums) < 3: return set()
    h1 = nums[0]
    result = set()
    for a in nums[1:5]:
        for b in nums[1:9]:
            if a != b:
                result.add(tuple(sorted([h1, a, b], key=lambda x: int(x))))
    return result

def form_new_10(nums):
    """新案A: 1位軸 × 2〜6位 × 2〜6位 = C(5,2)=10点"""
    if len(nums) < 3: return set()
    h1 = nums[0]
    pool = nums[1:6]  # 2〜6位
    return {tuple(sorted([h1, a, b], key=lambda x: int(x)))
            for a, b in combinations(pool, 2)}

def form_new_9(nums):
    """新案B: 1・2軸 × 1〜5 × 1〜5 = 9点（{3,4,5}を除くC(5,3)）"""
    if len(nums) < 3: return set()
    ax = {nums[0], nums[1]}   # 1位か2位を必ず含む
    pool = nums[0:5]          # 1〜5位
    result = set()
    for combo in combinations(pool, 3):
        if set(combo) & ax:   # 1位か2位が少なくとも1頭
            result.add(tuple(sorted(combo, key=lambda x: int(x))))
    return result

# ── 全レース集計 ──────────────────────────────────────────────

records = []
for key, horses in race_groups.items():
    date, venue, name = key
    c = get_cache(date, venue, name)
    if not c:
        continue
    trio = tuple(sorted(c["trio_nums"], key=lambda x: int(x)))
    pay  = c["trio_pay"]
    sh   = sorted(horses, key=lambda h: float(h["予想スコア"]), reverse=True)
    if len(sh) < 3:
        continue

    nums = [h["馬番"] for h in sh]
    c7   = form_7pt(nums)
    c22  = form_b_22(nums)
    c10  = form_new_10(nums)
    c9   = form_new_9(nums)

    score1 = float(sh[0]["予想スコア"])
    score2 = float(sh[1]["予想スコア"])
    odds1  = float(sh[0]["単勝オッズ"]) if sh[0]["単勝オッズ"] else 0
    gap    = score1 - score2
    n      = len(horses)
    has_sc = float(sh[0].get("同コース実績", 0) or 0) >= 4

    records.append({
        "trio": trio, "pay": pay,
        "c7":  c7,  "hit7":  trio in c7,  "bet7":  len(c7)  * 100,
        "c22": c22, "hit22": trio in c22, "bet22": len(c22) * 100,
        "c10": c10, "hit10": trio in c10, "bet10": len(c10) * 100,
        "c9":  c9,  "hit9":  trio in c9,  "bet9":  len(c9)  * 100,
        "odds1": odds1, "gap": gap, "n": n, "has_sc": has_sc,
    })

# ── 統計ヘルパー ──────────────────────────────────────────────

def stat(recs, key):
    h   = sum(r[f"hit{key}"] for r in recs)
    bet = sum(r[f"bet{key}"] for r in recs)
    pay = sum(r["pay"] * r[f"hit{key}"] for r in recs)
    roi = pay / bet * 100 if bet else 0
    return h, roi

def show(label, recs):
    if not recs: return
    n = len(recs)
    h7,  roi7  = stat(recs, "7")
    h9,  roi9  = stat(recs, "9")
    h10, roi10 = stat(recs, "10")
    h22, roi22 = stat(recs, "22")
    print(f"  {label:<34} {n:>4}  "
          f"7pt:{h7/n*100:>4.0f}%/{roi7:>6.1f}%  "
          f"9pt:{h9/n*100:>4.0f}%/{roi9:>6.1f}%  "
          f"10pt:{h10/n*100:>4.0f}%/{roi10:>6.1f}%  "
          f"22pt:{h22/n*100:>4.0f}%/{roi22:>6.1f}%")

# ── 出力 ─────────────────────────────────────────────────────

N = len(records)
print(f"全期間: {N}レース")
print()
print(f"  {'条件':<34} {'N':>4}  "
      f"{'7点 命中/ROI':>13}  "
      f"{'9点 命中/ROI':>13}  "
      f"{'10点 命中/ROI':>14}  "
      f"{'22点 命中/ROI':>14}")
print("  " + "─" * 95)

show("全体ベースライン", records)
print()

# 見送り条件フィルター後
active = [r for r in records
          if r["n"] != 18
          and not (3 <= r["gap"] < 5)
          and not r["has_sc"]
          and not (r["odds1"] and 8 <= r["odds1"] < 15)]
show("【見送り除外後】", active)
print()

# オッズ別
print("  ─ オッズ別 ─")
for lo, hi, label in [(0,2,"軸1倍台"),(2,3,"軸2倍台"),(3,5,"軸3〜4倍台"),
                       (5,8,"軸5〜7倍台"),(8,15,"軸8〜14倍台"),(15,999,"軸15倍以上")]:
    show(label, [r for r in records if r["odds1"] and lo <= r["odds1"] < hi])

print()
print("  ─ 乖離別 ─")
for lo, hi, label in [(0,1,"乖離0〜1pt"),(1,2,"乖離1〜2pt"),(2,3,"乖離2〜3pt"),
                       (3,5,"乖離3〜5pt"),(5,99,"乖離5pt以上")]:
    show(label, [r for r in records if lo <= r["gap"] < hi])

print()
print("  ─ 頭数別 ─")
for lo, hi, label in [(0,10,"〜9頭"),(10,14,"10〜13頭"),(14,18,"14〜17頭"),(18,19,"18頭")]:
    show(label, [r for r in records if lo < r["n"] <= hi])

print()
print("  ─ 7点推奨条件（乖離5pt+・13頭以下・軸2〜7倍）─")
cond_7pt = [r for r in records
            if r["gap"] >= 5 and r["n"] <= 13
            and r["odds1"] and 2 <= r["odds1"] < 8]
show("7点推奨条件", cond_7pt)

print()
print("  ─ フォームB強条件 ─")
show("乖離0〜1pt（横並び）",  [r for r in records if r["gap"] < 1])
show("穴軸15倍以上",        [r for r in records if r["odds1"] and r["odds1"] >= 15])
show("14〜17頭立て",       [r for r in records if 14 <= r["n"] <= 17])
