"""
検証CSVの各レースについて、netkeibaから三連複実際払戻を取得して
実回収率を計算するスクリプト。

使い方:
  python3 fetch_trio_payouts.py --test     # 最初の3レースのみ
  python3 fetch_trio_payouts.py            # 全レース取得＆キャッシュ保存
  python3 fetch_trio_payouts.py --analyze  # キャッシュから分析のみ（再取得なし）
"""
import csv
import json
import re
import sys
import time
import random
import argparse
from collections import defaultdict, OrderedDict
from itertools import combinations

import requests
from bs4 import BeautifulSoup

BASE_DIR = "/Users/du/Documents/競馬予想システム"
SRC_CSV   = f"{BASE_DIR}/data/検証_芝_2026年3〜5月.csv"
CACHE_JSON = f"{BASE_DIR}/data/trio_cache.json"

sys.path.insert(0, BASE_DIR)
from netkeiba_race_scraper import get_race_list, HEADERS

def _sleep():
    time.sleep(random.uniform(1.2, 2.0))

def parse_date(date_str):
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not m:
        return None
    import datetime
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

def build_race_id_map(race_keys):
    import datetime
    date_set = set()
    for date_str, venue, race_name in race_keys:
        d = parse_date(date_str)
        if d:
            date_set.add(d)

    print(f"レース一覧取得: {len(date_set)}日分...")
    id_map = {}
    for d in sorted(date_set):
        races = get_race_list([d])
        for r in races:
            name = re.sub(r"[\(（].*$", "", r["race_name"]).strip()
            key = (d.strftime("%Y年%-m月%-d日"), r["venue"], name)
            id_map[key] = r["race_id"]
    return id_map

def fetch_result_page(race_id):
    """レース結果ページを取得してsoupを返す（共通化）"""
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    _sleep()
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    return BeautifulSoup(r.content, "lxml")

def fetch_trio_payout(soup):
    for tbl in soup.find_all("table"):
        row = tbl.find("tr", class_="Fuku3")
        if not row:
            continue
        result_td = row.find("td", class_="Result")
        payout_td = row.find("td", class_="Payout")
        if not result_td or not payout_td:
            continue
        nums = [s.get_text(strip=True) for s in result_td.find_all("span") if s.get_text(strip=True)]
        pay_str = payout_td.get_text(strip=True).replace("円", "").replace(",", "")
        try:
            return tuple(nums), int(pay_str)
        except ValueError:
            return None, None
    return None, None

def fetch_horse_numbers(soup):
    name2num = {}
    tables = soup.find_all("table")
    if not tables:
        return name2num
    for tr in tables[0].find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td","th"])]
        if len(cells) < 4:
            continue
        if cells[2] and cells[3]:
            name2num[cells[3]] = cells[2]
    return name2num

def load_csv():
    races = OrderedDict()
    race_class_map = {}
    with open(SRC_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row["日付"], row["競馬場"], row["レース名"])
            if key not in races:
                races[key] = {}
                race_class_map[key] = row["クラス"]
            try:
                races[key][int(row["予想順位"])] = (row["馬名"], int(row["実着順"]))
            except (ValueError, KeyError):
                pass
    return races, race_class_map

def fetch_and_cache(test=False):
    races, race_class_map = load_csv()
    race_keys = list(races.keys())
    if test:
        race_keys = race_keys[:3]
        print("【テストモード: 最初の3レースのみ】\n")

    id_map = build_race_id_map(race_keys)
    cache = []

    for key in race_keys:
        date_str, venue, race_name = key
        cls = race_class_map[key]
        d   = races[key]

        print(f"{date_str} {venue} {race_name} ({cls}) ... ", end="", flush=True)

        race_id = id_map.get(key)
        if not race_id:
            print("race_id取得失敗")
            continue

        soup = fetch_result_page(race_id)
        name2num   = fetch_horse_numbers(soup)
        trio_nums, trio_pay = fetch_trio_payout(soup)

        if trio_nums is None or trio_pay is None:
            print(f"払戻取得失敗 (race_id={race_id})")
            continue

        # 予想順位→馬番マップ
        rank2num = {}
        for rank, (name, actual) in d.items():
            num = name2num.get(name)
            if num:
                rank2num[rank] = {"num": num, "actual": actual, "name": name}

        cache.append({
            "date": date_str, "venue": venue, "race_name": race_name,
            "cls": cls, "race_id": race_id,
            "trio_nums": list(trio_nums),
            "trio_pay": trio_pay,
            "rank2num": {str(k): v for k, v in rank2num.items()},
        })
        print(f"三連複={trio_nums} {trio_pay}円")

    with open(CACHE_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"\nキャッシュ保存: {CACHE_JSON}  ({len(cache)}レース)")
    return cache

