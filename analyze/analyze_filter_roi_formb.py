"""
7点（2頭軸流し）vs フォームB（22点）の全フィルター比較
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, json
from collections import defaultdict

# ─── 買い方の定義 ───────────────────────────────────────────

def form_7pt(sorted_horses):
    """現行: 1位・2位固定軸 × 3〜9位の1頭 = 最大7点"""
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
    """フォームB: 1位軸 × 2〜5位のどれか × 2〜9位のどれか = 最大22点
    1-2,3,4,5-2,3,4,5,6,7,8,9
    """
    nums = [h["馬番"] for h in sorted_horses]
    if len(nums) < 5:
        return set()
    h1      = nums[0]           # 1位（必ず入る）
    seconds = nums[1:5]         # 2〜5位
    others  = nums[1:9]         # 2〜9位
    result  = set()
    for a in seconds:
        for b in others:
            if a != b:
                result.add(tuple(sorted([h1, a, b], key=lambda x: int(x))))
    return result

# ─── データ読み込み ──────────────────────────────────────────

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

# ─── 全レース集計 ────────────────────────────────────────────

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
    if not c7 and not c22:
        continue

    h1 = sorted_h[0]
    h2 = sorted_h[1]
    score1 = float(h1["予想スコア"])
    score2 = float(h2["予想スコア"])
    odds1  = float(h1["単勝オッズ"]) if h1["単勝オッズ"] else 0
    gap    = score1 - score2
    n      = len(horses)
    has_sc = float(h1.get("同コース実績", 0) or 0) >= 4

    records.append({
        "date": date, "venue": venue, "name": name,
        "trio_nums": trio_nums, "trio_pay": trio_pay,
        "combos_7":  c7,  "hit_7":  trio_nums in c7,  "bet_7":  len(c7)  * 100,
        "combos_22": c22, "hit_22": trio_nums in c22, "bet_22": len(c22) * 100,
        "score1": score1, "odds1": odds1, "gap": gap, "n": n, "has_sc": has_sc,
    })

# ─── サマリー出力 ────────────────────────────────────────────

def row(label, recs):
    if not recs:
        return f"  {label:<38} {'0':>4}  {'---':>6}  {'---':>7}  {'---':>8}  {'---':>7}"
    n = len(recs)
    for key in ("7", "22"):
        pass

    def stat(key):
        h   = sum(r[f"hit_{key}"] for r in recs)
        bet = sum(r[f"bet_{key}"] for r in recs)
        pay = sum(r[f"trio_pay"] * r[f"hit_{key}"] for r in recs)
        roi = pay / bet * 100 if bet else 0
        pts = bet // n // 100  # 平均点数
        return h, roi, pts

    h7,  roi7,  pt7  = stat("7")
    h22, roi22, pt22 = stat("22")
    return (f"  {label:<38} {n:>4}  "
            f"{h7/n*100:>5.1f}%/{h22/n*100:>5.1f}%  "
            f"{roi7:>6.1f}%/{roi22:>6.1f}%  "
            f"avg {pt7:>2}pt/{pt22:>2}pt")

N = len(records)
print(f"全期間レース数: {N}")
print()
print(f"  {'条件':<38} {'N':>4}  {'命中率 7/22':>12}  {'ROI 7/22':>14}  {'平均点数':>10}")
print(f"  {'─'*38} {'─'*4}  {'─'*12}  {'─'*14}  {'─'*10}")

# ベースライン
print(row("【全レース（ベースライン）】", records))
print()
print("  ─ 見送りフィルター ─")
print(row("軸8倍未満のみ",             [r for r in records if r["odds1"] < 8]))
print(row("13頭以下のみ",              [r for r in records if r["n"] <= 13]))
print(row("軸8倍未満 かつ 13頭以下",   [r for r in records if r["odds1"] < 8 and r["n"] <= 13]))
print(row("同コース実績主因を除外",     [r for r in records if not r["has_sc"]]))
print(row("全見送り条件適用",           [r for r in records
                                         if r["odds1"] < 8 and r["n"] <= 13 and not r["has_sc"]]))
print()
print("  ─ 買いサインのみ ─")
print(row("乖離5点以上",               [r for r in records if r["gap"] >= 5]))
print(row("乖離5点以上 ＋ 13頭以下",   [r for r in records if r["gap"] >= 5 and r["n"] <= 13]))
print(row("軸2〜7倍台 ＋ 乖離5点以上 ＋ 13頭以下",
                                        [r for r in records
                                         if 2 <= r["odds1"] < 8 and r["gap"] >= 5 and r["n"] <= 13]))
print(row("全買いサイン条件（厳選）",   [r for r in records
                                         if r["odds1"] < 8 and r["n"] <= 13
                                         and r["gap"] >= 5 and not r["has_sc"]]))
print()
print("  ─ 参考: 除外対象レース ─")
print(row("除外: 軸8倍以上",           [r for r in records if r["odds1"] >= 8]))
print(row("除外: 14頭以上",            [r for r in records if r["n"] >= 14]))
print(row("除外: 乖離3〜5点",          [r for r in records if 3 <= r["gap"] < 5]))

# ─── フォームB 22点でのみの詳細 ──────────────────────────────
print()
print("=" * 70)
print("【フォームB（22点）単独詳細】")
print(f"  {'条件':<38} {'N':>4}  {'命中率':>6}  {'ROI':>7}  {'総賭け金':>10}  {'総払戻':>8}")
print(f"  {'─'*38} {'─'*4}  {'─'*6}  {'─'*7}  {'─'*10}  {'─'*8}")

def row22(label, recs):
    if not recs:
        return f"  {label:<38} {'0':>4}"
    n   = len(recs)
    h   = sum(r["hit_22"] for r in recs)
    bet = sum(r["bet_22"] for r in recs)
    pay = sum(r["trio_pay"] * r["hit_22"] for r in recs)
    roi = pay / bet * 100 if bet else 0
    return (f"  {label:<38} {n:>4}  {h/n*100:>5.1f}%  {roi:>6.1f}%  "
            f"{bet:>10,}  {pay:>8,}")

print(row22("全レース",                    records))
print(row22("軸8倍未満 かつ 13頭以下",
            [r for r in records if r["odds1"] < 8 and r["n"] <= 13]))
print(row22("乖離5点以上",                 [r for r in records if r["gap"] >= 5]))
print(row22("乖離5点以上 ＋ 13頭以下",    [r for r in records if r["gap"] >= 5 and r["n"] <= 13]))
print(row22("軸2〜7倍台 ＋ 乖離5点以上 ＋ 13頭以下",
            [r for r in records if 2 <= r["odds1"] < 8 and r["gap"] >= 5 and r["n"] <= 13]))
print(row22("全買いサイン条件（厳選）",
            [r for r in records if r["odds1"] < 8 and r["n"] <= 13
             and r["gap"] >= 5 and not r["has_sc"]]))
