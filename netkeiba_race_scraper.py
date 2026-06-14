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
import random
import datetime
import requests
from bs4 import BeautifulSoup
from typing import Optional

def _sleep():
    time.sleep(random.uniform(1.5, 2.5))

# jra_scraper の型を再利用
from jra_scraper import RaceInfo, HorseEntry
from cache_store import cache_get, cache_set

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
    # 当日: race_list_sub（出馬表リンクあり）、過去: db.netkeiba レース一覧
    today = datetime.date.today()
    if date >= today:
        return f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date:%Y%m%d}"
    return f"https://db.netkeiba.com/race/list/{date:%Y%m%d}/"


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

    netkeiba の race_list_sub はメインレース（10R前後）しかリンクしない場合がある。
    取得できた race_id の接頭部（venue×series×day の10桁）を使って、
    1R〜12R を全て試み、存在するレースを追加する。
    """
    if dates is None:
        dates = _this_week_dates()

    races = []
    for date in dates:
        _sleep()
        r = requests.get(_race_list_url(date), headers=HEADERS, timeout=15)
        if r.status_code != 200:
            continue
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")

        seen = set()
        prefixes = set()  # 10桁の接頭部（venue×series×day）

        for a in soup.find_all("a", href=True):
            href = a["href"]
            race_id = None

            # 当日: shutuba.html?race_id=XXXX
            if "shutuba.html?race_id=" in href:
                race_id = href.split("race_id=")[1].split("&")[0]
            # 過去: /race/XXXXXXXXXXXX/
            else:
                m = re.search(r"/race/(\d{12})/", href)
                if m:
                    race_id = m.group(1)

            if not race_id or len(race_id) != 12 or race_id in seen:
                continue
            seen.add(race_id)
            prefixes.add(race_id[:10])

            text = a.get_text(strip=True)
            rnum_m = re.match(r"(\d+R)(.*)", text)
            race_num = rnum_m.group(1) if rnum_m else f"{int(race_id[10:12])}R"
            rest = rnum_m.group(2) if rnum_m else text
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

        # 接頭部から1R〜9Rを補完（race_list_subに載らないレースをカバー）
        for prefix in prefixes:
            venue_code = prefix[4:6]
            venue = VENUE_CODE.get(venue_code, "?")
            for rnum in range(1, 10):
                cand_id = f"{prefix}{rnum:02d}"
                if cand_id in seen:
                    continue
                seen.add(cand_id)
                race_num_str = f"{rnum}R"
                races.append({
                    "race_id":   cand_id,
                    "race_name": "",        # shutuba取得時に判明
                    "race_num":  race_num_str,
                    "venue":     venue,
                    "date":      date,
                    "label":     f"{date} {venue} {race_num_str}",
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

    tc_m = re.search(r"馬場:?(良|稍重|重|不良)", rd1_text)
    if not tc_m:
        tc_m = re.search(r"[|/\s](良|稍重|重|不良)[|/\s]", rd1_text)
    track_condition = tc_m.group(1) if tc_m else ""

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
        race_num=int(race_id[10:12]),
        distance=distance,
        surface=surface,
        conditions=conditions,
        start_time=start_time,
        track_condition=track_condition,
        url=f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}",
    )


def get_entry_list_netkeiba(race_id: str) -> tuple[RaceInfo, list[HorseEntry]]:
    """
    netkeiba の shutuba_past.html から出馬表を取得して
    (RaceInfo, [HorseEntry]) を返す。
    """
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
    _sleep()
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")

    race_info = _parse_race_info(soup, race_id)

    tables = soup.find_all("table")
    if not tables:
        return race_info, []

    entries = []
    horse_seq = 0
    for row in tables[0].find_all("tr"):
        tr_id = row.get("id", "")
        if not re.match(r"tr_\d+$", tr_id):
            continue
        horse_seq += 1

        # 取り消し馬がHTMLから除外されると連番がずれるため、
        # cells[1](馬番列)または tr_id の数字を馬番として使う
        cells_peek = row.find_all(["td", "th"])
        horse_num_cell = cells_peek[1].get_text(strip=True) if len(cells_peek) > 1 else ""
        if re.match(r"^\d+$", horse_num_cell):
            horse_num = horse_num_cell
        else:
            horse_num = re.sub(r"\D", "", tr_id) or str(horse_seq)

        cells = row.find_all(["td", "th"])
        if len(cells) < 5:
            continue

        # 枠番（確定前は空の場合あり）
        frame_num = cells[0].get_text(strip=True)

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
# レース結果取得（過去レース検証用）
# ──────────────────────────────────────────────────────────────
def classify_race(rd2_text: str, race_name: str) -> str:
    """RaceData02テキストとレース名からクラスを判定する"""
    if re.search(r"\(G[123]\)|\(GI+\)", race_name):
        return "重賞"
    if "オープン" in rd2_text:
        if re.search(r"Listed|リステッド", rd2_text + race_name):
            return "L"
        return "OP"
    if "３勝クラス" in rd2_text:
        return "3勝クラス"
    if "２勝クラス" in rd2_text:
        return "2勝クラス"
    if "１勝クラス" in rd2_text:
        return "1勝クラス"
    if "未勝利" in rd2_text:
        return "未勝利"
    if "新馬" in rd2_text:
        return "新馬"
    return "不明"


def fetch_odds(race_id: str) -> dict[str, float]:
    """
    netkeibaから単勝オッズを取得する。{馬番str: float} を返す。
    レース前のリアルタイムオッズ取得用。APIが空の場合はHTMLをパース。
    """
    headers = {**HEADERS, "Referer": "https://race.netkeiba.com/"}

    # まずJSON APIを試す
    api_url = (f"https://race.netkeiba.com/api/api_get_jra_odds.html"
               f"?race_id={race_id}&type=b1&action=update")
    try:
        _sleep()
        r = requests.get(api_url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        d = data.get("data")
        if d and data.get("status") not in ("error", "close"):
            # data が dict の場合は data["odds"] リストを使う（status:"middle" など）
            if isinstance(d, dict):
                odds_list = d.get("odds") or []
            else:
                odds_list = d if isinstance(d, list) else []
            result = {}
            for item in odds_list:
                if not isinstance(item, dict):
                    continue
                num  = str(item.get("num") or item.get("horse_num", ""))
                odds = item.get("odds") or item.get("win_odds")
                if num and odds:
                    try:
                        result[num] = float(odds)
                    except (ValueError, TypeError):
                        pass
            if result:
                return result
    except Exception:
        pass

    # フォールバック: HTMLの単勝オッズページをパース
    html_url = f"https://race.netkeiba.com/odds/index.html?race_id={race_id}&type=b1"
    try:
        _sleep()
        r = requests.get(html_url, headers=headers, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "lxml")
        result = {}
        for tbl in soup.find_all("table"):
            rows = tbl.find_all("tr")
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cells) < 3:
                    continue
                # 「馬番」「馬名」「オッズ」の列構成を想定
                num_c  = cells[1] if len(cells) > 1 else ""
                odds_c = cells[-1]
                if num_c.isdigit() and re.match(r"\d+\.\d+", odds_c):
                    try:
                        result[num_c] = float(odds_c)
                    except ValueError:
                        pass
        if result:
            return result
    except Exception:
        pass

    return {}


def fetch_race_result(race_id: str) -> Optional[dict]:
    """
    race.netkeiba.com/race/result.html からレース結果を取得する。

    Returns: {
        "race_id", "race_name", "date", "venue", "surface", "distance",
        "race_class",  # OP/2勝クラス/重賞 など
        "conditions",
        "race_num_int",  # 何R（整数）
        "entries": [
            {"rank", "frame", "horse_num", "horse_name", "horse_id",
             "age_sex", "weight_carried", "jockey"},
            ...
        ]
    }
    """
    cached = cache_get("race_result", race_id)
    if cached is not None:
        return cached
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    _sleep()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception:
        return None

    # レース名
    rname_el = soup.find(class_="RaceName")
    race_name = rname_el.get_text(strip=True) if rname_el else ""

    # コース・距離
    rd1 = soup.find(class_="RaceData01")
    rd1_text = rd1.get_text(separator=" ", strip=True) if rd1 else ""
    ds_m = re.search(r"(芝|ダ)(\d+)m", rd1_text)
    if not ds_m:
        return None  # 障害・未対応コース
    surface  = ds_m.group(1)
    distance = ds_m.group(2) + "m"

    st_m = re.search(r"(\d+:\d+)発走", rd1_text)
    start_time = st_m.group(1) if st_m else ""

    # 馬場状態
    tc_m = re.search(r"(良|稍重|重|不良)", rd1_text)
    track_condition = tc_m.group(1) if tc_m else ""

    # 開催情報・クラス
    rd2 = soup.find(class_="RaceData02")
    rd2_text = rd2.get_text(separator=" ", strip=True) if rd2 else ""

    # 日付・グレード（タイトルタグから取得）
    title_el = soup.find("title")
    title_text = title_el.get_text(strip=True) if title_el else ""
    date_m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", title_text)

    # Icon_GradeType1/2/3 または タイトル内の(G1)(G2)(G3)で重賞判定
    grade_span = rname_el.find(class_=re.compile(r"Icon_GradeType[123]$")) if rname_el else None
    grade_in_title = re.search(r"\((G[123])\)", title_text)
    if grade_span or grade_in_title:
        race_class = "重賞"
    else:
        race_class = classify_race(rd2_text, race_name)
    venue = VENUE_CODE.get(race_id[4:6], "")
    date_str = date_m.group(1) if date_m else ""

    # R番号（race_id末尾2桁）
    race_num_int = int(race_id[10:12])

    # 結果テーブル
    entries = []
    for tbl in soup.find_all("table"):
        ths = [th.get_text(strip=True) for th in tbl.find_all("th")]
        if "着順" not in ths and "馬番" not in ths:
            continue
        rows = tbl.find_all("tr")
        col_headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        def ci(name):
            try: return col_headers.index(name)
            except ValueError: return -1

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            texts = [c.get_text(strip=True) for c in cells]
            if len(texts) < 5:
                continue
            rank_text = texts[ci("着順")] if ci("着順") >= 0 else texts[0]
            if not rank_text.isdigit():
                continue
            # horse_idはリンクから取得
            horse_id = ""
            for a in row.find_all("a", href=True):
                m = re.search(r"/horse/(\d+)", a["href"])
                if m:
                    horse_id = m.group(1)
                    break
            odds_col = "単勝オッズ" if ci("単勝オッズ") >= 0 else "単勝"
            odds_text = texts[ci(odds_col)] if ci(odds_col) >= 0 else ""
            try:
                odds = float(odds_text)
            except (ValueError, TypeError):
                odds = None
            pop_text = texts[ci("人気")] if ci("人気") >= 0 else ""
            try:
                popularity = int(pop_text)
            except (ValueError, TypeError):
                popularity = None
            entries.append({
                "rank":           int(rank_text),
                "frame":          texts[ci("枠")] if ci("枠") >= 0 else "",
                "horse_num":      texts[ci("馬番")] if ci("馬番") >= 0 else "",
                "horse_name":     texts[ci("馬名")] if ci("馬名") >= 0 else "",
                "horse_id":       horse_id,
                "age_sex":        texts[ci("性齢")] if ci("性齢") >= 0 else "",
                "weight_carried": texts[ci("斤量")] if ci("斤量") >= 0 else "",
                "jockey":         texts[ci("騎手")] if ci("騎手") >= 0 else "",
                "odds":           odds,
                "popularity":     popularity,
            })
        break

    if len(entries) < 5:
        return None

    result = {
        "race_id":      race_id,
        "race_name":    race_name,
        "date":         date_str,
        "venue":        venue,
        "surface":      surface,
        "distance":     distance,
        "race_class":   race_class,
        "conditions":   rd2_text,
        "race_num_int": race_num_int,
        "start_time":      start_time,
        "track_condition": track_condition,
        "entries":         entries,
    }
    cache_set("race_result", race_id, result)
    return result


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
