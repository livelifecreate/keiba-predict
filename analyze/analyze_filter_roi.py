"""
買いサイン/見送りフィルター別ROIシミュレーション（全期間）
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, json
from collections import defaultdict

def form_b_triples(sorted_horses):
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

rows = load_csv("data/検証_芝_2026年3〜5月_騎手ボーナスあり.csv") + load_csv("data/検証_芝_2026年1〜2月.csv")
cache_mar = load_cache("data/trio_cache_bonus.json")
cache_jan = load_cache("data/trio_cache_jan_feb.json")

def get_cache(date, venue, name):
    return cache_mar.get((date, venue, name)) or cache_jan.get((date, venue, name))

race_groups = defaultdict(list)
for r in rows:
    race_groups[(r["日付"], r["競馬場"], r["レース名"])].append(r)

# 全レースのデータを収集
records = []
for key, horses in race_groups.items():
    date, venue, name = key
    c = get_cache(date, venue, name)
    if not c:
        continue
    trio_nums = tuple(sorted(c["trio_nums"], key=lambda x: int(x)))
    trio_pay  = c["trio_pay"]

    sorted_h  = sorted(horses, key=lambda h: float(h["予想スコア"]), reverse=True)
    combos    = form_b_triples(sorted_h)
    if not combos:
        continue

    h1 = sorted_h[0]
    h2 = sorted_h[1]

    score1    = float(h1["予想スコア"])
    score2    = float(h2["予想スコア"])
    odds1     = float(h1["単勝オッズ"]) if h1["単勝オッズ"] else 0
    gap       = score1 - score2
    n_horses  = len(horses)
    has_same_course_top = float(h1.get("同コース実績", 0) or 0) >= 4
    hit       = trio_nums in combos
    bet       = len(combos) * 100

    records.append({
        "date": date, "venue": venue, "name": name,
        "hit": hit, "bet": bet, "pay": trio_pay if hit else 0,
        "trio_pay": trio_pay,
        "score1": score1, "odds1": odds1, "gap": gap,
        "n_horses": n_horses,
        "has_same_course_top": has_same_course_top,
    })

def roi_summary(recs, label):
    if not recs:
        return f"  {label:<38} {'0':>4}  ---     ---"
    n   = len(recs)
    h   = sum(r["hit"] for r in recs)
    bet = sum(r["bet"] for r in recs)
    pay = sum(r["pay"] for r in recs)
    roi = pay / bet * 100 if bet else 0
    return f"  {label:<38} {n:>4}  {h/n*100:>5.1f}%  {roi:>6.1f}%"

print(f"全期間レース数: {len(records)}\n")
print(f"  {'条件':<38} {'N':>4}  {'命中率':>6}  {'ROI':>7}")
print(f"  {'─'*38} {'─'*4}  {'─'*6}  {'─'*7}")

# ── ベースライン ──
print(roi_summary(records, "【全レース（ベースライン）】"))

print()
print("  ─ 見送りフィルター（除外条件）─")

# 軸8倍以上を除外
f1 = [r for r in records if r["odds1"] < 8]
print(roi_summary(f1, "軸1位 8倍未満のみ"))

# 13頭以下のみ
f2 = [r for r in records if r["n_horses"] <= 13]
print(roi_summary(f2, "出走13頭以下のみ"))

# 両方除外
f3 = [r for r in records if r["odds1"] < 8 and r["n_horses"] <= 13]
print(roi_summary(f3, "軸8倍未満 かつ 13頭以下"))

# 乖離3〜5点除外
f4 = [r for r in records if not (3 <= r["gap"] < 5)]
print(roi_summary(f4, "乖離3〜5点を除外"))

# 同コース実績が主因の時除外
f5 = [r for r in records if not r["has_same_course_top"]]
print(roi_summary(f5, "同コース実績(+4)が1位要因を除外"))

# 全見送り条件を適用
f_all_skip = [r for r in records
              if r["odds1"] < 8
              and r["n_horses"] <= 13
              and not r["has_same_course_top"]]
print(roi_summary(f_all_skip, "全見送り条件を適用"))

print()
print("  ─ 買いサインのみで勝負 ─")

# 乖離5点以上
b1 = [r for r in records if r["gap"] >= 5]
print(roi_summary(b1, "乖離5点以上のみ"))

# 軸2〜7倍台
b2 = [r for r in records if 2 <= r["odds1"] < 8]
print(roi_summary(b2, "軸2〜7倍台のみ"))

# 少頭数
b3 = [r for r in records if r["n_horses"] <= 9]
print(roi_summary(b3, "少頭数(〜9頭)のみ"))

# 軸2〜7倍台 + 乖離5点以上
b4 = [r for r in records if 2 <= r["odds1"] < 8 and r["gap"] >= 5]
print(roi_summary(b4, "軸2〜7倍台 ＋ 乖離5点以上"))

# 乖離5点以上 + 13頭以下
b5 = [r for r in records if r["gap"] >= 5 and r["n_horses"] <= 13]
print(roi_summary(b5, "乖離5点以上 ＋ 13頭以下"))

# 乖離1〜2点 + 軸3〜7倍台（クロス分析で良かった組み合わせ）
b6 = [r for r in records if 1 <= r["gap"] < 2 and 3 <= r["odds1"] < 8]
print(roi_summary(b6, "乖離1〜2点 ＋ 軸3〜7倍台"))

# 最強候補：軸2〜7倍台 + 乖離5点以上 + 13頭以下
b7 = [r for r in records if 2 <= r["odds1"] < 8 and r["gap"] >= 5 and r["n_horses"] <= 13]
print(roi_summary(b7, "軸2〜7倍台 ＋ 乖離5点以上 ＋ 13頭以下"))

# 総合ベスト候補
b8 = [r for r in records
      if r["odds1"] < 8
      and r["n_horses"] <= 13
      and r["gap"] >= 5
      and not r["has_same_course_top"]]
print(roi_summary(b8, "全買いサイン条件（厳選）"))

print()
print("  ─ 参考: 各フィルターで除外されたレース ─")
skip1 = [r for r in records if r["odds1"] >= 8]
skip2 = [r for r in records if r["n_horses"] >= 14]
skip3 = [r for r in records if 3 <= r["gap"] < 5]
skip4 = [r for r in records if r["has_same_course_top"]]
print(roi_summary(skip1, "除外対象: 軸8倍以上"))
print(roi_summary(skip2, "除外対象: 14頭以上"))
print(roi_summary(skip3, "除外対象: 乖離3〜5点"))
print(roi_summary(skip4, "除外対象: 同コース実績主因"))
