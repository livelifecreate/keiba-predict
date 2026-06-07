"""3連複・3連単の払戻し行HTMLを確認"""
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
race_id = "202605020811"
url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

for tbl in soup.find_all("table"):
    for row in tbl.find_all("tr"):
        label = row.find(["th","td"])
        if label and label.get_text(strip=True) in ("3連複", "3連単"):
            print(f"=== {label.get_text(strip=True)} class={row.get('class')} ===")
            print(row.prettify()[:800])
