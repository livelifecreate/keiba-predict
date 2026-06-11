"""
1勝クラス以下（1勝・未勝利・新馬）の回収率検証スクリプト

フロー:
  1. 1〜5月全土日の1勝クラス/未勝利/新馬レースを取得
  2. 採点・買いサインフィルター適用
  3. 三連複払戻を取得してROI計算
  4. 2勝クラス以上の結果と比較

使い方:
  python3 verify_1sho_roi.py                      # 1勝クラスのみ（デフォルト）
  python3 verify_1sho_roi.py --classes 未勝利      # 未勝利のみ
  python3 verify_1sho_roi.py --classes 1勝クラス 未勝利 新馬  # 全下位クラス
  python3 verify_1sho_roi.py --analyze-only        # キャッシュ再利用（再取得なし）
  python3 verify_1sho_roi.py --test                # 最初の3レースのみテスト
"""
import csv, json, re, sys, time, random, datetime, argparse
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

import requests
from bs4 import BeautifulSoup
from netkeiba_race_scraper import get_race_list, HEADERS
from scorer_turf import score_all as score_turf, parse_race_class
from jra_scraper import HorseEntry, RaceInfo

BASE_DIR = "/Users/du/Documents/競馬予想システム"
CACHE_JSON = f"{BASE_DIR}/data/trio_cache_1sho.json"

# 1〜5月の全土日
ALL_DATES = [
    # 1月
    datetime.date(2026, 1,  4), datetime.date(2026, 1,  5),
    datetime.date(2026, 1, 10), datetime.date(2026, 1, 11),
    datetime.date(2026, 1, 12),  # 成人の日
    datetime.date(2026, 1, 17), datetime.date(2026, 1, 18),
    datetime.date(2026, 1, 24), datetime.date(2026, 1, 25),
    datetime.date(2026, 1, 31),
    # 2月
    datetime.date(2026, 2,  1), datetime.date(2026, 2,  7),
    datetime.date(2026, 2,  8), datetime.date(2026, 2, 14),
    datetime.date(2026, 2, 15), datetime.date(2026, 2, 21),
    datetime.date(2026, 2, 22), datetime.date(2026, 2, 28),
    # 3月
    datetime.date(2026, 3,  1), datetime.date(2026, 3,  7),
    datetime.date(2026, 3,  8), datetime.date(2026, 3, 14),
    datetime.date(2026, 3, 15), datetime.date(2026, 3, 21),
    datetime.date(2026, 3, 22), datetime.date(2026, 3, 28),
    datetime.date(2026, 3, 29),
    # 4月
    datetime.date(2026, 4,  4), datetime.date(2026, 4,  5),
    datetime.date(2026, 4, 11), datetime.date(2026, 4, 12),
    datetime.date(2026, 4, 18), datetime.date(2026, 4, 19),
    datetime.date(2026, 4, 25), datetime.date(2026, 4, 26),
    datetime.date(2026, 4, 27),
    # 5月（5/3-5は連休中でJRAも開催）
    datetime.date(2026, 5,  2), datetime.date(2026, 5,  3),
    datetime.date(2026, 5,  4), datetime.date(2026, 5,  5),
    datetime.date(2026, 5,  9), datetime.date(2026, 5, 10),
    datetime.date(2026, 5, 16), datetime.date(2026, 5, 17),
    datetime.date(2026, 5, 23), datetime.date(2026, 5, 24),
    datetime.date(2026, 5, 30), datetime.date(2026, 5, 31),
]

def _sleep():
    time.sleep(random.uniform(1.2, 2.0))


# ── スコアリング ──────────────────────────────────────────────────────

def fetch_race_entries(race_id: str):
    """出走表取得（netkeiba）"""
    from netkeiba_race_scraper import get_entry_list_netkeiba
    return get_entry_list_netkeiba(race_id)


# ── 三連複払戻取得 ─────────────────────────────────────────────────────