def analyze(cache, target_classes=None):
    from itertools import combinations as comb

    def make_triples(axis, opponents):
        triples = set()
        all_ranks = sorted(set(list(axis) + list(opponents)))
        for t in comb(all_ranks, 3):
            if any(r in axis for r in t):
                triples.add(t)
        return list(triples)

    formations = [
        ("BOX 1-2-3",        list(comb([1,2,3], 3))),
        ("BOX 1-2-3-4",      list(comb([1,2,3,4], 3))),
        ("BOX 1-2-3-4-5",    list(comb([1,2,3,4,5], 3))),
        ("BOX 1-2-3-4-5-6",  list(comb([1,2,3,4,5,6], 3))),
        ("1軸→2,3,4",        make_triples([1],[2,3,4])),
        ("1軸→2,3,4,5",      make_triples([1],[2,3,4,5])),
        ("1軸→2,3,4,5,6",    make_triples([1],[2,3,4,5,6])),
        ("1,2軸→3,4",        make_triples([1,2],[3,4])),
        ("1,2軸→3,4,5",      make_triples([1,2],[3,4,5])),
        ("1,2軸→3,4,5,6",    make_triples([1,2],[3,4,5,6])),
        ("1,2,3軸→4,5",      make_triples([1,2,3],[4,5])),
        ("1,2,3軸→4,5,6",    make_triples([1,2,3],[4,5,6])),
    ]

    stats = {f: {"invest":0,"returns":0,"hits":0,"race_hits":0,"races":0}
             for f,_ in formations}

    for rec in cache:
        if target_classes and rec["cls"] not in target_classes:
            continue
        winning = set(rec["trio_nums"])
        r2n = {int(k): v for k, v in rec["rank2num"].items()}

        for fname, triples in formations:
            race_hit = False
            for (ra, rb, rc) in triples:
                if ra not in r2n or rb not in r2n or rc not in r2n:
                    continue
                stats[fname]["invest"] += 100
                nums = {r2n[ra]["num"], r2n[rb]["num"], r2n[rc]["num"]}
                if nums == winning:
                    stats[fname]["returns"] += rec["trio_pay"]
                    stats[fname]["hits"]    += 1
                    race_hit = True
            stats[fname]["races"] += 1
            if race_hit:
                stats[fname]["race_hits"] += 1

    label = "OP+2勝クラス" if target_classes else "全クラス"
    n_races = next(s["races"] for s in stats.values() if s["races"] > 0)
    print(f"\n【三連複 実回収率 ― {label} ({n_races}R)】")
    print(f"{'フォーメーション':<22} {'bet/R':>5} {'R命中率':>8} {'実回収率':>9}  {'収支':>9}")
    print("-" * 62)

    results = []
    for fname, _ in formations:
        s = stats[fname]
        if s["invest"] == 0:
            continue
        bpr = s["invest"] / 100 / s["races"]
        rhr = s["race_hits"] / s["races"] * 100
        roi = s["returns"] / s["invest"] * 100
        diff = s["returns"] - s["invest"]
        results.append((fname, bpr, rhr, roi, diff))

    for fname, bpr, rhr, roi, diff in sorted(results, key=lambda x: -x[3]):
        mark = "★" if roi >= 100 else ""
        print(f"{fname:<22} {bpr:>4.1f}  {rhr:>6.1f}%  {roi:>7.1f}%  {diff:>+9}円  {mark}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test",    action="store_true")
    parser.add_argument("--analyze", action="store_true", help="キャッシュから分析のみ")
    args = parser.parse_args()

    if args.analyze:
        with open(CACHE_JSON, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"キャッシュ読み込み: {len(cache)}レース")
    else:
        cache = fetch_and_cache(test=args.test)

    analyze(cache)
    analyze(cache, target_classes=["OP", "2勝クラス"])
    analyze(cache, target_classes=["OP"])
    analyze(cache, target_classes=["2勝クラス"])

if __name__ == "__main__":
    main()
