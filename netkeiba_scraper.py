"""
netkeiba から調教評価（A/B/C/D + コメント）を取得するスクレイパー。

対象: 重賞・主要特別戦（netkeiba が評価コメントを提供しているレースのみ）
一般戦: OikiriTable が存在しないため評価なし（スコア 0 扱い）

race_id 形式: YYYY + 会場コード(2) + 回次(2) + 日次(2) + レース番号(2)
例: 202605030211 = 2026年 東京(05) 3回(03) 2日(02) 11R
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass

BASE_URL = "https://race.netkeiba.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

VENUE_TO_CODE = {
    "札幌": "01", "函館": "02", "福島": "03", "新潟": "04",
    "東京": "05", "中山": "06", "中京": "07", "京都": "08",
    "阪神": "09", "小倉": "10",
}

# 評価ランク → スコア（+3: 調教自己ベスト水準の proxy）
RANK_SCORE = {"A": 3, "B": 0, "C": 0, "D": -1}


@dataclass
class TrainingData:
    horse_name: str
    rank: str        # A/B/C/D
    comment: str     # 気配抜群 / 叩き良化 / etc.
    score: int       # RANK_SCORE に基づくスコア


def _fetch(url: str) -> BeautifulSoup:
    time.sleep(0.5)  # サーバー負荷軽減
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return BeautifulSoup(r.content, "lxml")


def _build_race_id_prefix(race_date: str, venue: str, race_number: str) -> str:
    """
    JRA の race_info から netkeiba race_id の先頭10桁を生成する。
    race_date  : "2026年6月7日"
    venue      : "東京"
    race_number: "3回2日"
    → "2026050302"
    """
    year_m = re.search(r"(\d{4})年", race_date)
    year = year_m.group(1) if year_m else ""

    venue_code = VENUE_TO_CODE.get(venue, "")

    kai_m  = re.search(r"(\d+)回", race_number)
    nichi_m = re.search(r"(\d+)日", race_number)
    kai   = kai_m.group(1).zfill(2)   if kai_m   else "00"
    nichi = nichi_m.group(1).zfill(2) if nichi_m else "00"

    return f"{year}{venue_code}{kai}{nichi}"


def find_race_id(race_name: str, race_date: str, venue: str, race_number: str) -> str:
    """
    レース名・日付・会場・回/日 から netkeiba の race_id を検索して返す。
    見つからない場合は空文字。
    """
    prefix = _build_race_id_prefix(race_date, venue, race_number)
    if len(prefix) != 10:
        return ""

    # G1/重賞は後半レース（12R→1R の順に探す）
    for r_no in range(12, 0, -1):
        race_id = f"{prefix}{r_no:02d}"
        url = f"{BASE_URL}/race/oikiri.html?race_id={race_id}"
        try:
            soup = _fetch(url)
            title = soup.find("title")
            if title and race_name in title.get_text():
                return race_id
        except Exception:
            continue

    return ""


def fetch_training_data(race_id: str) -> dict[str, TrainingData]:
    """
    netkeiba の oikiri ページから全馬の調教評価を取得する。
    返り値: {馬名: TrainingData}
    OikiriTable が存在しないレース（一般戦）は空辞書を返す。
    """
    url = f"{BASE_URL}/race/oikiri.html?race_id={race_id}"
    soup = _fetch(url)

    table = soup.find("table", class_="OikiriTable")
    if not table:
        return {}

    result = {}
    for row in table.find_all("tr"):
        name_cell  = row.find(class_="Horse_Info")
        critic_cell = row.find(class_="Training_Critic")
        rank_cell  = next(
            (td for td in row.find_all("td")
             if td.get("class") and any("Rank_" in c for c in td.get("class", []))),
            None,
        )

        if not name_cell:
            continue

        horse_name = name_cell.get_text(strip=True)
        horse_name = re.sub(r"(前走|中間|休み明け).*$", "", horse_name).strip()

        comment = critic_cell.get_text(strip=True) if critic_cell else ""
        rank    = rank_cell.get_text(strip=True)   if rank_cell   else ""
        score   = RANK_SCORE.get(rank, 0)

        result[horse_name] = TrainingData(
            horse_name=horse_name,
            rank=rank,
            comment=comment,
            score=score,
        )

    return result


def get_training_scores(race_info) -> dict[str, TrainingData]:
    """
    JRA の race_info から netkeiba の調教評価を取得する。
    重賞・特別戦のみ有効。一般戦は空辞書。
    """
    race_id = find_race_id(
        race_name   = race_info.name,
        race_date   = race_info.date,
        venue       = race_info.venue,
        race_number = race_info.race_number,
    )

    if not race_id:
        print(f"  [調教] race_id 未検出: {race_info.name} → スキップ")
        return {}

    print(f"  [調教] race_id={race_id} でデータ取得中...")
    data = fetch_training_data(race_id)

    if not data:
        print(f"  [調教] OikiriTable なし（一般戦）→ 採点対象外")

    return data


if __name__ == "__main__":
    from jra_scraper import get_thisweek_g1_urls, get_entry_list

    urls = get_thisweek_g1_urls()
    for url in urls:
        race_info, _ = get_entry_list(url)
        print(f"\n=== {race_info.name} ===")
        training = get_training_scores(race_info)
        for name, td in training.items():
            print(f"  {name:<16} ランク:{td.rank}  {td.comment}  → {td.score:+d}点")
