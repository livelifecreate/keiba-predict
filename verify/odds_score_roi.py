"""
スコア高×オッズ高の期待値検証
A. 予想1位馬のオッズ帯別単勝ROI
B. 「予想1位 かつ オッズ10倍以上」馬の単勝・複勝・馬連ROI
C. スコア差5pt以上 かつ 軸馬オッズ5〜15倍 → 三連複5頭BOX ROI

使い方:
  cd /Users/du/Documents/競馬予想システム
  python3 verify/odds_score_roi.py
"""
import sys, re, json
sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from pathlib import Path
from collections import defaultdict

from jra_scraper import HorseEntry, RaceInfo
from scorer_turf import score_all as score_turf
from scorer_dart import score_all as score_dart
from cache_store import cache_get, cache_get_before

BASE        = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE  = BASE / 'cache' / 'race_result'
TRAINING_DIR = BASE / 'cache' / 'netkeiba_training'

TARGET_CLASSES = {"2勝クラス", "3勝クラス", "OP", "重賞"}
CLASS_INT      = {"2勝クラス": 2, "3勝クラス": 3, "OP": 4, "重賞": 5,
                  "GIII": 5, "GII": 6, "GI": 7, "GⅢ": 5, "GⅡ": 6, "GⅠ": 7}

# ────────────────────────────────────────────────────────────
# 払い戻しパーサー
# ────────────────────────────────────────────────────────────
def _parse_amounts(s: str) -> list:
    return [int(m.replace(',', '')) for m in re.findall(r'[\d,]+(?=円)', s)]

def _pn_for_count(s: str, count: int) -> list:
    """馬番文字列を count 頭分パース（greedy防止）"""
    nums, i = [], 0
    while i < len(s) and len(nums) < count:
        if i + 2 <= len(s):
            try:
                v2 = int(s[i:i+2])
                if 1 <= v2 <= 18:
                    nums.append(v2); i += 2
                    continue
            except ValueError:
                pass
        try:
            v1 = int(s[i:i+1])
            if 1 <= v1 <= 18:
                nums.append(v1); i += 1
                continue
        except ValueError:
            pass
        i += 1
    return nums

def get_payout(race_id: str, bet_type: str):
    """(horse_nums list, amounts list) を返す"""
    p = cache_get('payouts', race_id)
    if not p:
        return [], []
    v = p.get(bet_type, {})
    raw = v.get('raw', [])
    if len(raw) < 3:
        return [], []
    # 馬番の頭数を額から推定
    n_amounts = len(_parse_amounts(raw[2])) if raw[2] else 0
    count_map = {'単勝': 1, '複勝': n_amounts, '馬連': 2, '3連複': 3}
    count = count_map.get(bet_type, 2)
    hnums   = _pn_for_count(raw[1], count) if raw[1] else []
    amounts = _parse_amounts(raw[2])        if raw[2] else []
    return hnums, amounts

def get_tan_payout(race_id: str, horse_num: int):
    """単勝払い戻し（指定馬番）→ 払戻額（0=的中なし）"""
    hnums, amounts = get_payout(race_id, '単勝')
    if hnums and amounts and hnums[0] == horse_num:
        return amounts[0]
    return 0

def get_fuku_payout(race_id: str, horse_num: int):
    """複勝払い戻し（指定馬番）→ 払戻額（0=的中なし）"""
    p = cache_get('payouts', race_id)
    if not p:
        return 0
    v = p.get('複勝', {})
    raw = v.get('raw', [])
    if len(raw) < 3:
        return 0
    amounts = _parse_amounts(raw[2])
    # 複勝の馬番は raw[1] に「812122」形式
    hn_str = raw[1] if raw[1] else ''
    hnums = _pn_for_count(hn_str, len(amounts))
    if horse_num in hnums:
        idx = hnums.index(horse_num)
        return amounts[idx] if idx < len(amounts) else 0
    return 0

def get_baren_payout(race_id: str, h1: int, h2: int):
    """馬連払い戻し（指定2頭）→ 払戻額（0=的中なし）"""
    hnums, amounts = get_payout(race_id, '馬連')
    if amounts and frozenset(hnums[:2]) == frozenset([h1, h2]):
        return amounts[0]
    return 0

