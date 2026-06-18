"""
1335件分の払い戻しデータをnetkeiba から一括取得してキャッシュに保存
"""
import sys, re, time, requests
sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from pathlib import Path
from bs4 import BeautifulSoup
from cache_store import cache_get, cache_set
from netkeiba_race_scraper import HEADERS

BASE = Path('/Users/du/Documents/競馬予想システム')
RACE_IDS = [f.stem for f in sorted((BASE / 'cache' / 'race_result').glob('*.json'))]


def fetch_payouts(race_id: str) -> dict:
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


if __name__ == "__main__":
    total = len(RACE_IDS)
    hit, skip, err, empty = 0, 0, 0, 0

    for i, race_id in enumerate(RACE_IDS):
        if i % 50 == 0:
            print(f"  {i}/{total}件 (取得:{hit} スキップ:{skip} 空:{empty} エラー:{err})", flush=True)

        cached = cache_get("payouts", race_id)
        if cached is not None:
            skip += 1
            continue

        try:
            p = fetch_payouts(race_id)
            if p:
                hit += 1
            else:
                empty += 1
            time.sleep(0.3)
        except Exception as e:
            err += 1

    print(f"\n完了: 取得={hit} スキップ={skip} 空={empty} エラー={err}")
