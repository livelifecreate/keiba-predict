"""
スコア差bin × BOX頭数の三連複ROI分析
批評家指摘への回答: 「スコア差0〜1ptの見送りはROI・的中率で判定すべき」

分析内容:
  1. スコア差binごとのN頭BOX ROI・的中率・中央値配当
  2. 現行見送り（乖離3〜5pt）× 追加見送り（スコア差0〜1pt）の機会損失定量化

対象: 2勝クラス以上・キャッシュ済みレース（外部アクセスなし）
"""

import sys, re, json, statistics
from pathlib import Path
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from jra_scraper import HorseEntry, RaceInfo
from scorer_turf import score_all as score_turf
from scorer_dart import score_all as score_dart
from cache_store import cache_get, cache_get_before

BASE        = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE  = BASE / 'cache' / 'race_result'
NETKEIBA_TR = BASE / 'cache' / 'netkeiba_training'

TARGET_CLASSES = {"2勝クラス", "3勝クラス", "OP", "重賞"}

# スコア差BINの定義: (下限含む, 上限含まない, ラベル)
BINS = [
    (0.0, 1.0, "0〜1pt"),
    (1.0, 2.0, "1〜2pt"),
    (2.0, 3.0, "2〜3pt"),
    (3.0, 5.0, "3〜5pt"),
    (5.0, 99.0, "5pt以上"),
]

# 現行見送り対象(乖離3〜5pt)
CURRENT_SKIP_BIN = "3〜5pt"


# ---- 払戻データ取得 -----------------------------------------------------------

def parse_amounts(s: str) -> list[int]:
    return [int(m.replace(',', '')) for m in re.findall(r'[\d,]+(?=円)', s)]

def parse_horse_nums_pn(s: str, count: int) -> list[int]:
    """馬番パース。countを渡してgreedy誤読を防ぐ"""
    nums, i = [], 0
    while i < len(s) and len(nums) < count:
        if i + 2 <= len(s):
            two = int(s[i:i+2])
            if two <= 18:
                nums.append(two); i += 2
                continue
        nums.append(int(s[i:i+1])); i += 1
    return nums

def get_trio_payout(race_id: str) -> tuple[frozenset | None, int]:
    p = cache_get('payouts', race_id)
    if not p:
        return None, 0
    v = p.get('3連複', {})
    raw = v.get('raw', [])
    if len(raw) < 3:
        return None, 0
    hnums   = parse_horse_nums_pn(raw[1], 3) if raw[1] else []
    amounts = parse_amounts(raw[2]) if raw[2] else []
    if len(hnums) < 3 or not amounts:
        return None, 0
    return frozenset(hnums[:3]), amounts[0]


# ---- 調教データ取得 -----------------------------------------------------------

def _load_training(race_id: str) -> dict | None:
    p = NETKEIBA_TR / f"{race_id}.json"
    if not p.exists():
        return None
    try:
        from netkeiba_scraper import TrainingData as TD
        raw = json.loads(p.read_text())
        if not raw:
            return None
        return {name: TD(horse_name=name, rank=v["rank"], comment=v.get("comment",""), score=v["score"])
                for name, v in raw.items()}
    except Exception:
        return None


# ---- レース採点 -----------------------------------------------------------