def get_trio_payout(race_id: str, top5_nums: list):
    """三連複払い戻し（5頭BOX）→ 払戻額（0=的中なし）"""
    hnums, amounts = get_payout(race_id, '3連複')
    if hnums and amounts and frozenset(hnums[:3]).issubset(set(top5_nums)):
        return amounts[0]
    return 0

# ────────────────────────────────────────────────────────────
# 調教データ読み込み
# ────────────────────────────────────────────────────────────
def _load_training(race_id: str):
    p = TRAINING_DIR / f"{race_id}.json"
    if not p.exists():
        return None
    try:
        from netkeiba_scraper import TrainingData as TD
        raw = json.loads(p.read_text())
        if not raw:
            return None
        return {n: TD(horse_name=n, rank=v["rank"],
                      comment=v.get("comment", ""), score=v["score"])
                for n, v in raw.items()}
    except Exception:
        return None

# ────────────────────────────────────────────────────────────
# 1レース処理
# ────────────────────────────────────────────────────────────
def process(data: dict):
    """Returns dict with scoring results or None if skipped."""
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
        surface=data["surface"], conditions=data.get("conditions", ""),
        start_time=data.get("start_time", ""), url="",
        race_num=data["race_num_int"],
    )

    entries, rank_map, odds_map, horse_num_map = [], {}, {}, {}
    for e in data["entries"]:
        hid    = e.get("horse_id", "")
        recent = cache_get_before("horse_history", hid, cutoff) or []
        sire   = cache_get("sire", hid) or ""
        he = HorseEntry(
            frame_number=e["frame"], horse_number=e["horse_num"],
            horse_name=e["horse_name"], record="", prize_money="",
            owner="", trainer="", age_sex=e.get("age_sex", ""),
            weight_carried=e.get("weight_carried", ""),
            jockey=e.get("jockey", ""),
            recent_races=recent, sire=sire,
        )
        entries.append(he)
        rank_map[e["horse_name"]]     = e.get("rank", 99)
        odds_map[e["horse_name"]]     = e.get("odds")
        try:
            horse_num_map[e["horse_name"]] = int(e.get("horse_num", 0))
        except (TypeError, ValueError):
            horse_num_map[e["horse_name"]] = None

    if len(entries) < 5:
        return None

    fn = score_dart if data["surface"] == "ダ" else score_turf
    scored = fn(
        entries, race_info,
        training_data=_load_training(data.get("race_id", "")),
        track_condition=data.get("track_condition", ""),
        horse_ids={e["horse_name"]: e.get("horse_id", "") for e in data["entries"]},
    )
    scored.sort(key=lambda x: x[1].total, reverse=True)

    if len(scored) < 2:
        return None

    top1_name  = scored[0][0].horse_name
    top2_name  = scored[1][0].horse_name
    top1_score = scored[0][1].total
    top2_score = scored[1][1].total
    gap        = round(top1_score - top2_score, 2)
    n          = len(scored)
    cls_int    = CLASS_INT.get(data["race_class"], 0)

    odds1 = odds_map.get(top1_name)
    if not odds1 or odds1 <= 0:
        return None  # オッズなしはスキップ

    top5_names = [scored[i][0].horse_name for i in range(min(5, n))]
    top5_nums  = [horse_num_map[nm] for nm in top5_names if horse_num_map.get(nm)]

    def act(name):
        return rank_map.get(name, 99)

    return {
        "race_id":   data.get("race_id", ""),
        "date":      date_str,
        "name":      data["race_name"],
        "class":     data["race_class"],
        "cls_int":   cls_int,
        "surface":   data["surface"],
        "n":         n,
        "gap":       gap,
        "odds1":     odds1,
        "p1_name":   top1_name,
        "p1_num":    horse_num_map.get(top1_name),
        "p1_act":    act(top1_name),
        "p2_name":   top2_name,
        "p2_num":    horse_num_map.get(top2_name),
        "p2_act":    act(top2_name),
        "top5_nums": top5_nums,
    }

