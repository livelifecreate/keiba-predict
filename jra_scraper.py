"""JRA公式サイトから出馬表を取得するスクレイパー"""

import datetime
import re
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional


def build_jra_url(race_id: str, race_date: datetime.date) -> str:
    """
    netkeiba の race_id と開催日から JRA 公式出馬表 URL を生成する。

    CNAME 形式: pw01dde01{venue}{year}{kai}{nichi}{race}{date}/{checksum:02X}
    checksum = (169 + venue*10 + kai*84 + nichi*48 + race_contrib(race)) % 256
    race_contrib: race<=9 → race*181 % 256  /  race>=10 → (82+(race-10)*181) % 256
    """
    # race_id: YYYY + venue(2) + kai(2) + nichi(2) + race(2) = 12 chars
    venue = int(race_id[4:6])
    kai   = int(race_id[6:8])
    nichi = int(race_id[8:10])
    race  = int(race_id[10:12])
    year  = int(race_id[0:4])
    date_str = race_date.strftime("%Y%m%d")

    race_contrib = (race * 16) % 256
    base = (169 + venue * 10 + kai * 84 + nichi * 48) % 256
    checksum = (base + race_contrib) % 256

    cname = f"pw01dde01{venue:02d}{year}{kai:02d}{nichi:02d}{race:02d}{date_str}/{checksum:02X}"
    return f"{BASE_URL}/JRADB/accessD.html?CNAME={cname}"

BASE_URL = "https://www.jra.go.jp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


@dataclass
class RaceInfo:
    name: str
    date: str
    venue: str
    race_number: str
    distance: str
    surface: str
    conditions: str
    start_time: str
    url: str
    race_num: int = 0  # 何R（URLから抽出）
    track_condition: str = ""  # 馬場状態（良/稍重/重/不良）


@dataclass
class HorseEntry:
    frame_number: str       # 枠番
    horse_number: str       # 馬番
    horse_name: str         # 馬名
    record: str             # 戦績
    prize_money: str        # 賞金
    owner: str              # 馬主
    trainer: str            # 調教師
    age_sex: str            # 性齢
    weight_carried: str     # 負担重量
    jockey: str             # 騎手
    recent_races: list[str] = field(default_factory=list)  # 近走
    sire: str = ""  # 父
    bms:  str = ""  # 母父（ブルードメアサイア―）
    horse_weight: int = 0   # 馬体重kg（当日発表前は0）
    odds: float = 0.0       # 単勝オッズ（取得できない場合は0.0）
    popularity: int = 0     # 人気順
    horse_id: str = ""      # netkeiba 馬ID（道悪実績取得用）


