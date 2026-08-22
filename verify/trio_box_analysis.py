"""
3勝クラス×芝 三連複BOX分析
N=3,4,5,6頭BOXのROI・的中率・払戻分布を詳細検証し、赤字主因を特定する。
2勝クラス×芝 との比較も行う。

実行: python3 verify/trio_box_analysis.py
"""
import sys, re, json
from pathlib import Path
from itertools import combinations
from collections import defaultdict
import statistics

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from jra_scraper import HorseEntry, RaceInfo
from scorer_turf import score_all as score_turf
from cache_store import cache_get, cache_get_before

BASE       = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE = BASE / 'cache' / 'race_result'
NETKEIBA_TRAINING_DIR = BASE / 'cache' / 'netkeiba_training'

TARGET_CLASSES = {"2勝クラス", "3勝クラス"}


# ---- 三連複払い戻し取得 -------------------------------------------------------

def _pn_for_count(s: str, count: int) -> list[int]:
    """
    競馬払い戻しの馬番文字列を正確にパース。
    2桁→1桁の優先マッチ（左から最長優先）。count 頭分取得。
    """
    nums, i = [], 0
    while i < len(s) and len(nums) < count:
        if i + 2 <= len(s):
            two = int(s[i:i+2])
            if 1 <= two <= 18:
                nums.append(two)
                i += 2
                continue
        one = int(s[i:i+1])
        nums.append(one)
        i += 1
    return nums


def get_trio_payout(race_id: str) -> tuple:
    """(winning_set: frozenset, payout: int) or (None, 0)"""
    p = cache_get('payouts', race_id)
    if not p:
        return None, 0
    v = p.get('3連複', {})
    raw = v.get('raw', [])
    if len(raw) < 3:
        return None, 0
    try:
        hnums   = _pn_for_count(raw[1], 3) if raw[1] else []
        amounts = [int(m.replace(',', '')) for m in re.findall(r'[\d,]+(?=円)', raw[2])]
    except Exception:
        return None, 0
    if len(hnums) < 3 or not amounts:
        return None, 0
    return frozenset(hnums[:3]), amounts[0]


# ---- 調教データ取得 ----------------------------------------------------------

def _fetch_training_cached(race_id: str) -> dict | None:
    p = NETKEIBA_TRAINING_DIR / f"{race_id}.json"
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


# ---- レース採点 + BOX判定 ----------------------------------------------------

def process_race(data: dict) -> dict | None:
    """1レース分を採点し、BOX的中情報を返す。戻り値は dict or None"""
    rc = data.get("race_class")
    if rc not in TARGET_CLASSES:
        return None
    if data.get("surface") != "芝":
        return None
    if len(data.get("entries", [])) < 5:
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
        start_time=data.get("start_time", ""), url="", race_num=data["race_num_int"],
    )

    entries, rank_map, odds_map = [], {}, {}
    horse_ids = {}
    for e in data["entries"]:
        hid = e.get("horse_id", "")
        recent = cache_get_before("horse_history", hid, cutoff) or []
        sire   = cache_get("sire", hid) or ""
        he = HorseEntry(
            frame_number=e["frame"], horse_number=e["horse_num"],
            horse_name=e["horse_name"], record="", prize_money="",
            owner="", trainer="", age_sex=e.get("age_sex", ""),
            weight_carried=e.get("weight_carried", ""), jockey=e.get("jockey", ""),
            recent_races=recent, sire=sire,
        )
        entries.append(he)
        rank_map[e["horse_name"]] = e.get("rank", 99)
        odds_map[e["horse_name"]] = e.get("odds", 0.0)
        if hid:
            horse_ids[e["horse_name"]] = hid

    training_data = _fetch_training_cached(data.get("race_id", ""))
    tc = data.get("track_condition", "")
    scored = score_turf(entries, race_info, training_data=training_data,
                        track_condition=tc, horse_ids=horse_ids)
    scored.sort(key=lambda x: x[1].total, reverse=True)

    # 予想順位順に馬番リスト
    pred_horse_nums = [int(e.horse_number) for e, _ in scored]

    # 実際の3着内馬番セット
    actual_top3 = frozenset(
        int(e["horse_num"]) for e in data["entries"] if e.get("rank", 99) <= 3
    )
    if len(actual_top3) < 3:
        return None  # 同着等で3頭取れない場合はスキップ

    return {
        "race_id": data.get("race_id", ""),
        "race_class": rc,
        "date": date_str,
        "venue": data["venue"],
        "race_name": data["race_name"],
        "pred_horse_nums": pred_horse_nums,
        "actual_top3": actual_top3,
        "entry_count": len(entries),
    }


# ---- BOX ROI 計算 -----------------------------------------------------------