# ────────────────────────────────────────────────────────────
# データ読み込み（全キャッシュ）
# ────────────────────────────────────────────────────────────
def load_all() -> list:
    files = sorted(CACHE_RACE.glob("*.json"))
    results = []
    skipped = 0
    for f in files:
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        r = process(data)
        if r is None:
            skipped += 1
            continue
        results.append(r)
    print(f"処理済み: {len(results)}レース / スキップ: {skipped}件")
    return results

# ────────────────────────────────────────────────────────────
# A. 予想1位馬のオッズ帯別単勝ROI
# ────────────────────────────────────────────────────────────
ODDS_BANDS = [
    ("〜2.9倍",    0.0,  2.9),
    ("3〜4.9倍",   3.0,  4.9),
    ("5〜7.9倍",   5.0,  7.9),
    ("8〜14.9倍",  8.0, 14.9),
    ("15〜29.9倍", 15.0, 29.9),
    ("30倍以上",   30.0, 999.9),
]

def section_a(races: list):
    print("\n" + "="*65)
    print("A. 予想1位馬 オッズ帯別 単勝ROI")
    print("="*65)
    print(f"{'帯':<14} {'件数':>5} {'1着':>5} {'1着率':>7} {'回収':>10} {'単勝ROI':>9}")
    print("-"*65)

    for label, lo, hi in ODDS_BANDS:
        group = [r for r in races if lo <= r["odds1"] <= hi]
        if not group:
            print(f"{label:<14} {'0':>5}")
            continue
        invest  = len(group) * 100
        collect = sum(
            get_tan_payout(r["race_id"], r["p1_num"])
            for r in group if r["p1_num"]
        )
        wins    = sum(1 for r in group if r["p1_act"] == 1)
        roi     = collect / invest * 100 if invest else 0
        pct     = wins / len(group) * 100
        print(f"{label:<14} {len(group):>5} {wins:>5} {pct:>6.1f}% {collect:>9,}円 {roi:>7.1f}%")

    # 全体
    invest  = len(races) * 100
    collect = sum(
        get_tan_payout(r["race_id"], r["p1_num"])
        for r in races if r["p1_num"]
    )
    wins    = sum(1 for r in races if r["p1_act"] == 1)
    roi     = collect / invest * 100 if invest else 0
    pct     = wins / len(races) * 100
    print("-"*65)
    print(f"{'全体':<14} {len(races):>5} {wins:>5} {pct:>6.1f}% {collect:>9,}円 {roi:>7.1f}%")

