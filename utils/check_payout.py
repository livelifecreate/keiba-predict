"""netkeiba払戻しテーブルの構造確認"""
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

race_id = "202605020811"  # ヴィクトリアマイル
url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

# 払戻しテーブルを探す
for tbl in soup.find_all("table"):
    text = tbl.get_text()
    if "ワイド" in text and "払戻" in text[:50] or "ワイド" in text[:200]:
        print("=== テーブル発見 ===")
        for row in tbl.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
            if cells:
                print(cells)
        break
