"""払戻しテーブルのHTML構造詳細確認"""
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

race_id = "202605020811"
url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

for tbl in soup.find_all("table"):
    if "ワイド" in tbl.get_text():
        for row in tbl.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            label = cells[0].get_text(strip=True)
            if label != "ワイド":
                continue
            print("=== ワイド行のHTML ===")
            print(row.prettify())