# ────────────────────────────────────────────────────────────
# B. 「予想1位 かつ オッズ10倍以上」の単勝・複勝・馬連ROI
# ────────────────────────────────────────────────────────────
def section_b(races: list):
    print("\n" + "="*65)
    print("B. 予想1位 かつ オッズ10倍以上（市場低評価馬）の期待値")
    print("="*65)

    thresholds = [
        ("オッズ10倍以上", 10.0, 999.9),
        ("オッズ15倍以上", 15.0, 999.9),
        ("オッズ20倍以上", 20.0, 999.9),
    ]

    for label, lo, hi in thresholds:
        group = [r for r in races if lo <= r["odds1"] <= hi]
        n = len(group)
        if n == 0:
            print(f"\n{label}: データなし")
            continue

        # 単勝
        tan_inv = n * 100
        tan_col = sum(get_tan_payout(r["race_id"], r["p1_num"]) for r in group if r["p1_num"])
        tan_roi = tan_col / tan_inv * 100

        # 複勝
        fuku_inv = n * 100
        fuku_col = sum(get_fuku_payout(r["race_id"], r["p1_num"]) for r in group if r["p1_num"])
        fuku_roi = fuku_col / fuku_inv * 100

        # 馬連（予想1位×2位）
        bar_inv = n * 100
        bar_col = 0
        for r in group:
            if r["p1_num"] and r["p2_num"]:
                bar_col += get_baren_payout(r["race_id"], r["p1_num"], r["p2_num"])
        bar_roi = bar_col / bar_inv * 100

        wins = sum(1 for r in group if r["p1_act"] == 1)
        places = sum(1 for r in group if r["p1_act"] <= 3)

        print(f"\n{label} ({n}件)")
        print(f"  単勝: 1着{wins}件({wins/n*100:.1f}%) / 投資{tan_inv:,}円 / 回収{tan_col:,}円 / ROI {tan_roi:.1f}%")
        print(f"  複勝: 3着以内{places}件({places/n*100:.1f}%) / 投資{fuku_inv:,}円 / 回収{fuku_col:,}円 / ROI {fuku_roi:.1f}%")
        print(f"  馬連: 投資{bar_inv:,}円 / 回収{bar_col:,}円 / ROI {bar_roi:.1f}%")

    # クラス別内訳（10倍以上）
    print(f"\n--- クラス別内訳（オッズ10倍以上） ---")
    group10 = [r for r in races if r["odds1"] >= 10.0]
    for cls in ["2勝クラス", "3勝クラス", "OP", "重賞"]:
        sub = [r for r in group10 if r["class"] == cls]
        if not sub:
            continue
        n = len(sub)
        tan_inv = n * 100
        tan_col = sum(get_tan_payout(r["race_id"], r["p1_num"]) for r in sub if r["p1_num"])
        tan_roi = tan_col / tan_inv * 100
        wins    = sum(1 for r in sub if r["p1_act"] == 1)
        print(f"  {cls:<10} {n}件 / 1着{wins}件({wins/n*100:.1f}%) / 単勝ROI {tan_roi:.1f}%")

    # 芝/ダート別（10倍以上）
    print(f"\n--- 芝/ダート別（オッズ10倍以上） ---")
    for surf in ["芝", "ダ"]:
        sub = [r for r in group10 if r["surface"] == surf]
        if not sub:
            continue
        n = len(sub)
        tan_inv = n * 100
        tan_col = sum(get_tan_payout(r["race_id"], r["p1_num"]) for r in sub if r["p1_num"])
        tan_roi = tan_col / tan_inv * 100
        wins    = sum(1 for r in sub if r["p1_act"] == 1)
        print(f"  {surf}  {n}件 / 1着{wins}件({wins/n*100:.1f}%) / 単勝ROI {tan_roi:.1f}%")

# ────────────────────────────────────────────────────────────
# C. スコア差5pt以上 かつ オッズ5〜15倍 → 三連複5頭BOX ROI
#    （現行「8pt以上で信頼」仮説の検証）
# ────────────────────────────────────────────────────────────
def section_c(races: list):
    print("\n" + "="*65)
    print("C. スコア差×オッズ帯 三連複5頭BOX ROI（仮説検証）")
    print("="*65)

    scenarios = [
        ("差5pt以上×オッズ5〜15倍",  5.0, 999, 5.0,  15.0),
        ("差8pt以上×オッズ5〜15倍",  8.0, 999, 5.0,  15.0),
        ("差5pt以上×オッズ3〜10倍",  5.0, 999, 3.0,  10.0),
        ("差5pt以上×オッズ全体",      5.0, 999, 0.0, 999.0),
        ("差8pt以上×オッズ全体",      8.0, 999, 0.0, 999.0),
        ("差3pt未満×オッズ5〜15倍",  0.0, 3.0, 5.0,  15.0),  # 対照群
        ("全対象（フィルタなし）",    0.0, 999, 0.0, 999.0),  # ベースライン
    ]

    print(f"{'シナリオ':<28} {'件数':>5} {'的中':>5} {'的中率':>7} {'回収':>10} {'ROI':>8}")
    print("-"*65)
    for label, gap_lo, gap_hi, odds_lo, odds_hi in scenarios:
        group = [
            r for r in races
            if gap_lo <= r["gap"] < gap_hi
            and odds_lo <= r["odds1"] <= odds_hi
            and len(r["top5_nums"]) >= 3
        ]
        if not group:
            print(f"{label:<28} {'0':>5}")
            continue
        n       = len(group)
        invest  = n * 1000  # 5頭BOX = 10点 × 100円
        collect = sum(get_trio_payout(r["race_id"], r["top5_nums"]) for r in group)
        hits    = sum(1 for r in group if get_trio_payout(r["race_id"], r["top5_nums"]) > 0)
        roi     = collect / invest * 100 if invest else 0
        hit_pct = hits / n * 100
        print(f"{label:<28} {n:>5} {hits:>5} {hit_pct:>6.1f}% {collect:>9,}円 {roi:>7.1f}%")

    # 差×オッズ帯のマトリクス（スコア差 × オッズ帯）
    print(f"\n--- スコア差 × オッズ帯 マトリクス（三連複5BOX ROI）---")
    gap_ranges  = [("diff<3",  0, 3), ("diff3-5", 3, 5), ("diff5-8", 5, 8), ("diff8+", 8, 999)]
    odds_ranges = [("〜4.9", 0, 4.9), ("5〜9.9", 5, 9.9), ("10〜14.9", 10, 14.9), ("15〜29.9", 15, 29.9), ("30+", 30, 999)]

    header = f"{'スコア差':<12}" + "".join(f"{ol:>11}" for ol, *_ in odds_ranges)
    print(header)
    for glabel, glo, ghi in gap_ranges:
        row = f"{glabel:<12}"
        for olabel, olo, ohi in odds_ranges:
            sub = [
                r for r in races
                if glo <= r["gap"] < ghi
                and olo <= r["odds1"] <= ohi
                and len(r["top5_nums"]) >= 3
            ]
            if not sub:
                row += f"{'--':>11}"
                continue
            invest  = len(sub) * 1000
            collect = sum(get_trio_payout(r["race_id"], r["top5_nums"]) for r in sub)
            roi     = collect / invest * 100
            row += f"{roi:>9.0f}% ({len(sub)})"
        print(row)

