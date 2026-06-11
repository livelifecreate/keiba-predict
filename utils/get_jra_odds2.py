"""JRA今週のレース一覧から安田記念URLを取得してオッズを確認"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
BASE_URL = "https://www.jra.go.jp"

# 今週のレース一覧から安田記念を探す
soup_week = BeautifulSoup(
    requests.get(f"{BASE_URL}/keiba/thisweek/", headers=HEADERS, timeout=15).content, "lxml"
)

yasuda_url = None
for a in soup_week.find_all("a", href=True):
    text = a.get_text(strip=True)
    href = a["href"]
    if "安田" in text or "yasuda" in href.lower():
        yasuda_url = BASE_URL + href if href.startswith("/") else href
        print(f"発見: {text} → {yasuda_url}")
        break

if not yasuda_url:
    print("安田記念URL見つからず。今週のリンク一覧:")
    for a in soup_week.find_all("a", href=True):
        text = a.get_text(strip=True)
        if text:
            print(f"  {text[:40]}  {a['href'][:60]}")
