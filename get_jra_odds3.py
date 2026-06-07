"""JRA安田記念ページから出馬表URLを取得してオッズ確認"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
BASE_URL = "https://www.jra.go.jp"

r = requests.get("https://www.jra.go.jp/keiba/g1/yasuda.html", headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

# 出馬表リンクを探す
shutuba_url = None
for a in soup.find_all("a", href=True):
    text = a.get_text(strip=True)
    href = a["href"]
    if "出馬表" in text or "shutuba" in href or "sde10" in href:
        shutuba_url = BASE_URL + href if href.startswith("/") else href
        print(f"出馬表URL: {shutuba_url}")
        break

if not shutuba_url:
    print("出馬表リンク見つからず。ページ内リンク:")
    for a in soup.find_all("a", href=True)[:30]:
        t = a.get_text(strip=True)
        if t:
            print(f"  {t[:30]}  {a['href'][:60]}")
