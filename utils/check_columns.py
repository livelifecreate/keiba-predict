"""netkeiba結果テーブルの列構造確認"""
import requests, time
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

race_id = "202605020811"  # ヴィクトリアマイル
url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

tables = soup.find_all("table")
for row in tables[0].find_all("tr")[1:4]:  # 最初の3行だけ
    cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
    for i, c in enumerate(cells):
        print(f"  [{i:2d}] {c}")
    print()
