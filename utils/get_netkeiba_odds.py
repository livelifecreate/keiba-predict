"""netkeibaの出馬表・オッズページから前日オッズ取得"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

race_id = "202605030211"

# オッズページ（単勝）
url = f"https://race.netkeiba.com/odds/index.html?race_id={race_id}&type=b1"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

# テーブルから馬名・オッズ行を探す
horses = []
for row in soup.find_all("tr"):
    cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
    # 馬番(数字)・馬名・オッズが含まれる行
    if len(cells) >= 3 and cells[0].isdigit():
        odds_val = None
        name_val = None
        for c in cells[1:]:
            if re.match(r"^\d+\.\d+$", c):
                odds_val = float(c)
            elif len(c) > 1 and not c.replace(".", "").isdigit() and not c.startswith("（"):
                name_val = c
        if odds_val and name_val:
            horses.append((odds_val, cells[0], name_val))

if horses:
    horses.sort()
    print(f"{'人気':>4} {'馬番':>4} {'馬名':<18} {'単勝':>8}")
    print("-" * 42)
    for rank, (odds, num, name) in enumerate(horses, 1):
        print(f"{rank:>4}  {num:>4}  {name:<18} {odds:>6.1f}倍")
else:
    # ページの生テキストを確認
    print("オッズ未取得。ページ内テキスト（数字含む行）:")
    for line in soup.get_text().split("\n"):
        line = line.strip()
        if re.search(r"\d+\.\d+", line) and len(line) < 60:
            print(f"  {line}")
