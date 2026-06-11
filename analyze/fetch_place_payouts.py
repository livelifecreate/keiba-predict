"""
キャッシュ済みrace_idを使って複勝払戻を取得し、実回収率を計算する。
"""
import csv, json, re, sys, time, random
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

BASE_DIR   = "/Users/du/Documents/競馬予想システム"
SRC_CSV    = f"{BASE_DIR}/data/検証_芝_2026年3〜5月.csv"
TRIO_CACHE = f"{BASE_DIR}/data/trio_cache.json"
PLACE_CACHE= f"{BASE_DIR}/data/place_cache.json"

sys.path.insert(0, BASE_DIR)
from netkeiba_race_scraper import HEADERS

def _sleep():
    time.sleep(random.uniform(1.2, 2.0))

def fetch_place_payouts(race_id):
    """複勝の全払戻を {馬番: 払戻額} で返す"""
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    _sleep()
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")

    payouts = {}
    for tbl in soup.find_all("table"):
        row = tbl.find("tr", class_="Fukusho")
        if not row:
            continue
        # 複勝行のテキスト: "複勝 8 54 120円 110円 200円 2人気 1人気 4人気"
        text = row.get_text(" ", strip=True)
        # 馬番と払戻をペアで抽出: 馬番(1-2桁)→次の金額(3桁以上)
        nums = re.findall(r'\b(\d{1,2})\b', text)
        pays = re.findall(r'(\d{3,6})円', text)
        # 払戻テーブルの構造: 馬番リスト(3頭分) + 払戻リスト(3頭分)
        result_td = row.find("td", class_="Result")
        payout_td = row.find("td", class_="Payout")
        if result_td and payout_td:
            horse_nums = [s.get_text(strip=True) for s in result_td.find_all("span") if s.get_text(strip=True)]
            pay_strs   = [p.strip().replace("円","").replace(",","")
                          for p in payout_td.get_text(separator="\n").split("\n")
                          if re.search(r"\d{3,}", p.replace(",",""))]
            for num, pay in zip(horse_nums, pay_strs):
                try:
                    payouts[num] = int(pay)
                except ValueError:
                    pass
        break
    return payouts

def main():
    # trio_cacheからrace_idとrank2numを流用
    trio = json.load(open(TRIO_CACHE, encoding="utf-8"))

    place_data = []
    for rec in trio:
        print(f"{rec['date']} {rec['venue']} {rec['race_name']} ... ", end="", flush=True)
        payouts = fetch_place_payouts(rec["race_id"])
        if not payouts:
            print("取得失敗")
            continue
        place_data.append({
            "date": rec["date"], "venue": rec["venue"],
            "race_name": rec["race_name"], "cls": rec["cls"],
            "race_id": rec["race_id"],
            "place_payouts": payouts,
            "rank2num": rec["rank2num"],
        })
        print(f"複勝={payouts}")

    with open(PLACE_CACHE, "w", encoding="utf-8") as f:
        json.dump(place_data, f, ensure_ascii=False, indent=2)
    print(f"\nキャッシュ保存: {PLACE_CACHE} ({len(place_data)}レース)")

    analyze(place_data)

def analyze(data):
    stats = defaultdict(lambda: defaultdict(lambda: {"invest":0,"returns":0,"hits":0}))

    for rec in data:
        cls   = rec["cls"]
        r2n   = {int(k): v for k, v in rec["rank2num"].items()}
        pays  = rec["place_payouts"]

        for rank in range(1, 7):
            if rank not in r2n:
                continue
            num = r2n[rank]["num"]
            pay = pays.get(num, 0)
            for c in [cls, "全体"]:
                stats[c][f"複勝{rank}位"]["invest"]  += 100
                if pay > 0:
                    stats[c][f"複勝{rank}位"]["hits"]    += 1
                    stats[c][f"複勝{rank}位"]["returns"] += pay

    print(f"\n【複勝 実回収率】\n")
    print(f"{'クラス':<10} {'買い方':<10} {'命中率':>7} {'回収率':>8} {'収支':>10}")
    print("-"*50)
    for cls in ["全体","重賞","OP","2勝クラス"]:
        for rank in range(1, 7):
            key = f"複勝{rank}位"
            s = stats[cls][key]
            if s["invest"] == 0: continue
            n = s["invest"] // 100
            hr  = s["hits"] / n * 100
            roi = s["returns"] / s["invest"] * 100
            diff= s["returns"] - s["invest"]
            print(f"{cls:<10} {key:<10} {hr:>5.1f}%  {roi:>7.1f}%  {diff:>+9,}円")
        print()

if __name__ == "__main__":
    main()
