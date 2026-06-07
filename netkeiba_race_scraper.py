"""
netkeiba から全レース（G1〜一般戦）の出馬表を取得するスクレイパー。

対応ページ:
  race_list_sub.html  → 指定日の全レース一覧
  shutuba_past.html   → 5走分の近走付き出馬表

使い方:
  from netkeiba_race_scraper import search_race, get_entry_list_netkeiba

  race_id = search_race("エプソムカップ")   # レース名検索
  race_info, entries = get_entry_list_netkeiba(race_id)
"""

import re
import time
import datetime
import requests
from bs4 import BeautifulSoup
from typing import Optional

# jra_scraper の型を再利用
from jra_scraper import RaceInfo, HorseEntry

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

VENUE_CODE = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}


# ──────────────────────────────────────────────────────────────
# レース一覧取得
# ──────────────────────────────────────────────────────────────
def _race_list_url(date: datetime.date) -> str:
    return f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date:%Y%m%d}"


def _this_week_dates() -> list[datetime.date]:
    """今週の土曜・日曜を返す（当日が土日の場合はその週を含む）"""
    today = datetime.date.today()
    weekday = today.weekday()          # 0=月 … 6=日
    days_to_sat = (5 - weekday) % 7   # 次の土曜まで
    if days_to_sat == 0 and weekday == 5:
        # 今日が土曜
        sat = today
    else:
        sat = today + datetime.timedelta(days=days_to_sat)
    return [sat, sat + datetime.timedelta(days=1)]


def get_race_list(dates: list[datetime.date] = None) -> list[dict]:
    """
    指定した日付リストの全レースを返す。
    省略時は今週の土日。
    戻り値: [{"race_id", "race_name", "race_num", "venue", "label"}, ...]
    """
    if dates is None:
        dates = _this_week_dates()

    races = []
    for date in dates:
        time.sleep(0.4)
        r = requests.get(_race_list_url(date), headers=HEADERS, timeout=15)
        if r.status_code != 200:
            continue
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "shutuba.html?race_id=" not in href:
                continue
            race_id = href.split("race_id=")[1].split("&")[0]
            text = a.get_text(strip=True)
            if not text:
                continue

            # テキスト例: "11R安田記念15:40芝1600m17頭"
            rnum_m = re.match(r"(\d+R)(.*)", text)
            race_num = rnum_m.group(1) if rnum_m else ""
            rest = rnum_m.group(2) if rnum_m else text

            # レース名は先頭の日本語部分
            name_m = re.match(r"([^\d]+)", rest)
            race_name = name_m.group(1).strip() if name_m else rest

            venue_code = race_id[4:6]
            venue = VENUE_CODE.get(venue_code, "?")

            races.append({
                "race_id":   race_id,
                "race_name": race_name,
                "race_num":  race_num,
                "venue":     venue,
                "date":      date,
                "label":     f"{date} {venue} {race_num} {race_name}",
            })

    return races


def search_race(keyword: str, dates: list[datetime.date] = None) -> Optional[str]:
    """
    レース名キーワードで race_id を検索して返す。
    複数候補がある場合は一覧を表示して選択を促す。
    """
    races = get_race_list(dates)
    matched = [r for r in races if keyword in r["race_name"]]

    if not matched:
        print(f"  [検索] '{keyword}' に一致するレースが見つかりません。")
        print("  今週のレース一覧:")
        for r in races:
            print(f"    {r['label']}")
        return None

    if len(matched) == 1:
        print(f"  [検索] {matched[0]['label']}")
        return matched[0]["race_id"]

    print(f"  [検索] 複数候補があります:")
    for i, r in enumerate(matched, 1):
        print(f"    {i}: {r['label']}")
    try:
        idx = int(input("  番号を入力: ")) - 1
        return matched[idx]["race_id"]
    except (ValueError, IndexError):
        return None


