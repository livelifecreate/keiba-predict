"""ヴィクトリアマイル2026 出走馬・着順・horse_id取得"""
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

race_id = "202605020811"
url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

rname_el = soup.find(class_="RaceName")
rd1 = soup.find(class_="RaceData01")
print(f"レース: {rname_el.get_text(strip=True) if rname_el else '?'}")
print(f"情報: {rd1.get_text(separator=' ', strip=True) if rd1 else '?'}")
print()

tables = soup.find_all("table")
for t in tables:
    ths = [c.get_text(strip=True) for c in t.find_all("th")]
    if "着順" in ths or "馬番" in ths:
        rows = t.find_all("tr")
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
        print(f"ヘッダー: {headers}")
        print()
        for row in rows[1:]:
            cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
            horse_id = ""
            for a in row.find_all("a", href=True):
                m = re.search(r"/horse/(\d+)", a["href"])
                if m:
                    horse_id = m.group(1)
                    break
            if cells and len(cells) >= 6:
                print(f"  {' | '.join(cells[:10])}  horse_id={horse_id}")
        break
