"""
見送り条件適用後のROI検証
in-memory採点 + cache/payouts/ の実配当データ使用
"""
import sys, re, json
sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from pathlib import Path
from collections import defaultdict
from jra_scraper import HorseEntry, RaceInfo
from scorer_turf import score_all as score_turf
from scorer_dart import score_all as score_dart
from cache_store import cache_get, cache_get_before

BASE            = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE      = BASE / 'cache' / 'race_result'
TRAINING_DIR    = BASE / 'cache' / 'netkeiba_training'

TARGET_CLASSES  = {"2勝クラス", "3勝クラス", "OP", "重賞"}
CLASS_INT       = {"2勝クラス": 2, "3勝クラス": 3, "OP": 4, "重賞": 5}


# ---- 払い戻しパーサー -----------------------------------------------------------

def _parse_amounts(s: str) -> list[int]:
    return [int(m.replace(',','')) for m in re.findall(r'[\d,]+(?=円)', s)]

def _parse_horse_nums(s: str) -> list[int]:
    nums, i = [], 0
    while i < len(s):
        if i + 2 <= len(s) and int(s[i:i+2]) <= 18:
            nums.append(int(s[i:i+2])); i += 2
        else:
            nums.append(int(s[i:i+1])); i += 1
    return nums

def get_payout(race_id: str, bet_type: str):
    p = cache_get('payouts', race_id)
    if not p: return [], []
    v = p.get(bet_type, {})
    raw = v.get('raw', [])
    if len(raw) < 3: return [], []
    return _parse_horse_nums(raw[1]) if raw[1] else [], \
           _parse_amounts(raw[2])    if raw[2] else []


# ---- 見送り判定 -----------------------------------------------------------------

def is_skip(gap, n, race_class_int):
    """True=見送り"""
    if n == 18:            return True, "18頭フルゲート"
    if 3 <= gap < 5:       return True, f"乖離{gap:.1f}pt(3〜5pt)"
    if race_class_int < 3: return True, f"2勝クラス以下"
    if race_class_int >= 5:return True, "重賞"
    return False, ""


# ---- 調教データ -----------------------------------------------------------------

def _load_training(race_id):
    p = TRAINING_DIR / f"{race_id}.json"
    if not p.exists(): return None
    try:
        from netkeiba_scraper import TrainingData as TD
        raw = json.loads(p.read_text())
        if not raw: return None
        return {n: TD(horse_name=n, rank=v["rank"], comment=v.get("comment",""), score=v["score"])
                for n, v in raw.items()}
    except Exception:
        return None


# ---- レース処理 -----------------------------------------------------------------

def process(data):
    if data.get("race_class") not in TARGET_CLASSES: return None
    if data.get("surface") not in ("芝", "ダ"):      return None

    date_str = data["date"]
    dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not dm: return None
    cutoff = f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}"

    race_info = RaceInfo(
        name=data["race_name"], date=date_str, venue=data["venue"],
        race_number=f"{data['race_num_int']}R", distance=data["distance"],
        surface=data["surface"], conditions=data.get("conditions",""),
        start_time=data.get("start_time",""), url="", race_num=data["race_num_int"],
    )

    entries, rank_map, odds_map = [], {}, {}
    horse_num_map = {}
    for e in data["entries"]:
        hid  = e.get("horse_id","")
        recent = cache_get_before("horse_history", hid, cutoff) or []
        sire   = cache_get("sire", hid) or ""
        he = HorseEntry(
            frame_number=e["frame"], horse_number=e["horse_num"],
            horse_name=e["horse_name"], record="", prize_money="",
            owner="", trainer="", age_sex=e.get("age_sex",""),
            weight_carried=e.get("weight_carried",""), jockey=e.get("jockey",""),
            recent_races=recent, sire=sire,
        )
        entries.append(he)
        rank_map[e["horse_name"]]     = e.get("rank", 99)
        odds_map[e["horse_name"]]     = e.get("odds")
        try:
            horse_num_map[e["horse_name"]] = int(e.get("horse_num", 0))
        except (TypeError, ValueError):
            horse_num_map[e["horse_name"]] = None

    if len(entries) < 5: return None

    fn = score_dart if data["surface"] == "ダ" else score_turf
    scored = fn(entries, race_info,
                training_data=_load_training(data.get("race_id","")),
                track_condition=data.get("track_condition",""),
                horse_ids={e["horse_name"]: e.get("horse_id","") for e in data["entries"]})
    scored.sort(key=lambda x: x[1].total, reverse=True)

    if len(scored) < 2: return None

    top1_name = scored[0][0].horse_name
    top2_name = scored[1][0].horse_name
    gap       = round(scored[0][1].total - scored[1][1].total, 2)
    n         = len(scored)
    cls_int   = CLASS_INT.get(data["race_class"], 0)
    odds1     = odds_map.get(top1_name)

    # 実着順
    def act(name): return rank_map.get(name, 99)

    actual_top3_nums = {int(horse_num_map[nm]) for nm, rk in rank_map.items()
                        if rk <= 3 and horse_num_map.get(nm) is not None}
    top5_names = [scored[i][0].horse_name for i in range(min(5, n))]
    top4_names = [scored[i][0].horse_name for i in range(min(4, n))]
    top5_nums  = [horse_num_map.get(nm) for nm in top5_names if horse_num_map.get(nm)]
    top4_nums  = [horse_num_map.get(nm) for nm in top4_names if horse_num_map.get(nm)]

    return {
        "race_id":   data.get("race_id",""),
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
        "p2_num":    horse_num_map.get(top2_name),
        "top5_nums": top5_nums,
        "top4_nums": top4_nums,
        "actual_top3_nums": actual_top3_nums,
        "top5_in_top3": sum(1 for nm in top5_names if act(nm) <= 3),
        "top4_in_top3": sum(1 for nm in top4_names if act(nm) <= 3),
    }


