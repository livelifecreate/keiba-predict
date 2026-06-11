"""血統ページ構造確認（母父インデックス確認）"""
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
horse_id = "2023107089"  # ロブチェン: 父ワールドプレミア、母父は？
url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
r = requests.get(url, headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

# テーブル0 の全td
tds = soup.find_all("table")[0].find_all("td")
print(f"td総数: {len(tds)}")
print("\nb_mlクラスのtdのみ:")
for j, td in enumerate(tds):
    cls = td.get("class", [])
    text = td.get_text(strip=True)
    # 年（数字）の前の部分を馬名として取り出す
    m = re.match(r"([^\d\[\(]+)", text)
    name = m.group(1).strip() if m else text[:20]
    print(f"  [{j:2d}] class={cls} name={name}")
