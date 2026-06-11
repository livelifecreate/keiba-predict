"""ウィクトルウェルスの近走確認"""
import re, time, requests
from bs4 import BeautifulSoup
HEADERS = {"User-Agent": "Mozilla/5.0"}
horse_id = "2022104655"
url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")
table = soup.find("table")
rows = table.find_all("tr") if table else []
headers = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])] if rows else []
def idx(n):
    try: return headers.index(n)
    except: return -1

print("ウィクトルウェルス 近走5件:")
for row in rows[1:6]:
    cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
    c = lambda i: cells[i] if 0 <= i < len(cells) else ""
    print(f"  {c(0)} {c(idx('開催'))} {c(idx('レース名')):<22} 着:{c(idx('着順'))} {c(idx('距離'))}")