def process_race(data: dict) -> dict | None:
    """1レースを採点してスコア差・払戻など必要情報を返す"""
    rc = data.get("race_class")
    if rc not in TARGET_CLASSES:
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
        surface=data["surface"], conditions=data.get("conditions",""),
        start_time=data.get("start_time",""), url="", race_num=data["race_num_int"],
    )

    entries, rank_map, num_map = [], {}, {}
    horse_ids = {}
    for e in data["entries"]:
        hid = e.get("horse_id","")
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
        rank_map[e["horse_name"]] = e.get("rank", 99)
        num_map[e["horse_name"]]  = int(e["horse_num"]) if str(e["horse_num"]).isdigit() else 0
        if hid:
            horse_ids[e["horse_name"]] = hid

    if len(entries) < 5:
        return None

    training_data = _load_training(data.get("race_id",""))
    fn = score_dart if data["surface"] == "ダ" else score_turf
    tc = data.get("track_condition","")
    try:
        scored = fn(entries, race_info, training_data=training_data,
                    track_condition=tc, horse_ids=horse_ids)
    except Exception:
        return None
    scored.sort(key=lambda x: x[1].total, reverse=True)

    if len(scored) < 2:
        return None

    gap = scored[0][1].total - scored[1][1].total  # スコア差(1位 - 2位)
    n_horses = len(entries)

    # 予想順位→馬番 マッピング
    pred_nums = []
    for entry, bd in scored:
        hn = num_map.get(entry.horse_name, 0)
        if hn > 0:
            pred_nums.append(hn)

    # 実際の1〜3着 馬番
    actual_top3_nums = frozenset(
        num_map[h] for h, r in rank_map.items()
        if r <= 3 and num_map.get(h, 0) > 0
    )
    if len(actual_top3_nums) < 3:
        return None  # 3着以内が3頭揃わない場合はスキップ

    # 3連複払戻
    race_id = data.get("race_id","")
    trio_win, trio_pay = get_trio_payout(race_id)

    return {
        "race_id":        race_id,
        "date":           date_str,
        "race_name":      data["race_name"],
        "race_class":     rc,
        "surface":        data["surface"],
        "n_horses":       n_horses,
        "gap":            round(gap, 2),
        "pred_nums":      pred_nums,   # 予想順位順の馬番リスト
        "actual_top3":    actual_top3_nums,
        "trio_win":       trio_win,    # 実際の3連複winning frozenset (馬番)
        "trio_pay":       trio_pay,
    }


# ---- BOX ROI 集計 -----------------------------------------------------------

def box_roi(races: list[dict], n_box: int) -> dict:
    """N頭BOXのROI/的中率/中央値配当を集計"""
    invest = 0
    collect = 0
    hits = 0
    payouts_on_hit = []
    n_races = 0

    n_combs = len(list(combinations(range(n_box), 3)))  # C(n,3)点数

    for r in races:
        trio_win = r["trio_win"]
        trio_pay = r["trio_pay"]
        if trio_win is None or trio_pay == 0:
            continue

        pred = r["pred_nums"]
        if len(pred) < n_box:
            continue  # 予想馬番が足りない場合はスキップ

        box_set = set(pred[:n_box])
        cost = n_combs * 100
        invest  += cost
        n_races += 1

        if trio_win <= box_set:   # trio_win(3頭) が全部 box_set 内に含まれるか
            collect += trio_pay
            hits    += 1
            payouts_on_hit.append(trio_pay)

    if n_races == 0:
        return {"n": 0, "hit_rate": 0, "roi": 0, "median_pay": 0}

    return {
        "n":          n_races,
        "hit_rate":   hits / n_races * 100,
        "roi":        collect / invest * 100 if invest > 0 else 0,
        "median_pay": statistics.median(payouts_on_hit) if payouts_on_hit else 0,
    }


# ---- メイン ------------------------------------------------------------------

