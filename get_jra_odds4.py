"""JRA安田記念ページの全リンクとオッズ含むテキストを確認"""
import requests, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
BASE_URL = "https://www.jra.go.jp"

r = requests.get("https://www.jra.go.jp/keiba/g1/yasuda.html", headers=HEADERS, timeout=15)
r.encoding = r.apparent_encoding
soup = BeautifulSoup(r.content, "lxml")

print("=== 全リンク ===")
for a in soup.find_all("a", href=True):
    t = a.get_text(strip=True)
    h = a["href"]
    if t and h != "#":
        print(f"  {t[:40]:<40}  {h[:80]}")

print("\n=== オッズ・人気を含むテキスト ===")
text = soup.get_text()
for line in text.split("\n"):
    line = line.strip()
    if line and ("倍" in line or "人気" in line or re.search(r"\d+\.\d+", line)):
        print(f"  {line[:80]}")