# ---- ROIシミュレーション --------------------------------------------------------

def sim_roi(races, label):
    if not races:
        print(f"  {label}: データなし"); return

    tan_inv = tan_col = 0
    fuku_inv = fuku_col = 0
    box5_inv = box5_col = 0
    box4_inv = box4_col = 0

    for r in races:
        rid = r["race_id"]

        # 単勝
        tan_inv += 100
        if r["p1_act"] == 1 and r["odds1"]:
            tan_col += r["odds1"] * 100

        # 複勝
        fuku_inv += 100
        if r["p1_act"] <= 3 and rid:
            hnums, amounts = get_payout(rid, '複勝')
            if hnums and amounts and r["p1_num"] in hnums:
                idx = hnums.index(r["p1_num"])
                if idx < len(amounts):
                    fuku_col += amounts[idx]

        # 5頭BOX（OP以上に適用 or 比較用に全体で計算）
        box5_inv += 1000
        if rid and len(r["top5_nums"]) >= 3:
            hnums, amounts = get_payout(rid, '3連複')
            if hnums and amounts:
                winning = frozenset(hnums[:3])
                if winning.issubset(set(r["top5_nums"])):
                    box5_col += amounts[0]

        # 4頭BOX（3勝クラスに適用 or 比較用）
        box4_inv += 400
        if rid and len(r["top4_nums"]) >= 3:
            hnums, amounts = get_payout(rid, '3連複')
            if hnums and amounts:
                winning = frozenset(hnums[:3])
                if winning.issubset(set(r["top4_nums"])):
                    box4_col += amounts[0]

    n = len(races)
    tan_roi  = tan_col  / tan_inv  * 100 if tan_inv  else 0
    fuku_roi = fuku_col / fuku_inv * 100 if fuku_inv else 0
    box5_roi = box5_col / box5_inv * 100 if box5_inv else 0
    box4_roi = box4_col / box4_inv * 100 if box4_inv else 0
    tan_pct  = sum(1 for r in races if r["p1_act"] == 1) / n * 100
    fuku_pct = sum(1 for r in races if r["p1_act"] <= 3) / n * 100
    box5_pct = sum(1 for r in races if r["top5_in_top3"] == 3) / n * 100
    box4_pct = sum(1 for r in races if r["top4_in_top3"] == 3) / n * 100

    print(f"\n  [{label}] n={n}R")
    print(f"  {'馬券':<16} {'ROI':>6}  {'命中率':>6}  {'投資合計':>10}  {'回収合計':>10}")
    print(f"  {'-'*58}")
    print(f"  {'単勝(100円/R)':<16} {tan_roi:>5.0f}%  {tan_pct:>5.1f}%  {tan_inv:>10,}円  {tan_col:>10,.0f}円")
    print(f"  {'複勝(100円/R)':<16} {fuku_roi:>5.0f}%  {fuku_pct:>5.1f}%  {fuku_inv:>10,}円  {fuku_col:>10,.0f}円")
    print(f"  {'5頭BOX(1000円/R)':<16} {box5_roi:>5.0f}%  {box5_pct:>5.1f}%  {box5_inv:>10,}円  {box5_col:>10,.0f}円")
    print(f"  {'4頭BOX(400円/R)':<16} {box4_roi:>5.0f}%  {box4_pct:>5.1f}%  {box4_inv:>10,}円  {box4_col:>10,.0f}円")
    return {"n": n, "tan_roi": tan_roi, "fuku_roi": fuku_roi, "box5_roi": box5_roi, "box4_roi": box4_roi}


# ---- メイン -------------------------------------------------------------------

if __name__ == "__main__":
    print("in-memory採点中...", flush=True)
    all_races, skipped = [], 0
    files = sorted(CACHE_RACE.glob("*.json"))
    total = len(files)

    for i, f in enumerate(files):
        if i % 100 == 0: print(f"  {i}/{total}件...", flush=True)
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        r = process(data)
        if r:
            all_races.append(r)
        else:
            skipped += 1

    print(f"\n採点完了: {len(all_races)}R (スキップ:{skipped}R)")

    # 見送りフラグを付ける
    buy_races  = []
    skip_races = []
    skip_breakdown = defaultdict(list)

    for r in all_races:
        skip, reason = is_skip(r["gap"], r["n"], r["cls_int"])
        if skip:
            skip_races.append(r)
            skip_breakdown[reason].append(r)
        else:
            buy_races.append(r)

    print(f"\n見送り: {len(skip_races)}R / 買い: {len(buy_races)}R")
    print("見送り内訳:")
    for reason, rs in sorted(skip_breakdown.items()):
        print(f"  {reason}: {len(rs)}R")

    print("\n" + "="*62)
    print("  ROI比較（実際の払い戻しデータ使用）")
    print("="*62)

    sim_roi(all_races,  "全体（見送り条件なし）")
    sim_roi(buy_races,  "買いサインのみ（見送り適用後）")

    print("\n── 見送り条件別の内訳 ──")
    sim_roi([r for r in all_races if r["cls_int"] == 2], "2勝クラス（見送り）")
    sim_roi([r for r in all_races if r["cls_int"] >= 5], "重賞（見送り）")
    sim_roi([r for r in all_races if r["n"] == 18],       "18頭フルゲート（見送り）")
    sim_roi([r for r in all_races if 3 <= r["gap"] < 5],  "乖離3〜5pt（見送り）")

    print("\n── 買いサイン内訳 ──")
    sim_roi([r for r in buy_races if r["cls_int"] == 3], "3勝クラス（→4頭BOX）")
    sim_roi([r for r in buy_races if r["cls_int"] == 4], "OP（→5頭BOX）")

    print()