def main():
    print("全キャッシュ済み対象レースを採点中...")

    all_races = []
    skipped = 0
    files = sorted(CACHE_RACE.glob("*.json"))
    total = len(files)

    for i, f in enumerate(files):
        if i % 100 == 0:
            print(f"  {i}/{total}件... (有効: {len(all_races)}, スキップ: {skipped})", flush=True)
        try:
            data = json.loads(f.read_text())
        except Exception:
            skipped += 1
            continue

        result = process_race(data)
        if result is None:
            skipped += 1
        else:
            all_races.append(result)

    print(f"\n採点完了: 有効 {len(all_races)}レース / スキップ {skipped}件")

    if not all_races:
        print("有効レースがありません")
        return

    # スコア差binに分類
    binned: dict[str, list] = defaultdict(list)
    for r in all_races:
        g = r["gap"]
        for lo, hi, label in BINS:
            if lo <= g < hi:
                binned[label].append(r)
                break

    # ---- 出力1: スコア差bin × BOX頭数のROI表 --------------------------------
    print("\n" + "="*80)
    print("【スコア差bin × 三連複BOX ROI表】")
    print("="*80)
    print(f"{'binラベル':<12} {'件数':>5}  " +
          "  ".join([f"{'4頭BOX(4点)':>14}", f"{'5頭BOX(10点)':>14}"]))
    print("-"*80)

    bin_order = [label for _, _, label in BINS]
    total_races = len(all_races)

    results_by_bin = {}
    for label in bin_order:
        races_in_bin = binned.get(label, [])
        r4 = box_roi(races_in_bin, 4)
        r5 = box_roi(races_in_bin, 5)
        results_by_bin[label] = {"races": races_in_bin, "r4": r4, "r5": r5}

        n = len(races_in_bin)
        pct = n / total_races * 100 if total_races > 0 else 0
        skip_mark = " ※現行見送り" if label == CURRENT_SKIP_BIN else ""
        print(f"{label:<12} {n:>5}({pct:4.1f}%)  "
              f"  {r4['hit_rate']:5.1f}% ROI:{r4['roi']:6.1f}% 中央値:{r4['median_pay']:6,}円"
              f"  {r5['hit_rate']:5.1f}% ROI:{r5['roi']:6.1f}% 中央値:{r5['median_pay']:6,}円"
              f"{skip_mark}")

    # 全体合計行
    r4_all = box_roi(all_races, 4)
    r5_all = box_roi(all_races, 5)
    print("-"*80)
    print(f"{'全体合計':<12} {total_races:>5}(100%)  "
          f"  {r4_all['hit_rate']:5.1f}% ROI:{r4_all['roi']:6.1f}% 中央値:{r4_all['median_pay']:6,}円"
          f"  {r5_all['hit_rate']:5.1f}% ROI:{r5_all['roi']:6.1f}% 中央値:{r5_all['median_pay']:6,}円")

    # ---- 出力2: 機会損失定量化 ------------------------------------------------
    print("\n" + "="*80)
    print("【見送り拡張シナリオ別 機会損失定量化】")
    print("="*80)

    # シナリオ定義
    current_skip = {"3〜5pt"}                   # 現行見送り
    expanded_skip = {"3〜5pt", "0〜1pt"}         # 追加見送り案

    def filter_races(races: list, skip_bins: set) -> list:
        out = []
        for r in races:
            g = r["gap"]
            in_skip = False
            for lo, hi, label in BINS:
                if lo <= g < hi and label in skip_bins:
                    in_skip = True
                    break
            if not in_skip:
                out.append(r)
        return out

    scenarios = [
        ("A: 全レース買い（見送りなし）", set()),
        ("B: 現行見送り（3〜5pt除外）",   current_skip),
        ("C: 拡張見送り（3〜5pt + 0〜1pt除外）", expanded_skip),
    ]

    print(f"\n{'シナリオ':<42} {'レース数':>8} {'全体比':>7}  "
          f"{'4頭BOX的中率':>12} {'4頭BOX ROI':>10}  "
          f"{'5頭BOX的中率':>12} {'5頭BOX ROI':>10}")
    print("-"*120)

    scenario_results = {}
    for label, skip_bins in scenarios:
        filtered = filter_races(all_races, skip_bins)
        n = len(filtered)
        pct = n / total_races * 100 if total_races > 0 else 0
        r4 = box_roi(filtered, 4)
        r5 = box_roi(filtered, 5)
        scenario_results[label] = {"n": n, "pct": pct, "r4": r4, "r5": r5, "filtered": filtered}
        print(f"{label:<42} {n:>8} ({pct:4.1f}%)  "
              f"{r4['hit_rate']:>11.1f}% {r4['roi']:>9.1f}%  "
              f"{r5['hit_rate']:>11.1f}% {r5['roi']:>9.1f}%")

    # ---- 出力3: 0〜1pt bin のクラス別内訳 ------------------------------------
    print("\n" + "="*80)
    print("【スコア差 0〜1pt の内訳（クラス別）】")
    print("="*80)
    gap01_races = binned.get("0〜1pt", [])
    by_class = defaultdict(list)
    for r in gap01_races:
        by_class[r["race_class"]].append(r)

    print(f"{'クラス':<12} {'件数':>6}  "
          f"{'4頭BOX的中率':>12} {'4頭BOX ROI':>10}  "
          f"{'5頭BOX的中率':>12} {'5頭BOX ROI':>10}")
    print("-"*80)
    for cls in ["2勝クラス", "3勝クラス", "OP", "重賞"]:
        races_cls = by_class.get(cls, [])
        if not races_cls:
            continue
        r4c = box_roi(races_cls, 4)
        r5c = box_roi(races_cls, 5)
        print(f"{cls:<12} {len(races_cls):>6}  "
              f"{r4c['hit_rate']:>11.1f}% {r4c['roi']:>9.1f}%  "
              f"{r5c['hit_rate']:>11.1f}% {r5c['roi']:>9.1f}%")

    # ---- 出力4: 判定サマリー -------------------------------------------------
    print("\n" + "="*80)
    print("【判定サマリー】")
    print("="*80)
    gap01 = results_by_bin.get("0〜1pt", {})
    r4_01 = gap01.get("r4", {})
    r5_01 = gap01.get("r5", {})
    r4_35 = results_by_bin.get("3〜5pt", {}).get("r4", {})
    r5_35 = results_by_bin.get("3〜5pt", {}).get("r5", {})
    r4_5p = results_by_bin.get("5pt以上", {}).get("r4", {})
    r5_5p = results_by_bin.get("5pt以上", {}).get("r5", {})

    gap01_n = len(binned.get("0〜1pt", []))
    gap01_pct = gap01_n / total_races * 100 if total_races > 0 else 0

    print(f"\nスコア差0〜1pt のレース数: {gap01_n}件 ({gap01_pct:.1f}%)")
    print(f"  4頭BOX ROI: {r4_01.get('roi',0):.1f}%  的中率: {r4_01.get('hit_rate',0):.1f}%")
    print(f"  5頭BOX ROI: {r5_01.get('roi',0):.1f}%  的中率: {r5_01.get('hit_rate',0):.1f}%")
    print()
    print(f"現行見送り 3〜5pt のROI（比較用）:")
    print(f"  4頭BOX ROI: {r4_35.get('roi',0):.1f}%  5頭BOX ROI: {r5_35.get('roi',0):.1f}%")
    print()
    print(f"最高ROIのbin (5pt以上):")
    print(f"  4頭BOX ROI: {r4_5p.get('roi',0):.1f}%  5頭BOX ROI: {r5_5p.get('roi',0):.1f}%")
    print()

    # 0〜1pt の見送り是非を判定
    roi_threshold = 100.0  # 回収率100%をラインとする
    r4_roi_01 = r4_01.get("roi", 0)
    r5_roi_01 = r5_01.get("roi", 0)
    better_than_threshold = r4_roi_01 >= roi_threshold or r5_roi_01 >= roi_threshold

    # シナリオC(拡張見送り)がBより良いか
    sc_b = scenario_results.get("B: 現行見送り（3〜5pt除外）", {})
    sc_c = scenario_results.get("C: 拡張見送り（3〜5pt + 0〜1pt除外）", {})
    r4_c_roi = sc_c.get("r4", {}).get("roi", 0)
    r4_b_roi = sc_b.get("r4", {}).get("roi", 0)
    r5_c_roi = sc_c.get("r5", {}).get("roi", 0)
    r5_b_roi = sc_b.get("r5", {}).get("roi", 0)

    print("--- 結論 ---")
    print(f"スコア差0〜1pt を「見送るべき」か:")
    if not better_than_threshold:
        print(f"  → 【見送り根拠あり】4頭BOX ROI={r4_roi_01:.1f}% / 5頭BOX ROI={r5_roi_01:.1f}% (いずれも100%未満)")
    else:
        print(f"  → 【見送り根拠なし】4頭BOX ROI={r4_roi_01:.1f}% / 5頭BOX ROI={r5_roi_01:.1f}% (少なくとも一方が100%以上)")

    print()
    print(f"拡張見送り(シナリオC)が現行見送り(シナリオB)より改善するか:")
    r4_improved = r4_c_roi > r4_b_roi
    r5_improved = r5_c_roi > r5_b_roi
    print(f"  4頭BOX: B={r4_b_roi:.1f}% → C={r4_c_roi:.1f}%  ({'改善' if r4_improved else '悪化'})")
    print(f"  5頭BOX: B={r5_b_roi:.1f}% → C={r5_c_roi:.1f}%  ({'改善' if r5_improved else '悪化'})")

    sc_b_n = sc_b.get("n", 0)
    sc_c_n = sc_c.get("n", 0)
    skipped_by_expand = sc_b_n - sc_c_n
    print(f"\n  拡張見送りで追加除外されるレース数: {skipped_by_expand}件 "
          f"({skipped_by_expand/total_races*100:.1f}%)")
    print(f"  (全体{total_races}件中 {sc_c_n}件が「買えるレース」として残る)")

    print("\n" + "="*80)
    print("分析完了")


if __name__ == "__main__":
    main()
