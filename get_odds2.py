"""出馬表ページから人気・オッズを取得（別パターン）"""
import requests, re, json
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

race_id = "202605030211"

# 単勝オッズページ
for url in [
    f"https://race.netkeiba.com/odds/index.html?race_id={race_id}",
    f"https://race.netkeiba.com/odds/index.html?race_id={race_id}&type=b1",
    f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}",
]:
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")

    # 人気順テーブルを探す
    for tbl in soup.find_all("table"):
        text = tbl.get_text()
        if "倍" in text and ("人気" in text or re.search(r"\d+\.\d+", text)):
            print(f"URL: {url}")
            for row in tbl.find_all("tr")[:20]:
                cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
                if any("倍" in c or re.match(r"^\d+\.\d+$", c) for c in cells):
                    print(cells)
            print()
            break