# ────────────────────────────────────────────────────────────
# 判定コメント
# ────────────────────────────────────────────────────────────
def print_verdict(races: list):
    print("\n" + "="*65)
    print("【判定コメント】")
    print("="*65)

    # 高オッズ帯の単勝ROI
    hi_odds = [r for r in races if r["odds1"] >= 10.0]
    n_hi = len(hi_odds)
    if n_hi > 0:
        tan_col = sum(get_tan_payout(r["race_id"], r["p1_num"]) for r in hi_odds if r["p1_num"])
        tan_roi = tan_col / (n_hi * 100) * 100
        verdict_b = "★買い追加候補" if tan_roi >= 100 else "✗ 期待値マイナス"
        print(f"B. 予想1位×オッズ10倍以上の単勝ROI: {tan_roi:.1f}% → {verdict_b}")
    else:
        print("B. オッズ10倍以上のサンプルなし")

    # 差5pt×オッズ5〜15倍の三連複
    c_group = [
        r for r in races
        if r["gap"] >= 5.0 and 5.0 <= r["odds1"] <= 15.0
        and len(r["top5_nums"]) >= 3
    ]
    if c_group:
        invest  = len(c_group) * 1000
        collect = sum(get_trio_payout(r["race_id"], r["top5_nums"]) for r in c_group)
        roi_c   = collect / invest * 100
        verdict_c = "★買い追加候補" if roi_c >= 100 else "✗ 期待値マイナス"
        print(f"C. 差5pt×オッズ5〜15倍の三連複5BOX ROI: {roi_c:.1f}% → {verdict_c}")

    # 最高ROI帯の特定
    best_roi   = 0
    best_label = ""
    for label, lo, hi in ODDS_BANDS:
        group = [r for r in races if lo <= r["odds1"] <= hi]
        if not group:
            continue
        invest  = len(group) * 100
        collect = sum(get_tan_payout(r["race_id"], r["p1_num"]) for r in group if r["p1_num"])
        roi     = collect / invest * 100
        if roi > best_roi:
            best_roi   = roi
            best_label = label
    if best_roi >= 100:
        print(f"\n単勝最高ROI帯: {best_label}（{best_roi:.1f}%）→ 買い目戦略に追加検討")
    else:
        print(f"\n単勝最高ROI帯: {best_label}（{best_roi:.1f}%）→ 全帯でROI100%未満")

    print("\n注意: バックテスト期間のROIは過去データへの適合を含む。")
    print("      ROI>120%以上かつ件数50件以上を実運用追加の最低基準とする。")


# ────────────────────────────────────────────────────────────
# メイン
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    t0 = time.time()
    print("全キャッシュからレース読み込み中...")
    races = load_all()
    print(f"読み込み完了: {len(races)}件 ({time.time()-t0:.1f}秒)")

    section_a(races)
    section_b(races)
    section_c(races)
    print_verdict(races)