def fetch_trio_payout(race_id: str):
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    _sleep()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception as e:
        return None, None, {}

    # 三連複払戻
    trio_nums, trio_pay = None, None
    for tbl in soup.find_all("table"):
        row = tbl.find("tr", class_="Fuku3")
        if not row:
            continue
        result_td = row.find("td", class_="Result")
        payout_td = row.find("td", class_="Payout")
        if not result_td or not payout_td:
            continue
        nums = [s.get_text(strip=True) for s in result_td.find_all("span")
                if s.get_text(strip=True)]
        pay_str = payout_td.get_text(strip=True).replace("円", "").replace(",", "")
        try:
            trio_nums = tuple(nums)
            trio_pay = int(pay_str)
        except ValueError:
            pass
        break

    # 馬名→馬番マップ
    name2num = {}
    tables = soup.find_all("table")
    if tables:
        for tr in tables[0].find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) >= 4 and cells[2] and cells[3]:
                name2num[cells[3]] = cells[2]

    return trio_nums, trio_pay, name2num


# ── 買いサイン判定 ─────────────────────────────────────────────────────

def calc_buy_sign(sorted_results, odds_map, n):
    if len(sorted_results) < 2:
        return "neutral"
    top_entry, top_d = sorted_results[0]
    sec_entry, sec_d = sorted_results[1]
    gap = top_d.total - sec_d.total
    odds1 = odds_map.get(top_entry.horse_name, 0)
    has_sc = top_d.same_course >= 4

    if n == 18:
        return "skip"
    if 3 <= gap < 5:
        return "skip"
    if has_sc:
        return "skip"
    if odds1 and 8 <= odds1 < 15:
        return "skip"

    if odds1:
        if gap >= 5 and n <= 13 and 2 <= odds1 < 8:
            return "7pt"
    else:
        if gap >= 5 and n <= 13:
            return "7pt"

    return "formb"


def form_b_combos(sorted_results):
    nums = [e.horse_number for e, _ in sorted_results]
    if len(nums) < 3:
        return set()
    ax0, ax1 = nums[0], nums[1]
    result = set()
    for b in nums[2:9]:
        if b != ax0 and b != ax1:
            result.add(tuple(sorted([ax0, ax1, b], key=lambda x: int(x))))
    return result


def sevens_combos(sorted_results):
    nums = [e.horse_number for e, _ in sorted_results]
    if len(nums) < 3:
        return set()
    ax0, ax1 = nums[0], nums[1]
    return {tuple(sorted([ax0, ax1, b], key=lambda x: int(x)))
            for b in nums[2:9]}


# ── メイン処理 ────────────────────────────────────────────────────────

