"""shutubaページのHTML構造確認"""
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

race_id = "202605030211"
url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

# 馬名と人気を含む行を探す
for tbl in soup.find_all("table"):
    rows = tbl.find_all("tr")
    if len(rows) < 5:
        continue
    for row in rows[1:5]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
        if len(cells) > 5:
            print(cells[:12])
    break
