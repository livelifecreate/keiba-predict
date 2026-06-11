"""1〜2月 三連複払戻取得 → trio_cache_jan_feb.json"""
import csv, json, re, sys, time, random
from collections import OrderedDict
from itertools import combinations

import requests
from bs4 import BeautifulSoup

BASE_DIR   = "/Users/du/Documents/競馬予想システム"
SRC_CSV    = f"{BASE_DIR}/data/検証_芝_2026年1〜2月.csv"
CACHE_JSON = f"{BASE_DIR}/data/trio_cache_jan_feb.json"

sys.path.insert(0, BASE_DIR)
from netkeiba_race_scraper import get_race_list, HEADERS

def _sleep():
    time.sleep(random.uniform(1.2, 2.0))

def parse_date(date_str):
    import datetime
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

def load_csv():
    races, cls_map = OrderedDict(), {}
    with open(SRC_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row["日付"], row["競馬場"], row["レース名"])
            if key not in races:
                races[key] = {}
                cls_map[key] = row["クラス"]
            try:
                races[key][int(row["予想順位"])] = (row["馬名"], int(row["実着順"]))
            except (ValueError, KeyError):
                pass
    return races, cls_map

def build_id_map(race_keys):
    date_set = {parse_date(d) for d, _, _ in race_keys if parse_date(d)}
    print(f"race_id取得: {len(date_set)}日分...")
    id_map = {}
    for d in sorted(date_set):
        for r in get_race_list([d]):
            name = re.sub(r"[\(（].*$", "", r["race_name"]).strip()
            key = (d.strftime("%Y年%-m月%-d日"), r["venue"], name)
            id_map[key] = r["race_id"]
    return id_map

def fetch_result(race_id):
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    _sleep()
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    return BeautifulSoup(r.content, "lxml")

def get_trio(soup):
    for tbl in soup.find_all("table"):
        row = tbl.find("tr", class_="Fuku3")
        if not row:
            continue
        res = row.find("td", class_="Result")
        pay = row.find("td", class_="Payout")
        if not res or not pay:
            continue
        nums = [s.get_text(strip=True) for s in res.find_all("span") if s.get_text(strip=True)]
        pay_str = pay.get_text(strip=True).replace("円","").replace(",","")
        try:
            return tuple(nums), int(pay_str)
        except ValueError:
            return None, None
    return None, None

def get_name2num(soup):
    name2num = {}
    tables = soup.find_all("table")
    if not tables:
        return name2num
    for tr in tables[0].find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td","th"])]
        if len(cells) >= 4 and cells[2] and cells[3]:
            name2num[cells[3]] = cells[2]
    return name2num

def main():
    races, cls_map = load_csv()
    id_map = build_id_map(list(races.keys()))
    cache = []

    for key, d in races.items():
        date_str, venue, race_name = key
        print(f"{date_str} {venue} {race_name} ... ", end="", flush=True)
        race_id = id_map.get(key)
        if not race_id:
            print("race_id取得失敗")
            continue
        soup = fetch_result(race_id)
        name2num = get_name2num(soup)
        trio_nums, trio_pay = get_trio(soup)
        if trio_nums is None:
            print("払戻取得失敗")
            continue
        rank2num = {}
        for rank, (name, actual) in d.items():
            num = name2num.get(name)
            if num:
                rank2num[rank] = {"num": num, "actual": actual, "name": name}
        cache.append({
            "date": date_str, "venue": venue, "race_name": race_name,
            "cls": cls_map[key], "race_id": race_id,
            "trio_nums": list(trio_nums), "trio_pay": trio_pay,
            "rank2num": {str(k): v for k, v in rank2num.items()},
        })
        print(f"OK {trio_nums} {trio_pay}円")

    with open(CACHE_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"\n保存: {CACHE_JSON} ({len(cache)}レース)")

    # フォームB分析
    analyze(cache)

def make_triples(axis, opp):
    triples = set()
    for t in combinations(sorted(set(list(axis)+list(opp))), 3):
        if any(r in axis for r in t):
            triples.add(t)
    return list(triples)

FORMATIONS = [
    ("BOX 1-2-3",        list(combinations([1,2,3], 3))),
    ("BOX 1-2-3-4",      list(combinations([1,2,3,4], 3))),
    ("フォームB(1×2〜5×2〜9)", make_triples([1],[2,3,4,5]) + make_triples([2,3,4,5],[2,3,4,5,6,7,8,9])),
    ("1軸→2,3,4,5",      make_triples([1],[2,3,4,5])),
    ("1,2軸→3,4,5",      make_triples([1,2],[3,4,5])),
    ("1,2軸→3,4,5,6",    make_triples([1,2],[3,4,5,6])),
]

def analyze(cache, label="全クラス", classes=None):
    from collections import defaultdict
    stats = {f: {"invest":0,"returns":0,"hits":0,"race_hits":0,"races":0} for f,_ in FORMATIONS}
    for rec in cache:
        if classes and rec["cls"] not in classes:
            continue
        winning = set(rec["trio_nums"])
        r2n = {int(k): v for k, v in rec["rank2num"].items()}
        for fname, triples in FORMATIONS:
            race_hit = False
            for (ra, rb, rc) in triples:
                if ra not in r2n or rb not in r2n or rc not in r2n:
                    continue
                # 重複馬番を除外
                nums = {r2n[ra]["num"], r2n[rb]["num"], r2n[rc]["num"]}
                if len(nums) < 3:
                    continue
                stats[fname]["invest"] += 100
                if nums == winning:
                    stats[fname]["returns"] += rec["trio_pay"]
                    stats[fname]["hits"] += 1
                    race_hit = True
            stats[fname]["races"] += 1
            if race_hit:
                stats[fname]["race_hits"] += 1

    n_races = next((s["races"] for s in stats.values() if s["races"]>0), 0)
    print(f"\n【三連複実回収率 ― {label} ({n_races}R)】")
    print(f"{'フォーメーション':<28} {'bet/R':>5} {'R命中率':>8} {'ROI':>8}  {'収支':>9}")
    print("-"*65)
    for fname, _ in FORMATIONS:
        s = stats[fname]
        if s["invest"] == 0: continue
        bpr = s["invest"]/100/s["races"]
        rhr = s["race_hits"]/s["races"]*100
        roi = s["returns"]/s["invest"]*100
        diff = s["returns"]-s["invest"]
        mark = "★" if roi>=100 else ""
        print(f"{fname:<28} {bpr:>4.1f}  {rhr:>6.1f}%  {roi:>6.1f}%  {diff:>+9,}円  {mark}")

if __name__ == "__main__":
    main()