def run_verify(target_classes, dates, test=False, analyze_only=False):
    cache_path = CACHE_JSON

    if analyze_only:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"キャッシュ読み込み: {len(cache)}レース")
        analyze(cache)
        return

    from netkeiba_race_scraper import fetch_odds

    print(f"対象クラス: {target_classes}")
    print(f"対象日数: {len(dates)}日")
    print()

    cache = []
    # 既存キャッシュ読み込み（中断再開用）
    existing_keys = set()
    try:
        with open(cache_path, encoding="utf-8") as f:
            cache = json.load(f)
        existing_keys = {(e["date"], e["venue"], e["race_name"]) for e in cache}
        print(f"既存キャッシュ: {len(cache)}レース（スキップ済み）")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    race_count = 0
    class_label_map = {0: "新馬", 1: "1勝クラス", -1: "未勝利"}

    for d in dates:
        print(f"\n──── {d} ────")
        try:
            races = get_race_list([d])
        except Exception as e:
            print(f"  レース一覧取得失敗: {e}")
            continue

        for race_meta in races:
            race_id = race_meta["race_id"]
            label = race_meta.get("label", "")

            try:
                race_info, entries = fetch_race_entries(race_id)
            except Exception as e:
                continue

            if not entries:
                continue

            if race_info.surface not in ("芝",):
                continue

            race_class_num = parse_race_class(
                (race_info.conditions or "") + " " + (race_info.name or "")
            )
            cls_name = {0: "新馬", 1: "1勝クラス", -1: "未勝利"}.get(race_class_num, f"cls{race_class_num}")

            if cls_name not in target_classes:
                continue

            key = (race_info.date or d.strftime("%Y年%-m月%-d日"),
                   race_info.venue or "", race_info.name or "")

            if key in existing_keys:
                print(f"  [スキップ] {key[0]} {key[1]} {key[2]}")
                continue

            print(f"  {cls_name} {race_info.name} {race_info.distance} {len(entries)}頭", end="", flush=True)

            # 採点
            try:
                scored = score_turf(entries, race_info)
            except Exception as e:
                print(f" → 採点失敗: {e}")
                continue

            sorted_r = sorted(scored, key=lambda x: x[1].total, reverse=True)

            # オッズ取得
            try:
                odds_raw = fetch_odds(race_id)
                num_to_name = {str(e.horse_number): e.horse_name for e in entries}
                odds_map = {num_to_name[k]: v for k, v in odds_raw.items() if k in num_to_name}
            except Exception:
                odds_map = {}

            n = len(entries)
            sign = calc_buy_sign(sorted_r, odds_map, n)

            # 三連複払戻取得
            trio_nums, trio_pay, name2num = fetch_trio_payout(race_id)

            if trio_nums is None or trio_pay is None:
                print(f" → 払戻取得失敗")
                continue

            # 予想順位→馬番マップ
            rank2num = {}
            for rank, (entry, bd) in enumerate(sorted_r, 1):
                num = name2num.get(entry.horse_name) or str(entry.horse_number)
                rank2num[str(rank)] = {"num": num, "name": entry.horse_name,
                                        "score": round(bd.total, 2)}

            top1_odds = odds_map.get(sorted_r[0][0].horse_name, 0) if sorted_r else 0
            gap_val = (sorted_r[0][1].total - sorted_r[1][1].total) if len(sorted_r) >= 2 else 0

            entry_obj = {
                "date":      key[0],
                "venue":     key[1],
                "race_name": key[2],
                "cls":       cls_name,
                "race_id":   race_id,
                "n_horses":  n,
                "gap":       round(gap_val, 2),
                "top1_odds": top1_odds,
                "sign":      sign,
                "trio_nums": list(trio_nums),
                "trio_pay":  trio_pay,
                "rank2num":  rank2num,
            }
            cache.append(entry_obj)
            existing_keys.add(key)

            # 中間保存（途中終了対策）
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)

            print(f" → 三連複={trio_nums} {trio_pay}円  サイン={sign}")

            race_count += 1
            if test and race_count >= 3:
                print("\n【テストモード: 3レースで終了】")
                break
        else:
            continue
        break

    print(f"\n取得完了: {len(cache)}レース（キャッシュ: {cache_path}）")
    analyze(cache)


