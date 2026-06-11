"""
1レース買い目パターンシミュレーター

使い方:
  python3 sim_race.py 202605030211   # 安田記念

出力:
  - システムランキング（全頭・オッズ付き）
  - 実際の結果と着順照合
  - 買い目パターン別 損益シミュレーション
"""

import sys
import re
import requests
from bs4 import BeautifulSoup
from collections import defaultdict

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from netkeiba_race_scraper import fetch_race_result, HEADERS
from verify_batch import process_race, fetch_past_races, fetch_sire
from cache_store import cache_get, cache_set


def fetch_payouts(race_id: str) -> dict:
    """払戻金テーブルを取得"""
    cached = cache_get("payouts", race_id)
    if cached is not None:
        return cached

    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception:
        return {}

    payouts = {}
    for tbl in soup.find_all("table", class_=re.compile("Pay")):
        for row in tbl.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            label = cells[0]
            amounts = []
            for c in cells[1:]:
                # "1,234円" 形式のみ対象
                m = re.search(r"([\d,]+)円", c)
                if m:
                    try:
                        amounts.append(int(m.group(1).replace(",", "")))
                    except ValueError:
                        pass
            if amounts:
                payouts[label] = {"amounts": amounts, "raw": cells}

    cache_set("payouts", race_id, payouts)
    return payouts


def simulate(race_id: str):
    print(f"\nrace_id: {race_id}")
    print("結果取得中...")

    result = cache_get("race_result", race_id)
    if result is None:
        result = fetch_race_result(race_id)
        if result:
            cache_set("race_result", race_id, result)
    if not result:
        print("結果取得失敗")
        return

    print(f"レース: {result['race_name']}  {result['date']}  {result['venue']}  "
          f"{result['surface']}{result['distance']}  {len(result['entries'])}頭\n")

    print("採点中（初回は時間がかかります）...")
    proc = process_race(result)
    if not proc:
        print("採点失敗")
        return

    se = proc["scored"]  # [(entry, score, actual_rank, odds, popularity), ...]

    # ── ランキング表示 ──
    print("=" * 70)
    print("■ システムランキング")
    print("=" * 70)
    print(f"  {'予想':>3}  {'馬名':12s}  {'スコア':>6}  {'単勝':>6}  {'人気':>3}  {'実着':>3}")
    print("-" * 70)
    for i, (entry, score, actual, odds, pop) in enumerate(se, 1):
        mark = "★" if actual == 1 else ("○" if actual <= 3 else "  ")
        odds_s = f"{odds:.1f}" if odds else "  -"
        pop_s  = str(pop) if pop else "-"
        print(f"{mark} {i:2d}位  {entry.horse_name:12s}  {score:+6.1f}  "
              f"{odds_s:>6}倍  {pop_s:>3}人気  {actual:>2}着")

    # 実際の1-2-3着
    top3_actual = sorted(se, key=lambda x: x[2])[:3]
    print(f"\n実際の結果: "
          f"1着={top3_actual[0][0].horse_name}  "
          f"2着={top3_actual[1][0].horse_name}  "
          f"3着={top3_actual[2][0].horse_name}")

    # ── 買い目パターンシミュレーション ──
    print("\n" + "=" * 70)
    print("■ 買い目パターン別シミュレーション（各100円）")
    print("=" * 70)

    payouts = fetch_payouts(race_id)
    if payouts:
        print("\n払戻金テーブル:")
        for k, v in payouts.items():
            print(f"  {k}: {v['raw']}")

    # 予想順位から馬番を取得
    def pred_horse_num(rank: int):
        if rank <= len(se):
            return int(se[rank-1][0].horse_number)
        return None

    def pred_actual_rank(rank: int):
        if rank <= len(se):
            return se[rank-1][2]
        return 99

    actuals = [pred_actual_rank(i) for i in range(1, len(se)+1)]
    actual_set_top = {actuals[i] for i in range(len(actuals))}

    def box_hit_umaren(top_n):
        s = set(actuals[:top_n])
        return 1 in s and 2 in s

    def box_hit_sanfuku(top_n):
        s = set(actuals[:top_n])
        return 1 in s and 2 in s and 3 in s

    from math import comb
    patterns = [
        ("単勝 予想1位",       1,             actuals[0] == 1),
        ("馬連 上位2頭BOX",    comb(2,2),     box_hit_umaren(2)),
        ("馬連 上位3頭BOX",    comb(3,2),     box_hit_umaren(3)),
        ("馬連 上位4頭BOX",    comb(4,2),     box_hit_umaren(4)),
        ("馬連 上位5頭BOX",    comb(5,2),     box_hit_umaren(5)),
        ("馬連 上位6頭BOX",    comb(6,2),     box_hit_umaren(6)),
        ("3連複 上位3頭BOX",   comb(3,3),     box_hit_sanfuku(3)),
        ("3連複 上位4頭BOX",   comb(4,3),     box_hit_sanfuku(4)),
        ("3連複 上位5頭BOX",   comb(5,3),     box_hit_sanfuku(5)),
        ("3連複 上位6頭BOX",   comb(6,3),     box_hit_sanfuku(6)),
        ("3連複 上位7頭BOX",   comb(7,3),     box_hit_sanfuku(7)),
        ("3連複 上位8頭BOX",   comb(8,3),     box_hit_sanfuku(8)),
    ]

    print(f"\n  {'パターン':20s}  {'点数':>4}  {'的中':>4}  {'投資':>6}")
    print("-" * 50)
    for name, tickets, hit in patterns:
        investment = tickets * 100
        hit_str = "◎" if hit else "×"
        print(f"  {name:20s}  {tickets:4d}点  {hit_str:>4}  {investment:5d}円")

    print("\n※ 的中パターンの払戻金は上記払戻テーブルで確認してください")


if __name__ == "__main__":
    race_id = sys.argv[1] if len(sys.argv) > 1 else "202605030211"
    simulate(race_id)
