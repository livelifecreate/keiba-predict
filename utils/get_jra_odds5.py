"""JRA今週のレースページから安田記念出馬表URL→オッズ取得"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
BASE_URL = "https://www.jra.go.jp"

soup = BeautifulSoup(
    requests.get(f"{BASE_URL}/keiba/thisweek/", headers=HEADERS, timeout=15).content, "lxml"
)

# 安田記念の出馬表リンクを探す
shutuba_url = None
for a in soup.find_all("a", href=True):
    href = a["href"]
    text = a.get_text(strip=True)
    if ("sde10" in href or "shutuba" in href.lower()) and ("安田" in text or "東京11" in text or "1600" in text):
        shutuba_url = BASE_URL + href if href.startswith("/") else href
        print(f"出馬表URL: {shutuba_url}")

# 見つからなければ全リンク確認
if not shutuba_url:
    print("今週ページの全リンク（sde/shutuba含むもの）:")
    for a in soup.find_all("a", href=True):
        h = a["href"]
        t = a.get_text(strip=True)
        if "sde10" in h or "shutuba" in h.lower() or "pw01" in h:
            print(f"  {t[:40]}  {h}")