def analyze(cache):
    """キャッシュデータからROIを計算"""
    if not cache:
        print("データなし")
        return

    def check_hit_formb(entry):
        nums = entry.get("rank2num", {})
        if len(nums) < 3:
            return False, 0
        sorted_ranks = sorted(nums.keys(), key=int)
        ax0_num = nums[sorted_ranks[0]]["num"]
        ax1_num = nums[sorted_ranks[1]]["num"]
        trio = set(entry["trio_nums"])
        combos = set()
        for b_rank in sorted_ranks[2:9]:
            b_num = nums[b_rank]["num"]
            if b_num != ax0_num and b_num != ax1_num:
                c = tuple(sorted([ax0_num, ax1_num, b_num], key=lambda x: int(x)))
                combos.add(c)
        trio_sorted = tuple(sorted(entry["trio_nums"], key=lambda x: int(x)))
        hit = trio_sorted in combos
        n_combos = len(combos)
        return hit, n_combos

    def check_hit_7pt(entry):
        nums = entry.get("rank2num", {})
        if len(nums) < 3:
            return False, 0
        sorted_ranks = sorted(nums.keys(), key=int)
        ax0_num = nums[sorted_ranks[0]]["num"]
        ax1_num = nums[sorted_ranks[1]]["num"]
        combos = set()
        for b_rank in sorted_ranks[2:9]:
            b_num = nums[b_rank]["num"]
            if b_num != ax0_num and b_num != ax1_num:
                c = tuple(sorted([ax0_num, ax1_num, b_num], key=lambda x: int(x)))
                combos.add(c)
        trio_sorted = tuple(sorted(entry["trio_nums"], key=lambda x: int(x)))
        hit = trio_sorted in combos
        n_combos = len(combos)
        return hit, n_combos

    print("\n" + "=" * 65)
    print("  1勝クラス ROI分析結果")
    print("=" * 65)

    # クラス別 × サイン別でグループ化
    by_class_sign = defaultdict(list)
    for e in cache:
        key = (e["cls"], e["sign"])
        by_class_sign[key].append(e)

    # サイン別集計
    sign_groups = defaultdict(list)
    for e in cache:
        sign_groups[e["sign"]].append(e)

    print(f"\n全レース: {len(cache)}件\n")
    print(f"{'サイン':<12} {'N':>4}  {'3複命中':>7}  {'フォームB ROI':>13}  {'7点 ROI':>10}")
    print("─" * 60)

    # 比較用: 2勝クラス以上の参照値
    ref = {
        "全体":      {"formb_roi": 82,  "7pt_roi": 193},
        "7pt条件":   {"formb_roi": 193, "7pt_roi": 193},
        "skip":      {"formb_roi": 9,   "7pt_roi": 0},
    }

    all_formb_bet = all_formb_pay = 0
    all_7pt_bet = all_7pt_pay = 0

    for sign in ["7pt", "formb", "skip", "neutral"]:
        rows = sign_groups.get(sign, [])
        if not rows:
            continue

        fb_bet = fb_pay = pt7_bet = pt7_pay = hits_fb = hits_7pt = 0
        for e in rows:
            hit_fb, n_fb = check_hit_formb(e)
            if n_fb > 0:
                fb_bet += n_fb * 100
                if hit_fb:
                    fb_pay += e["trio_pay"]
                    hits_fb += 1

            hit_7, n_7 = check_hit_7pt(e)
            if n_7 > 0:
                pt7_bet += n_7 * 100
                if hit_7:
                    pt7_pay += e["trio_pay"]
                    hits_7pt += 1

        roi_fb = fb_pay / fb_bet * 100 if fb_bet else 0
        roi_7  = pt7_pay / pt7_bet * 100 if pt7_bet else 0
        n = len(rows)
        hit_rate = hits_fb / n * 100 if n else 0

        print(f"{sign:<12} {n:>4}  {hits_fb:>3}/{n:<3}({hit_rate:>4.0f}%)  "
              f"ROI:{roi_fb:>6.1f}%        ROI:{roi_7:>5.1f}%")

        all_formb_bet += fb_bet
        all_formb_pay += fb_pay
        all_7pt_bet += pt7_bet
        all_7pt_pay += pt7_pay

    print("─" * 60)
    total_fb_roi = all_formb_pay / all_formb_bet * 100 if all_formb_bet else 0
    total_7pt_roi = all_7pt_pay / all_7pt_bet * 100 if all_7pt_bet else 0
    n_total = len(cache)
    print(f"{'全体合計':<12} {n_total:>4}  {'─':>7}   "
          f"ROI:{total_fb_roi:>6.1f}%        ROI:{total_7pt_roi:>5.1f}%")

    print()
    print("【参考: 2勝クラス以上の実績】")
    print(f"  全体フォームB: ROI 82%  |  7点推奨条件: ROI 193%")
    print(f"  見送り条件:    ROI  9%")
    print()
    print("【判定】")
    if total_7pt_roi > 150:
        print("  ✅ 7点推奨条件は 2勝クラス以上と同等以上の期待値あり → 買い対象")
    elif total_7pt_roi > 100:
        print("  ⚠ 7点推奨条件でかろうじて黒字 → 少額で様子見")
    else:
        print("  ❌ 7点推奨条件でも赤字 → 1勝クラス以下は見送り推奨")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--classes", nargs="+", default=["1勝クラス"],
                        help="対象クラス (1勝クラス / 未勝利 / 新馬)")
    parser.add_argument("--test",         action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()

    run_verify(
        target_classes=args.classes,
        dates=ALL_DATES,
        test=args.test,
        analyze_only=args.analyze_only,
    )
