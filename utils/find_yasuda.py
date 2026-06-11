"""6/7東京開催から安田記念のrace_idを探す"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

for date in ["20260607", "20260608"]:
    r = requests.get(f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}", headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "race_id=" not in href:
            continue
        text = a.get_text(strip=True)
        if "安田" in text or "G1" in text or "1600" in text:
            rid = re.search(r"race_id=(\d+)", href)
            if rid:
                print(f"{date}  {rid.group(1)}  {text[:60]}")
