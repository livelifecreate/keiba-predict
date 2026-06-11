"""db.nkeiba の4/18開催日ページからアンタレスS race_idを探す"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

r = requests.get("https://db.netkeiba.com/race/list/20260418/", headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

for a in soup.find_all("a", href=True):
    href = a["href"]
    m = re.search(r"/race/(\d{12})/", href)
    if m:
        text = a.get_text(strip=True)
        print(f"{m.group(1)}  {text[:50]}")