def fetch_html(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return BeautifulSoup(resp.text, "html.parser")


def parse_race_info(soup: BeautifulSoup, url: str) -> RaceInfo:
    header = soup.find(id="race_header") or soup.find(class_="race_header")
    header_text = header.get_text(separator=" ", strip=True) if header else ""

    # PC版: class="race_name" / スマホ版: h3タグに「11R麦秋ステークス」形式
    race_name_elem = soup.find(class_="race_name")
    if race_name_elem:
        race_name = race_name_elem.get_text(strip=True)
    else:
        h3 = soup.find("h3")
        if h3:
            race_name = re.sub(r"^\d+R", "", h3.get_text(strip=True)).strip()
        else:
            race_name = ""

    # PC版はheader_text、スマホ版はfull_textで検索
    search_text = header_text if header_text else soup.get_text(separator=" ")

    # 日付
    date_match = re.search(r"\d{4}年\d{1,2}月\d{1,2}日", search_text)
    date = date_match.group() if date_match else ""

    # 発走時刻（「15時45分」または「発走15:45」形式）
    time_match = re.search(r"(\d+時\d+分)", search_text)
    if not time_match:
        time_match = re.search(r"発走(\d+:\d+)", search_text)
    start_time = time_match.group(1) if time_match else ""

    # 競馬場
    venue_match = re.search(r"\d+回(東京|中山|阪神|京都|中京|新潟|福島|小倉|札幌|函館)\d+日", search_text)
    if not venue_match:
        venue_match = re.search(r"(東京|中山|阪神|京都|中京|新潟|福島|小倉|札幌|函館)", search_text)
    venue = venue_match.group(1) if venue_match else ""

    # 回・日
    race_num_match = re.search(r"(\d+)回(?:東京|中山|阪神|京都|中京|新潟|福島|小倉|札幌|函館)(\d+)日", search_text)
    race_number = f"{race_num_match.group(1)}回{race_num_match.group(2)}日" if race_num_match else ""

    # 距離と馬場（PC版「1,400メートル（芝」 / スマホ版「1400m ダート・左」）
    dist_match = re.search(r"([\d,]+)\s*メートル\s*[（(]([芝ダ障])", search_text)
    if dist_match:
        distance = dist_match.group(1).replace(",", "") + "m"
        surface = dist_match.group(2)
    else:
        dist_match2 = re.search(r"(\d+)m\s*(ダート|芝|障)", search_text)
        if dist_match2:
            distance = dist_match2.group(1) + "m"
            s = dist_match2.group(2)
            surface = "ダ" if "ダート" in s else "芝" if "芝" in s else "障"
        else:
            distance = ""
            surface = ""

    conditions = race_name

    # 馬場状態: 「天候 晴 芝 良」「馬場：良」など複数パターン対応
    tc_match = (
        re.search(r"(?:芝|ダート|障害)\s*(良|稍重|重|不良)", search_text) or
        re.search(r"馬場[：:\s]*(良|稍重|重|不良)", search_text)
    )
    track_condition = tc_match.group(1) if tc_match else ""

    # URLからレース番号（何R）を抽出: pw01dde01{venue:2}{year:4}{kai:2}{nichi:2}{race:2}{date:8}
    race_num = 0
    m = re.search(r'pw01dde01\d{2}\d{4}\d{2}\d{2}(\d{2})\d{8}', url)
    if m:
        race_num = int(m.group(1))

    return RaceInfo(
        name=race_name,
        date=date,
        venue=venue,
        race_number=race_number,
        distance=distance,
        surface=surface,
        conditions=conditions,
        start_time=start_time,
        track_condition=track_condition,
        url=url,
        race_num=race_num,
    )


def parse_horse_entry(cells: list) -> Optional[HorseEntry]:
    if len(cells) < 4:
        return None

    # 枠番: waku クラスの img src から番号を取得
    waku_cell = next((c for c in cells if "waku" in (c.get("class") or [])), None)
    if waku_cell:
        img = waku_cell.find("img")
        if img:
            m = re.search(r"/waku/(\d+)\.png", img.get("src", ""))
            frame_num = m.group(1) if m else ""
        else:
            frame_num = waku_cell.get_text(strip=True)
    else:
        frame_num = cells[0].get_text(strip=True)

    # 馬番: num クラス
    num_cell = next((c for c in cells if "num" in (c.get("class") or [])), None)
    horse_num = num_cell.get_text(strip=True) if num_cell else cells[1].get_text(strip=True)

    # 馬名・戦績・賞金・馬主・調教師: horse クラス
    horse_cell = next((c for c in cells if "horse" in (c.get("class") or [])), None)
    horse_text = horse_cell.get_text(strip=True) if horse_cell else cells[2].get_text(strip=True)

    # 馬名はアルファベット・カタカナ・漢字・ひらがな・長音符のみ（オッズ数字を除く）
    horse_name_match = re.match(r"^([^\d（(]+)", horse_text)
    horse_name = horse_name_match.group(1).strip() if horse_name_match else horse_text.split("(")[0].strip()

    record_match = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)", horse_text)
    record = record_match.group(1) if record_match else ""

    prize_match = re.search(r"([\d,]+\.?\d*)万円", horse_text)
    prize = prize_match.group(0) if prize_match else ""

    # 馬体重: 「420kg」形式
    weight_match = re.search(r"(\d{3,4})kg", horse_text)
    horse_weight = int(weight_match.group(1)) if weight_match else 0

    # 単勝オッズ・人気: 「36.1(6番人気)」形式
    odds_match = re.search(r"([\d.]+)\((\d+)番人気\)", horse_text)
    odds       = float(odds_match.group(1)) if odds_match else 0.0
    popularity = int(odds_match.group(2))   if odds_match else 0

    owner = ""
    trainer = ""
    if "万円" in horse_text:
        after_prize = horse_text[horse_text.index("万円") + 2:].strip()
        trainer_match = re.search(r"([^\s（(]+)\s*[（(](美浦|栗東)[）)]", after_prize)
        if trainer_match:
            trainer = trainer_match.group(1)
        parts = after_prize.split()
        owner = parts[0] if parts else ""

    # 性齢・斤量・騎手: jockey クラス
    jockey_cell = next((c for c in cells if "jockey" in (c.get("class") or [])), None)
    jockey_text = jockey_cell.get_text(strip=True) if jockey_cell else cells[3].get_text(strip=True)

    age_sex_match = re.match(r"(牡\d+|牝\d+|せん\d+|騸\d+)", jockey_text)
    age_sex = age_sex_match.group(1) if age_sex_match else ""

    weight_match = re.search(r"(\d+\.\d+)\s*kg", jockey_text)
    weight = weight_match.group(1) + "kg" if weight_match else ""

    # 騎手名: 斤量の後、レーティング番号の前まで
    jockey_name_match = re.search(r"\d+\.\d+kg(.+?)(?:\s*\d{3}\s*[A-Z]|$)", jockey_text)
    jockey = jockey_name_match.group(1).strip() if jockey_name_match else ""

    # 近走: past クラス
    recent = []
    for cell in cells:
        cls = cell.get("class") or []
        if "past" in cls:
            text = cell.get_text(strip=True)
            if text:
                recent.append(text)

    return HorseEntry(
        frame_number=frame_num,
        horse_number=horse_num,
        horse_name=horse_name,
        record=record,
        prize_money=prize,
        owner=owner,
        trainer=trainer,
        age_sex=age_sex,
        weight_carried=weight,
        jockey=jockey,
        recent_races=recent,
        horse_weight=horse_weight,
        odds=odds,
        popularity=popularity,
    )


