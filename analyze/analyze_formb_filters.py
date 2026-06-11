"""
フォームB（22点）専用フィルター分析
+ 7点推奨（2頭軸）の最適閾値探索
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, json, statistics
from collections import defaultdict

def form_7pt(sorted_horses):
    nums = [h["馬番"] for h in sorted_horses]
    if len(nums) < 5:
        return set()
    ax0, ax1 = nums[0], nums[1]
    result = set()
    for b in nums[2:9]:
        if b != ax0 and b != ax1:
            result.add(tuple(sorted([ax0, ax1, b], key=lambda x: int(x))))
    return result

def form_b_22(sorted_horses):
    nums = [h["馬番"] for h in sorted_horses]
    if len(nums) < 5:
        return set()
    h1      = nums[0]
    seconds = nums[1:5]
    others  = nums[1:9]
    result  = set()
    for a in seconds:
        for b in others:
            if a != b:
                result.add(tuple(sorted([h1, a, b], key=lambda x: int(x))))
    return result

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

records = []
for key, horses in race_groups.items():
    date, venue, name = key
    c = get_cache(date, venue, name)
    if not c:
        continue
    trio_nums = tuple(sorted(c["trio_nums"], key=lambda x: int(x)))
    trio_pay  = c["trio_pay"]
    sorted_h  = sorted(horses, key=lambda h: float(h["予想スコア"]), reverse=True)

    c7  = form_7pt(sorted_h)
    c22 = form_b_22(sorted_h)

    h1 = sorted_h[0]
    h2 = sorted_h[1]
    score1 = float(h1["予想スコア"])
    score2 = float(h2["予想スコア"])
    score3 = float(sorted_h[2]["予想スコア"]) if len(sorted_h) > 2 else score2
    odds1  = float(h1["単勝オッズ"]) if h1["単勝オッズ"] else 0
    odds2  = float(h2["単勝オッズ"]) if h2["単勝オッズ"] else 0
    gap12  = score1 - score2
    gap13  = score1 - score3
    n      = len(horses)
    has_sc = float(h1.get("同コース実績", 0) or 0) >= 4

    records.append({
        "date": date, "venue": venue, "name": name,
        "trio_nums": trio_nums, "trio_pay": trio_pay,
        "hit_7": trio_nums in c7, "bet_7": len(c7) * 100,
        "hit_22": trio_nums in c22, "bet_22": len(c22) * 100,
        "score1": score1, "score2": score2, "score3": score3,
        "odds1": odds1, "odds2": odds2,
        "gap12": gap12, "gap13": gap13,
        "n": n, "has_sc": has_sc,
    })

def stat22(recs):
    if not recs:
        return 0, 0.0, 0.0
    n   = len(recs)
    h   = sum(r["hit_22"] for r in recs)
    bet = sum(r["bet_22"] for r in recs)
    pay = sum(r["trio_pay"] * r["hit_22"] for r in recs)
    return n, h/n*100, pay/bet*100 if bet else 0

def stat7(recs):
    if not recs:
        return 0, 0.0, 0.0
    n   = len(recs)
    h   = sum(r["hit_7"] for r in recs)
    bet = sum(r["bet_7"] for r in recs)
    pay = sum(r["trio_pay"] * r["hit_7"] for r in recs)
    return n, h/n*100, pay/bet*100 if bet else 0

def show(label, recs, mode="22"):
    fn = stat22 if mode == "22" else stat7
    n, hr, roi = fn(recs)
    print(f"  {label:<40} {n:>4}  {hr:>5.1f}%  {roi:>6.1f}%")

N = len(records)

# ═══════════════════════════════════════════════
# 1. フォームB単軸別フィルター分析
# ═══════════════════════════════════════════════
print(f"全期間: {N}レース\n")
print("━"*62)
print("【フォームB（22点）フィルター分析】")
print(f"  {'条件':<40} {'N':>4}  {'命中率':>6}  {'ROI':>7}")
print(f"  {'─'*40} {'─'*4}  {'─'*6}  {'─'*7}")

show("全レース（ベースライン）", records)
print()
print("  ─ オッズ別 ─")
for lo, hi, lbl in [(0,2,"1倍台"),(2,3,"2倍台"),(3,5,"3〜4倍台"),
                    (5,8,"5〜7倍台"),(8,15,"8〜14倍台"),(15,99,"15倍以上")]:
    show(f"軸1位 {lbl}", [r for r in records if lo <= r["odds1"] < hi])

print()
print("  ─ 乖離別（1位-2位スコア差）─")
for lo, hi, lbl in [(-99,0,"マイナス（逆転）"),(0,1,"0〜1点"),(1,2,"1〜2点"),
                    (2,3,"2〜3点"),(3,5,"3〜5点"),(5,99,"5点以上")]:
    show(f"乖離 {lbl}", [r for r in records if lo <= r["gap12"] < hi])

print()
print("  ─ 頭数別 ─")
for lo, hi, lbl in [(0,10,"〜9頭"),(10,14,"10〜13頭"),(14,18,"14〜17頭"),(18,99,"18頭")]:
    show(f"{lbl}", [r for r in records if lo <= r["n"] < hi])

print()
print("  ─ 同コース実績 ─")
show("同コース実績あり（1位主因）", [r for r in records if r["has_sc"]])
show("同コース実績なし",            [r for r in records if not r["has_sc"]])

# ═══════════════════════════════════════════════
# 2. フォームB クロス集計（ROI上位）
# ═══════════════════════════════════════════════
print()
print("━"*62)
print("【フォームB クロス集計 ROI上位15】")
print(f"  {'条件':<42} {'N':>4}  {'命中率':>6}  {'ROI':>7}")
print(f"  {'─'*42} {'─'*4}  {'─'*6}  {'─'*7}")

odds_breaks = [(0,2,"1倍台"),(2,3,"2倍台"),(3,5,"3〜4倍台"),
               (5,8,"5〜7倍台"),(8,15,"8〜14倍台"),(15,99,"15倍以上")]
gap_breaks  = [(-99,0,"乖離<0"),(0,1,"乖離0〜1"),(1,2,"乖離1〜2"),
               (2,3,"乖離2〜3"),(3,5,"乖離3〜5"),(5,99,"乖離5+")]
n_breaks    = [(0,10,"〜9頭"),(10,14,"10〜13頭"),(14,99,"14頭以上")]

def get_label(val, breaks):
    for lo, hi, lbl in breaks:
        if lo <= val < hi:
            return lbl
    return breaks[-1][2]

cross = defaultdict(list)
for r in records:
    ol = get_label(r["odds1"], odds_breaks)
    gl = get_label(r["gap12"], gap_breaks)
    nl = get_label(r["n"], n_breaks)
    cross[(ol, gl, nl)].append(r)

sorted_cross = sorted(cross.items(),
    key=lambda x: (sum(r["trio_pay"]*r["hit_22"] for r in x[1]) /
                   max(sum(r["bet_22"] for r in x[1]),1)*100), reverse=True)

for (ol, gl, nl), recs in sorted_cross[:15]:
    n, hr, roi = stat22(recs)
    if n < 3:
        continue
    print(f"  {ol} / {gl} / {nl:<10} {n:>4}  {hr:>5.1f}%  {roi:>6.1f}%")

# ═══════════════════════════════════════════════
# 3. 7点推奨の閾値探索
# ═══════════════════════════════════════════════
print()
print("━"*62)
print("【7点推奨の閾値探索: 乖離 × 頭数 × オッズ】")
print("   7点ROI > 150% かつ 22点ROI との差が大きい条件を探す")
print(f"  {'条件':<40} {'N':>4}  {'7pt ROI':>8}  {'22pt ROI':>9}  {'差':>6}")
print(f"  {'─'*40} {'─'*4}  {'─'*8}  {'─'*9}  {'─'*6}")

combos = [
    ("乖離5+・13頭以下",
     [r for r in records if r["gap12"] >= 5 and r["n"] <= 13]),
    ("乖離5+・13頭以下・軸2〜7倍",
     [r for r in records if r["gap12"] >= 5 and r["n"] <= 13 and 2 <= r["odds1"] < 8]),
    ("乖離3+・13頭以下",
     [r for r in records if r["gap12"] >= 3 and r["n"] <= 13]),
    ("乖離3+・9頭以下",
     [r for r in records if r["gap12"] >= 3 and r["n"] <= 9]),
    ("乖離5+・全頭数",
     [r for r in records if r["gap12"] >= 5]),
    ("乖離4+・13頭以下",
     [r for r in records if r["gap12"] >= 4 and r["n"] <= 13]),
    ("乖離4+・13頭以下・軸2〜7倍",
     [r for r in records if r["gap12"] >= 4 and r["n"] <= 13 and 2 <= r["odds1"] < 8]),
    ("乖離3+・13頭以下・軸2〜7倍",
     [r for r in records if r["gap12"] >= 3 and r["n"] <= 13 and 2 <= r["odds1"] < 8]),
]
for lbl, recs in combos:
    n7,  hr7,  roi7  = stat7(recs)
    n22, hr22, roi22 = stat22(recs)
    diff = roi7 - roi22
    print(f"  {lbl:<40} {n7:>4}  {roi7:>7.1f}%  {roi22:>8.1f}%  {diff:>+5.1f}%")