# ──────────────────────────────────────────────────────────────
# 出馬表パース
# ──────────────────────────────────────────────────────────────
def _parse_past_cell(parts: list[str]) -> Optional[str]:
    """
    netkeiba の Past セル（'|'区切り）を parse_past_race 互換の文字列に変換する。

    parts[0]: '2026.04.05\xa0阪神'   (date + venue)
    parts[1]: '6'                    (position)
    parts[2]: '大阪杯'               (race_name)
    parts[3]: 'GI'                   (grade)
    parts[4]: '芝2000 1:58.1'        (surface + distance + time)
    parts[5]: '良'                   (track)
    parts[6]: '15頭\xa012番\xa05人 ルメール 58.0'
    parts[7]: '11-11-11-4\xa0(35.2)\xa0492(+8)'
    parts[8]: 'クロワデュノール'     (2nd horse)
    parts[9]: '(0.5)'               (margin; negative = winner)
    """
    if len(parts) < 8:
        return None

    # 日付・競馬場
    dv = parts[0].replace("\xa0", " ").strip()
    dv_m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s*(.+)", dv)
    if not dv_m:
        return None
    year, mon, day, venue = dv_m.groups()
    venue = venue.strip()
    date_jp = f"{year}年{int(mon)}月{int(day)}日"

    pos       = parts[1].strip()
    race_name = parts[2].strip()
    grade     = parts[3].strip()        # GI / GII / GIII / 空文字
    surf_dist = parts[4].strip()        # 芝2000 1:58.1
    head_etc  = parts[6].replace("\xa0", " ")
    lap_hw    = parts[7].replace("\xa0", " ")
    second    = parts[8].strip() if len(parts) > 8 else ""
    margin_raw = parts[9].strip() if len(parts) > 9 else "(0)"

    # 距離・馬場
    sd_m = re.match(r"(芝|ダ)(\d+)", surf_dist)
    surface = sd_m.group(1) if sd_m else ""
    dist    = sd_m.group(2) if sd_m else ""

    # 頭数
    head_m = re.search(r"(\d+)頭", head_etc)
    heads  = head_m.group(0) if head_m else ""

    # 馬体重
    hw_m = re.search(r"(\d{3,4})\(", lap_hw)
    hw   = f"{hw_m.group(1)}kg" if hw_m else ""

    # 上がり3F
    last3f_m = re.search(r"\((\d+\.\d+)\)", lap_hw)
    last3f   = f"3F {last3f_m.group(1)}" if last3f_m else ""

    # 着差（勝ち馬との差を絶対値で）
    mg_m = re.search(r"\((-?[\d.]+)\)", margin_raw)
    margin_str = f"({abs(float(mg_m.group(1)))})" if mg_m else "(0)"

    # 通過順位（先頭の数字 = 1コーナー通過順位）
    corner_m = re.match(r"(\d+)[-]", lap_hw.strip())
    corner_str = f"1角:{corner_m.group(1)}" if corner_m else ""

    # JRA互換文字列を組み立て
    return (
        f"{date_jp}{venue}{race_name}{grade}"
        f"{pos}着{heads}5番人気"
        f"{dist}{surface}{hw}{last3f}"
        f"{second}{margin_str}{corner_str}"
    )


def _parse_race_info(soup: BeautifulSoup, race_id: str) -> RaceInfo:
    """shutuba_past ページからレース情報を抽出する"""
    # タイトルから日付を取得: "安田記念(G1) 5走表示 | 2026年6月7日 東京11R ..."
    title = soup.title.get_text(strip=True) if soup.title else ""
    date_m  = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", title)
    date_str = date_m.group(1) if date_m else ""

    # レース名
    race_name_el = soup.find(class_="RaceName")
    race_name = race_name_el.get_text(strip=True) if race_name_el else ""

    # RaceData01: 発走時刻・距離・コース
    rd1 = soup.find(class_="RaceData01")
    rd1_text = rd1.get_text(separator="|", strip=True) if rd1 else ""
    # 例: '15:40発走 /|芝1600m|(左　C)'
    start_time = ""
    distance   = ""
    surface    = ""
    st_m = re.search(r"(\d+:\d+)発走", rd1_text)
    if st_m:
        start_time = st_m.group(1)
    ds_m = re.search(r"(芝|ダ)(\d+)m", rd1_text)
    if ds_m:
        surface  = ds_m.group(1)
        distance = ds_m.group(2) + "m"

    # RaceData02: 開催情報・条件
    rd2 = soup.find(class_="RaceData02")
    rd2_text = rd2.get_text(separator="|", strip=True) if rd2 else ""
    # 例: '3回|東京|2日目|サラ系３歳以上|オープン|(国際)(指)|定量|17頭|...'
    parts = [p.strip() for p in rd2_text.split("|")]

    venue      = VENUE_CODE.get(race_id[4:6], "")
    race_num   = f"{parts[0]}{parts[2]}" if len(parts) >= 3 else ""  # "3回2日目"
    conditions = "|".join(parts[3:7]) if len(parts) >= 7 else ""

    return RaceInfo(
        name=race_name,
        date=date_str,
        venue=venue,
        race_number=race_num,
        distance=distance,
        surface=surface,
        conditions=conditions,
        start_time=start_time,
        url=f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}",
    )