def build_jra_result_url(race_id: str, race_date: datetime.date) -> str:
    """
    JRA 公式結果ページ URL を生成する。
    結果チェックサム = (出馬表チェックサム + 0xBC) % 256
    """
    venue = int(race_id[4:6])
    kai   = int(race_id[6:8])
    nichi = int(race_id[8:10])
    race  = int(race_id[10:12])
    year  = int(race_id[0:4])
    date_str = race_date.strftime("%Y%m%d")

    race_contrib   = (race * 16) % 256
    base           = (169 + venue * 10 + kai * 84 + nichi * 48) % 256
    entry_cs       = (base + race_contrib) % 256
    result_cs      = (entry_cs + 0xBC) % 256

    cname = f"pw01sde01{venue:02d}{year}{kai:02d}{nichi:02d}{race:02d}{date_str}/{result_cs:02X}"
    return f"{BASE_URL}/JRADB/accessS.html?CNAME={cname}"


@dataclass
class ResultEntry:
    rank:         int
    frame_number: str
    horse_number: str
    horse_name:   str
    time:         str
    margin:       str
    popularity:   int
    odds:         float
    horse_weight: int
    weight_diff:  int


def _parse_result_row(cells: list) -> Optional[ResultEntry]:
    """結果ページの1行（tr）をパースして ResultEntry を返す"""
    if not cells:
        return None

    def _get(cls: str) -> str:
        c = next((x for x in cells if cls in (x.get("class") or [])), None)
        return c.get_text(strip=True) if c else ""

    # 着順: class="place"
    rank_text = _get("place")
    if not rank_text.isdigit():
        return None
    rank = int(rank_text)

    # 枠番: class="waku"（img src から番号）
    waku_cell = next((c for c in cells if "waku" in (c.get("class") or [])), None)
    frame_num = ""
    if waku_cell:
        img = waku_cell.find("img")
        if img:
            m = re.search(r"/waku/(\d+)\.png", img.get("src", ""))
            frame_num = m.group(1) if m else ""

    horse_num  = _get("num")       # 馬番
    horse_name = _get("horse")     # 馬名（クリーンなテキスト）
    time_str   = _get("time")      # タイム: "2:09.9"
    margin     = _get("margin")    # 着差
    pop_text   = _get("pop")       # 単勝人気

    # 馬体重（増減）: class="h_weight" → "486(+6)" or "486(-2)"
    hw_text     = _get("h_weight")
    wt_m        = re.search(r"(\d{3,4})\(([+-]?\d+)\)", hw_text)
    horse_weight = int(wt_m.group(1)) if wt_m else 0
    weight_diff  = int(wt_m.group(2)) if wt_m else 0

    popularity = int(pop_text) if pop_text.isdigit() else 0

    return ResultEntry(
        rank=rank, frame_number=frame_num, horse_number=horse_num,
        horse_name=horse_name, time=time_str, margin=margin,
        popularity=popularity, odds=0.0,
        horse_weight=horse_weight, weight_diff=weight_diff,
    )