def analyze_box(races: list[dict], N: int) -> dict:
    """
    上位N頭のBOXについて:
    - 総レース数、的中数、的中率
    - ROI（投資額 = C(N,3)×100円）
    - 払戻の最低・中央値・最高
    - 最高配当除いたROI
    """
    pts = len(list(combinations(range(N), 3)))  # C(N,3)
    invest_per_race = pts * 100

    total_races  = 0
    hit_count    = 0
    payouts_list = []

    for r in races:
        nums = r["pred_horse_nums"]
        if len(nums) < N:
            continue  # 出走頭数がN未満はスキップ
        total_races += 1

        top_n = frozenset(nums[:N])
        if r["actual_top3"].issubset(top_n):
            # 的中：払い戻し取得
            win_set, payout = get_trio_payout(r["race_id"])
            if payout > 0:
                hit_count += 1
                payouts_list.append(payout)
            # payoutが0（キャッシュなし）でも的中としてカウントするが
            # ROI計算には使えないのでpayout>0のもののみ使用
        # 投資はpayout有無に関わらずカウント

    total_invest = total_races * invest_per_race
    total_return = sum(payouts_list)

    roi = (total_return / total_invest * 100) if total_invest > 0 else 0.0
    hit_rate = (hit_count / total_races * 100) if total_races > 0 else 0.0

    if payouts_list:
        p_min    = min(payouts_list)
        p_median = statistics.median(payouts_list)
        p_max    = max(payouts_list)
        # 最高配当除いたROI
        ex_max_return = total_return - p_max
        ex_max_roi    = (ex_max_return / total_invest * 100) if total_invest > 0 else 0.0
    else:
        p_min = p_median = p_max = 0
        ex_max_roi = 0.0

    return {
        "N": N,
        "pts": pts,
        "total_races": total_races,
        "hit_count": hit_count,
        "hit_rate": hit_rate,
        "total_invest": total_invest,
        "total_return": total_return,
        "roi": roi,
        "p_min": p_min,
        "p_median": p_median,
        "p_max": p_max,
        "ex_max_roi": ex_max_roi,
        "payouts_list": payouts_list,
    }


# ---- メイン ------------------------------------------------------------------