def get_entry_list_netkeiba(race_id: str) -> tuple[RaceInfo, list[HorseEntry]]:
    """
    netkeiba の shutuba_past.html から出馬表を取得して
    (RaceInfo, [HorseEntry]) を返す。
    """
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
    time.sleep(0.5)
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")

    race_info = _parse_race_info(soup, race_id)

    tables = soup.find_all("table")
    if not tables:
        return race_info, []

    entries = []
    for row in tables[0].find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 5:
            continue

        # 枠番・馬番
        frame_num = cells[0].get_text(strip=True)
        horse_num = cells[1].get_text(strip=True)
        if not horse_num.isdigit():
            continue

        # 馬名 (Horse_Info セル: 父名|馬名|母名|母父名|厩舎|脚質...)
        hi_cell = next((c for c in cells if "Horse_Info" in " ".join(c.get("class", []))), None)
        hi_parts = hi_cell.get_text(separator="|", strip=True).split("|") if hi_cell else []
        horse_name = hi_parts[1].strip() if len(hi_parts) > 1 else ""
        sire       = hi_parts[0].strip() if len(hi_parts) > 0 else ""
        bms        = hi_parts[3].strip() if len(hi_parts) > 3 else ""
        trainer    = hi_parts[4].strip() if len(hi_parts) > 4 else ""

        # 性齢・騎手・斤量 (Jockey セル: 性齢毛色|騎手|斤量)
        jk_cell = next((c for c in cells if "Jockey" in " ".join(c.get("class", []))), None)
        jk_parts = jk_cell.get_text(separator="|", strip=True).split("|") if jk_cell else []
        age_sex        = jk_parts[0].strip() if jk_parts else ""
        jockey         = jk_parts[1].strip() if len(jk_parts) > 1 else ""
        weight_carried = jk_parts[2].strip() if len(jk_parts) > 2 else ""

        # 近走 (Past セル × 最大5)
        past_cells = [c for c in cells if "Past" in " ".join(c.get("class", []))]
        recent_races = []
        for pc in past_cells:
            parts = pc.get_text(separator="|", strip=True).split("|")
            converted = _parse_past_cell(parts)
            if converted:
                recent_races.append(converted)

        if not horse_name:
            continue

        entries.append(HorseEntry(
            frame_number   = frame_num,
            horse_number   = horse_num,
            horse_name     = horse_name,
            record         = "",
            prize_money    = "",
            owner          = "",
            trainer        = trainer,
            age_sex        = age_sex,
            weight_carried = weight_carried,
            jockey         = jockey,
            recent_races   = recent_races,
            sire           = sire,
            bms            = bms,
        ))

    return race_info, entries


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    keyword = sys.argv[1] if len(sys.argv) > 1 else "安田記念"
    race_id = search_race(keyword)
    if race_id:
        info, entries = get_entry_list_netkeiba(race_id)
        print(f"\n{info.name}  {info.date}  {info.venue}  {info.distance}({info.surface})")
        for e in entries:
            print(f"  {e.frame_number}枠 {e.horse_number}番 {e.horse_name}  近走{len(e.recent_races)}件")
            if e.recent_races:
                print(f"    前走: {e.recent_races[0]}")
