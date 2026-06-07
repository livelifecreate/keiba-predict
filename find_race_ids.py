"""指定日のレース一覧からrace_idを表示する"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
DATES = ["20260418"]

for date in DATES:
    r = requests.get(f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}", headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")
    print(f"\n=== {date} ===")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "shutuba.html?race_id=" not in href:
            continue
        rid = re.search(r"race_id=(\d+)", href)
        text = a.get_text(strip=True)
        if rid and text and rid.group(1) not in seen:
            seen.add(rid.group(1))
            print(f"  {rid.group(1)}  {text[:60]}")
