"""HTMLを直接確認してレース名+グレードを取得"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# 2025年の各重賞開催日をリストで試す
DATE_PAIRS = [
    # クイーンS 7月函館
    "20250712", "20250713", "20250719", "20250720",
    # ニュージーランドT 4月中山
    "20250405", "20250406", "20260405", "20260406",
    # デイリー杯2歳S 11月京都
    "20251108", "20251115",
    # 12月中山
    "20251206", "20251213",
    # メトロポリタンS 5月東京
    "20250510",
]

KEYWORDS = ["クイーンS", "ニュージーランドT", "デイリー杯2歳S", "ディセンバーS", "メトロポリタンS", "BSN賞", "アンタレスS"]

found: dict[str, str] = {}

for date_str in DATE_PAIRS:
    if len(found) == len(KEYWORDS):
        break
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
    time.sleep(0.3)
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = r.apparent_encoding
    except Exception as e:
        print(f"  {date_str}: エラー {e}")
        continue

    soup = BeautifulSoup(r.content, "lxml")
    # ページ内の全テキストをダンプ（最初の1日分だけ）
    texts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if text:
            texts.append(text)
        for kw in KEYWORDS:
            if kw in text and kw not in found:
                found[kw] = f"{date_str}: 「{text}」"

print("=== 格付け確認結果 ===")
for kw in KEYWORDS:
    print(f"  {kw:<20}: {found.get(kw, '見つからず')}")

# race_list_subが空の場合、1日分のHTMLを確認
print("\n=== 2025/07/12のページサンプル ===")
r2 = requests.get("https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=20250712",
                  headers=HEADERS, timeout=10)
r2.encoding = r2.apparent_encoding
soup2 = BeautifulSoup(r2.content, "lxml")
print(f"  ステータス: {r2.status_code}")
print(f"  body先頭200字: {soup2.get_text()[:300]}")