def main():
    print("キャッシュ全レースを読み込み中...")
    race_files = sorted(CACHE_RACE.glob("*.json"))
    total = len(race_files)

    races_3sho = []  # 3勝クラス×芝
    races_2sho = []  # 2勝クラス×芝

    for i, f in enumerate(race_files):
        if i % 200 == 0:
            print(f"  {i}/{total} 処理中...", flush=True)
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        r = process_race(data)
        if r is None:
            continue
        if r["race_class"] == "3勝クラス":
            races_3sho.append(r)
        elif r["race_class"] == "2勝クラス":
            races_2sho.append(r)

    print(f"\n3勝クラス×芝: {len(races_3sho)} レース")
    print(f"2勝クラス×芝: {len(races_2sho)} レース")

    # ---- 3勝クラス×芝 N=3〜6 テーブル ----------------------------------------
    print("\n" + "="*72)
    print("【3勝クラス×芝】三連複N頭BOX分析")
    print("="*72)
    print(f"{'N':>3} {'点数':>4} {'n':>5} {'的中':>5} {'的中率':>7} "
          f"{'ROI':>7} {'払戻最低':>9} {'払戻中央':>9} {'払戻最高':>9} {'最高除ROI':>10}")
    print("-"*72)

    results_3sho = {}
    for N in [3, 4, 5, 6]:
        res = analyze_box(races_3sho, N)
        results_3sho[N] = res
        print(f"{N:>3} {res['pts']:>4} {res['total_races']:>5} {res['hit_count']:>5} "
              f"{res['hit_rate']:>6.1f}% "
              f"{res['roi']:>6.1f}% "
              f"{res['p_min']:>9,} "
              f"{int(res['p_median']):>9,} "
              f"{res['p_max']:>9,} "
              f"{res['ex_max_roi']:>9.1f}%")

    # ---- 2勝クラス×芝 N=3〜6 テーブル ----------------------------------------
    print("\n" + "="*72)
    print("【2勝クラス×芝】三連複N頭BOX分析")
    print("="*72)
    print(f"{'N':>3} {'点数':>4} {'n':>5} {'的中':>5} {'的中率':>7} "
          f"{'ROI':>7} {'払戻最低':>9} {'払戻中央':>9} {'払戻最高':>9} {'最高除ROI':>10}")
    print("-"*72)

    results_2sho = {}
    for N in [3, 4, 5, 6]:
        res = analyze_box(races_2sho, N)
        results_2sho[N] = res
        print(f"{N:>3} {res['pts']:>4} {res['total_races']:>5} {res['hit_count']:>5} "
              f"{res['hit_rate']:>6.1f}% "
              f"{res['roi']:>6.1f}% "
              f"{res['p_min']:>9,} "
              f"{int(res['p_median']):>9,} "
              f"{res['p_max']:>9,} "
              f"{res['ex_max_roi']:>9.1f}%")

    # ---- 赤字主因分析 ----------------------------------------------------------
    print("\n" + "="*72)
    print("【赤字主因分析】3勝クラス×芝 vs 2勝クラス×芝 比較（N=5基準）")
    print("="*72)

    def analyze_cause(label: str, races: list[dict], res5: dict):
        print(f"\n--- {label} ---")
        n     = res5["total_races"]
        hrate = res5["hit_rate"]
        roi   = res5["roi"]
        plist = res5["payouts_list"]

        # 損益分岐点払戻（ROI=100%になるために必要な平均払戻）
        invest_per = res5["pts"] * 100
        breakeven  = invest_per * (n / max(res5["hit_count"], 1)) if res5["hit_count"] > 0 else float('inf')

        print(f"  総レース数: {n}")
        print(f"  的中率: {hrate:.1f}%")
        print(f"  ROI: {roi:.1f}%")
        print(f"  1点単位投資: {invest_per}円")
        if plist:
            avg_payout = sum(plist) / len(plist)
            print(f"  平均払戻（的中時）: {avg_payout:,.0f}円")
            print(f"  損益分岐点払戻（ROI100%になる払戻）: {breakeven:,.0f}円")
            pct_above = sum(1 for p in plist if p >= breakeven) / len(plist) * 100
            print(f"  損益分岐点以上の的中割合: {pct_above:.1f}%")

            # 払戻分布
            buckets = [
                (0,    1000,  "〜1000"),
                (1000, 2000,  "1000〜2000"),
                (2000, 5000,  "2000〜5000"),
                (5000, 10000, "5000〜10000"),
                (10000, 50000,"10000〜50000"),
                (50000, 10**9,"50000以上"),
            ]
            print("  払戻分布:")
            for lo, hi, label_b in buckets:
                cnt = sum(1 for p in plist if lo <= p < hi)
                if cnt:
                    print(f"    {label_b:>15}円: {cnt}件 ({100*cnt/len(plist):.1f}%)")

    analyze_cause("3勝クラス×芝", races_3sho, results_3sho[5])
    analyze_cause("2勝クラス×芝", races_2sho, results_2sho[5])

    # ---- 比較サマリー ----------------------------------------------------------
    print("\n" + "="*72)
    print("【比較サマリー】3勝 vs 2勝（N=5）")
    print("="*72)
    r3 = results_3sho[5]
    r2 = results_2sho[5]
    print(f"{'指標':<20} {'3勝クラス×芝':>15} {'2勝クラス×芝':>15}")
    print("-"*52)
    print(f"{'レース数 n':<20} {r3['total_races']:>15} {r2['total_races']:>15}")
    print(f"{'的中数':<20} {r3['hit_count']:>15} {r2['hit_count']:>15}")
    print(f"{'的中率 (%)':<20} {r3['hit_rate']:>14.1f}% {r2['hit_rate']:>14.1f}%")
    print(f"{'ROI (%)':<20} {r3['roi']:>14.1f}% {r2['roi']:>14.1f}%")
    if r3['payouts_list']:
        print(f"{'払戻中央値 (円)':<20} {int(r3['p_median']):>15,} {int(r2['p_median']):>15,}")
        print(f"{'払戻最高 (円)':<20} {r3['p_max']:>15,} {r2['p_max']:>15,}")
        avg3 = sum(r3['payouts_list'])/len(r3['payouts_list']) if r3['payouts_list'] else 0
        avg2 = sum(r2['payouts_list'])/len(r2['payouts_list']) if r2['payouts_list'] else 0
        print(f"{'払戻平均 (円)':<20} {avg3:>15,.0f} {avg2:>15,.0f}")

    print("\n赤字の主因判定:")
    if r3['total_races'] < 20:
        print("  ⚠ サンプル数が20件未満 → 統計的判定不可（誤差範囲）")
    else:
        # 的中率の比較（2勝クラスとの差）
        hr_diff = r3['hit_rate'] - r2['hit_rate']
        # 払戻中央値の比較
        med_diff = (r3['p_median'] - r2['p_median']) if r3['payouts_list'] and r2['payouts_list'] else 0

        roi_3 = r3['roi']
        roi_2 = r2['roi']

        print(f"  3勝ROI={roi_3:.1f}% vs 2勝ROI={roi_2:.1f}%")
        print(f"  的中率差: {hr_diff:+.1f}pt（3勝 - 2勝）")
        print(f"  払戻中央値差: {int(med_diff):+,}円（3勝 - 2勝）")

        if roi_3 < 100:
            if r3['hit_rate'] < 20:
                print("  → 主因: 【的中率の低さ】（20%未満）")
            elif r3['p_median'] and r3['p_median'] < (r3['pts'] * 100 * r3['total_races'] / max(r3['hit_count'], 1)):
                print("  → 主因: 【配当の低さ】（損益分岐点払戻を下回る中央値）")
            else:
                print("  → 主因: 的中率・配当の両方が不足（複合要因）")


if __name__ == "__main__":
    main()
