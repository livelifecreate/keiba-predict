"""出馬表ページから現在の人気・オッズを取得"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

race_id = "202605030211"
url = f"https://race.netkeiba.com/odds/index.html?race_id={race_id}&type=b1"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

# 単勝オッズテーブルを探す
rows = soup.find_all("tr", id=re.compile(r"tr_"))
if not rows:
    # 別パターンで探す
    rows = soup.select("table tbody tr")

print(f"{'人気':>4} {'馬番':>4} {'馬名':<16} {'単勝オッズ':>10}")
print("-" * 40)

horses = []
for row in rows:
    cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
    if len(cells) < 3:
        continue
    # 馬番・馬名・オッズを含む行を探す
    for i, c in enumerate(cells):
        if re.match(r"^\d+\.\d+$", c):  # オッズ形式
            try:
                num = cells[0] if cells[0].isdigit() else ""
                name = next((cells[j] for j in range(1, min(4, len(cells))) if len(cells[j]) > 1 and not cells[j].replace(".", "").isdigit()), "")
                odds = float(c)
                if num and name and odds > 0:
                    horses.append((odds, num, name))
            except (ValueError, IndexError):
                pass
            break

horses.sort()
for rank, (odds, num, name) in enumerate(horses, 1):
    print(f"{rank:>4}位  {num:>3}番  {name:<16} {odds:>8.1f}倍")
