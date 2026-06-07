"""JRA出馬表ページから前日オッズ・人気を取得"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

# JRA 安田記念 出馬表URL（東京11R）
url = "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01sde10202&JRDB=202605030211"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

# オッズを含む表を探す
horses = []
for tbl in soup.find_all("table"):
    rows = tbl.find_all("tr")
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
        # 馬番・馬名・オッズが含まれそうな行
        if len(cells) >= 4 and any(re.match(r"^\d+\.\d+$", c) for c in cells):
            horses.append(cells)

if not horses:
    print("取得失敗。ページ内容を確認:")
    # テーブル一覧
    for i, tbl in enumerate(soup.find_all("table")[:5]):
        print(f"  table[{i}]: {tbl.get_text()[:100]}")
else:
    for row in horses[:20]:
        print(row)