def get_race_result(url: str) -> list[ResultEntry]:
    """結果ページを取得して ResultEntry のリストを返す。未公開なら空リスト。"""
    try:
        soup = fetch_html(url)
    except Exception:
        return []

    table = soup.find("table", class_="basic")
    if not table:
        return []

    results = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        entry = _parse_result_row(cells)
        if entry:
            results.append(entry)

    return results


def get_entry_list(url: str) -> tuple[RaceInfo, list[HorseEntry]]:
    """出馬表を取得して (レース情報, 出走馬リスト) を返す"""
    soup = fetch_html(url)
    race_info = parse_race_info(soup, url)

    table = soup.find("table", class_="basic")
    if not table:
        return race_info, []

    entries = []
    rows = table.find_all("tr")
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        entry = parse_horse_entry(cells)
        if entry and entry.horse_number:
            entries.append(entry)

    return race_info, entries


def get_thisweek_g1_urls() -> list[str]:
    """今週のG1レース出馬表URLリストを返す"""
    soup = fetch_html(f"{BASE_URL}/keiba/thisweek/")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "syutsuba" in href and href.startswith("/keiba/g1/"):
            full_url = BASE_URL + href
            if full_url not in urls:
                urls.append(full_url)
    return urls


def print_entry_list(race_info: RaceInfo, entries: list[HorseEntry]):
    print(f"\n{'='*60}")
    print(f"レース名  : {race_info.name}")
    print(f"開催日    : {race_info.date}  {race_info.venue}  {race_info.start_time}")
    print(f"コース    : {race_info.distance} ({race_info.surface})")
    print(f"{'='*60}")
    print(f"{'枠':>2} {'馬番':>3} {'馬名':<18} {'性齢':>4} {'斤量':>5} {'騎手':<12}")
    print("-" * 60)
    for e in entries:
        print(f"{e.frame_number:>2} {e.horse_number:>3} {e.horse_name:<18} {e.age_sex:>4} {e.weight_carried:>5} {e.jockey:<12}")


if __name__ == "__main__":
    print("今週のG1出馬表を取得中...")
    urls = get_thisweek_g1_urls()

    if not urls:
        print("今週のG1出馬表は見つかりませんでした。")
    else:
        for url in urls:
            print(f"\nURL: {url}")
            race_info, entries = get_entry_list(url)
            print_entry_list(race_info, entries)
            print(f"\n出走頭数: {len(entries)}頭")
