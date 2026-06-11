"""
1〜2月の三連複ROI再計算（東京外枠後半加点ロジック追加後）
- trio_cache_jan_feb.json の払戻データを使用
- 検証_芝_2026年1〜2月.csv のスコアに outer_post_tokyo_late を加算して再ランキング
- 東京レースの開催日目はrace_idからnetkeibaにアクセスして取得
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, json, re, time
from collections import defaultdict
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_day_of_meeting(race_id: str) -> int:
    """netkeibaから開催日目を取得（失敗時は0）"""
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
    try:
        time.sleep(1.0)
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "lxml")
        rd2 = soup.find(class_="RaceData02")
        if not rd2:
            return 0
        text = rd2.get_text("|", strip=True)
        m = re.search(r"(\d+)日目", text)
        return int(m.group(1)) if m else 0
    except Exception as e:
        print(f"  [!] {race_id} 日目取得失敗: {e}", file=sys.stderr)
        return 0


def check_outer_post_tokyo_late(horse_number: str, venue: str, day_of: int) -> float:
    if venue != "東京" or day_of < 6:
        return 0.0
    try:
        return 1.5 if int(horse_number) >= 10 else 0.0
    except (ValueError, TypeError):
        return 0.0


def load_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    cache = json.load(open("data/trio_cache_jan_feb.json"))
    rows  = load_csv("data/検証_芝_2026年1〜2月.csv")

    # cache をキー（date+venue+race_name）で引けるようにする
    cache_by_key = {}
    for entry in cache:
        key = (entry["date"], entry["venue"], entry["race_name"])
        cache_by_key[key] = entry

    # 東京レースの開催日目をrace_idから取得
    tokyo_day_cache: dict[str, int] = {}
    print("=== 東京レースの開催日目取得 ===")
    seen_ids = set()
    for entry in cache:
        if entry["venue"] == "東京":
            rid = entry["race_id"]
            if rid not in seen_ids:
                seen_ids.add(rid)
                day = fetch_day_of_meeting(rid)
                tokyo_day_cache[rid] = day
                key = (entry["date"], entry["race_name"])
                print(f"  {key[0]} {key[1]} race_id={rid} → {day}日目")

    # CSVをレース単位にグループ化
    race_groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["日付"], r["競馬場"], r["レース名"])
        race_groups[key].append(r)

    # フォームB: 予想1〜2位を軸、3〜9位以降を相手
    def form_b_triples(sorted_horses: list[dict]) -> set[tuple]:
        nums = [h["馬番"] for h in sorted_horses]
        if len(nums) < 5:
            return set()
        axes   = nums[:2]   # 1〜2位
        others = nums[2:9]  # 3〜9位
        combos = set()
        for a in axes:
            for b in others:
                if a != b:
                    combos.add(tuple(sorted([axes[0], axes[1], b], key=lambda x: int(x))))
        # 軸2頭の両方が含まれる組み合わせのみ
        result = set()
        for combo in combos:
            if axes[0] in combo and axes[1] in combo:
                result.add(combo)
        return result

    # 統計
    total_races = 0
    hit_races   = 0
    total_bet   = 0
    total_pay   = 0
    no_cache    = 0

    # 旧ロジック（比較用）
    old_hit = 0
    old_bet = 0
    old_pay = 0

    print("\n=== ROI計算 ===")

    for key, horses in sorted(race_groups.items()):
        date, venue, race_name = key
        c = cache_by_key.get((date, venue, race_name))
        if not c:
            no_cache += 1
            continue

        trio_nums = tuple(sorted(c["trio_nums"], key=lambda x: int(x)))
        trio_pay  = c["trio_pay"]

        # 開催日目取得（東京のみ）
        day_of = 0
        if venue == "東京":
            day_of = tokyo_day_cache.get(c["race_id"], 0)

        # --- 新ロジックでスコア再計算 ---
        for h in horses:
            base = float(h["予想スコア"])
            add  = check_outer_post_tokyo_late(h["馬番"], venue, day_of)
            h["_new_score"] = base + add
            h["_old_score"] = base

        # 新順位でソート（スコア降順）
        sorted_new = sorted(horses, key=lambda h: h["_new_score"], reverse=True)
        sorted_old = sorted(horses, key=lambda h: h["_old_score"], reverse=True)

        # フォームB組み合わせ（新）
        combos_new = form_b_triples(sorted_new)
        combos_old = form_b_triples(sorted_old)

        bet_new = len(combos_new) * 100
        bet_old = len(combos_old) * 100

        hit_new = trio_nums in combos_new
        hit_old = trio_nums in combos_old

        pay_new = trio_pay if hit_new else 0
        pay_old = trio_pay if hit_old else 0

        total_races += 1
        total_bet   += bet_new
        total_pay   += pay_new
        old_bet     += bet_old
        old_pay     += pay_old
        if hit_new: hit_races += 1
        if hit_old: old_hit  += 1

        # 変化があったレースのみ表示
        changed = combos_new != combos_old
        marker = " ★変化" if changed else ""
        print(f"  {date} {venue} {race_name}{marker}")
        if changed:
            print(f"    旧: {'◎' if hit_old else '×'} 新: {'◎' if hit_new else '×'}  "
                  f"払戻={trio_pay}円  日目={day_of}")

    print(f"\n=== 結果サマリー ===")
    print(f"検証レース数: {total_races}  (trio_cacheなし: {no_cache})")
    print(f"{'項目':<18} {'旧':>8} {'新':>8}")
    print(f"{'命中率':<18} {old_hit/total_races*100:>7.1f}% {hit_races/total_races*100:>7.1f}%")
    print(f"{'総賭け金':<18} {old_bet:>8,} {total_bet:>8,}")
    print(f"{'総払戻':<18} {old_pay:>8,} {total_pay:>8,}")
    roi_old = old_pay / old_bet * 100 if old_bet else 0
    roi_new = total_pay / total_bet * 100 if total_bet else 0
    print(f"{'ROI':<18} {roi_old:>7.1f}% {roi_new:>7.1f}%")


if __name__ == "__main__":
    main()
