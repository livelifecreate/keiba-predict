"""
過去レースの出走馬データを再構成して採点し、実結果と比較する。

使い方:
  python3 backtest.py --race-id 202605021211   # 日本ダービー
"""

import re
import sys
import time
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

from jra_scraper import HorseEntry, RaceInfo
from scorer import score_all, print_scores, SCORE_LABELS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

VENUE_PATTERNS = ["東京","中山","阪神","京都","中京","新潟","福島","小倉","札幌","函館"]

# テキスト着差 → 秒数変換（おおよその値）
MARGIN_TEXT = {
    "ハナ": 0.02, "アタマ": 0.05, "クビ": 0.1,
    "1/2": 0.15, "3/4": 0.2,
    "1": 0.3, "1.1/2": 0.4, "2": 0.6,
    "2.1/2": 0.7, "3": 0.8, "4": 1.0,
    "5": 1.3, "大差": 3.0,
}


# ──────────────────────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────────────────────
def _extract_venue(kaika: str) -> str:
    for v in VENUE_PATTERNS:
        if v in kaika:
            return v
    return ""


def _parse_margin(raw: str, pos: str) -> float:
    """着差文字列 → 浮動小数点（勝ち馬との差）"""
    if pos == "1":
        return 0.0
    raw = raw.strip()
    if raw in MARGIN_TEXT:
        return MARGIN_TEXT[raw]
    try:
        v = float(raw)
        return abs(v)
    except ValueError:
        return 0.0


def _db_row_to_str(cells: list[str]) -> str | None:
    """
    db.netkeiba の戦績テーブル 1行 → parse_past_race 互換文字列に変換

    カラム順: 日付,開催,天気,R,レース名,映像,頭数,枠番,馬番,オッズ,人気,
              着順,騎手,斤量,距離,?,馬場,?,タイム,着差,...,コーナー,?,後3F,馬体重,...,次着馬名,...
    """
    if len(cells) < 30:
        return None

    # 日付
    date_raw = cells[0]
    dm = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})", date_raw)
    if not dm:
        return None
    date_jp = f"{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日"

    # 競馬場
    venue = _extract_venue(cells[1])

    # レース名（'皐月賞(GI)' → '皐月賞GI'）
    race_name_raw = cells[4]
    race_name = re.sub(r"[（(]([^)）]+)[）)]", r"\1", race_name_raw)

    # 着順
    pos = cells[11].strip()
    if not pos.isdigit():
        return None

    # 頭数
    field_size = cells[6].strip()

    # 距離・馬場
    ds = cells[14].strip()
    ds_m = re.match(r"(芝|ダ)(\d+)", ds)
    surface = ds_m.group(1) if ds_m else ""
    dist    = ds_m.group(2) if ds_m else ""

    # 後3F (cells[27])
    last3f = cells[27].strip() if len(cells) > 27 else ""
    if not re.match(r"^\d{2}\.\d", last3f):
        last3f = ""

    # 馬体重 (cells[28])
    hw_raw = cells[28].strip() if len(cells) > 28 else ""
    hw_m = re.match(r"(\d{3,4})", hw_raw)
    hw = hw_m.group(1) + "kg" if hw_m else ""

    # 着差 → マージン
    margin_raw = cells[19].strip() if len(cells) > 19 else "0"
    margin = _parse_margin(margin_raw, pos)
    margin_str = f"({margin})"

    # 2着馬名 (cells[31])
    second_raw = cells[31].strip() if len(cells) > 31 else ""
    second = second_raw.replace("(", "").replace(")", "")

    return (
        f"{date_jp}{venue}{race_name}"
        f"{pos}着{field_size}頭5番人気"
        f"{dist}{surface}{hw}"
        f"3F {last3f}{second}{margin_str}"
    )


# ──────────────────────────────────────────────────────────────
# データ取得
# ──────────────────────────────────────────────────────────────
def get_race_result(race_id: str) -> tuple[RaceInfo, list[dict]]:
    """
    netkeiba result.html から RaceInfo とレース結果リストを返す。
    結果リスト: [{"pos","frame","num","name","age_sex","weight","jockey",
                  "horse_weight","horse_id","actual_rank"}, ...]
    """
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")

    # タイトルから日付・レース名
    title = soup.title.get_text(strip=True) if soup.title else ""
    # 例: "日本ダービー(G1) 結果・払戻 | 2026年5月31日 東京11R ..."
    name_m = re.match(r"(.+?)[（(]", title)
    race_name = name_m.group(1).strip() if name_m else race_id
    date_m = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", title)
    date_str = date_m.group(1) if date_m else ""

    # RaceData から距離・コース
    rd1 = soup.find(class_="RaceData01")
    rd1_text = rd1.get_text(separator="|") if rd1 else ""
    ds_m = re.search(r"(芝|ダ)(\d+)m", rd1_text)
    surface  = ds_m.group(1) if ds_m else "芝"
    distance = ds_m.group(2) + "m" if ds_m else ""
    venue_code = race_id[4:6]
    from netkeiba_race_scraper import VENUE_CODE
    venue = VENUE_CODE.get(venue_code, "")

    rd2 = soup.find(class_="RaceData02")
    conditions = rd2.get_text(separator=" ", strip=True) if rd2 else ""

    race_info = RaceInfo(
        name=race_name, date=date_str, venue=venue,
        race_number="", distance=distance, surface=surface,
        conditions=conditions, start_time="", url=url,
    )

    # 結果テーブル
    tables = soup.find_all("table")
    horses = []
    if not tables:
        return race_info, horses

    # horse_id リンクを取得（db.netkeiba）
    horse_id_map = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/horse/" in href:
            hid_m = re.search(r"/horse/(\d+)", href)
            if hid_m:
                horse_id_map[a.get_text(strip=True)] = hid_m.group(1)

    for row in tables[0].find_all("tr")[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
        if len(cells) < 10:
            continue
        try:
            actual_rank = int(cells[0])
        except ValueError:
            continue
        horses.append({
            "actual_rank":   actual_rank,
            "frame":         cells[1],
            "num":           cells[2],
            "name":          cells[3],
            "age_sex":       cells[4],
            "weight":        cells[5],       # 斤量
            "jockey":        cells[6],
            "horse_weight":  cells[14] if len(cells) > 14 else "",
            "horse_id":      horse_id_map.get(cells[3], ""),
        })

    return race_info, horses


def _strip_horse_name(raw: str) -> str:
    """'アドマイヤマーズ2016 栗毛[血統]...' → 'アドマイヤマーズ'"""
    name = raw.split("[")[0].strip()
    name = re.sub(r"\d{4}.*$", "", name).strip()
    return name


def get_bloodline(horse_id: str) -> tuple[str, str]:
    """db.netkeiba から 父・母父 を取得して (sire, bms) を返す"""
    if not horse_id:
        return "", ""
    time.sleep(0.2)
    url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return "", ""
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception:
        return "", ""
    tbl = soup.find("table", class_="blood_table")
    if not tbl:
        return "", ""
    cells = [td.get_text(strip=True) for td in tbl.find_all("td")]
    # cells[0]=父, cells[16]=母, cells[17]=母父(BMS)
    sire = _strip_horse_name(cells[0])  if len(cells) > 0  else ""
    bms  = _strip_horse_name(cells[17]) if len(cells) > 17 else ""
    return sire, bms


def get_horse_history(horse_id: str, before_date: str) -> list[str]:
    """
    db.netkeiba から horse_id の戦績を取得し、
    before_date (YYYY/MM/DD) 以前の直近5走を parse_past_race 互換文字列リストで返す。
    """
    if not horse_id:
        return []
    time.sleep(0.3)
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception:
        return []

    tables = soup.find_all("table")
    if not tables:
        return []

    table = tables[0]
    rows = table.find_all("tr")[1:]  # ヘッダーをスキップ

    results = []
    for row in rows:
        cells = [c.get_text(strip=True) for c in row.find_all(["td","th"])]
        if not cells:
            continue
        race_date = cells[0]
        if race_date >= before_date:
            continue  # Derby 当日以降はスキップ
        converted = _db_row_to_str(cells)
        if converted:
            results.append(converted)
        if len(results) >= 5:
            break

    return results


# ──────────────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────────────
def run_backtest(race_id: str, training_url: str = None):
    print(f"\n[バックテスト] race_id={race_id}")

    # 結果取得
    race_info, result_horses = get_race_result(race_id)
    print(f"  レース: {race_info.name}  {race_info.date}  {race_info.venue}  {race_info.distance}({race_info.surface})")
    print(f"  出走頭数: {len(result_horses)}頭")

    # 各馬の事前戦績を並列取得
    dm = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", race_info.date)
    race_date_ymd = f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}" if dm else "2026/05/31"

    print(f"  {race_date_ymd} 以前の直近5走を取得中...")

    def fetch(h):
        history = get_horse_history(h["horse_id"], race_date_ymd)
        return h, history

    histories = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch, h): h for h in result_horses}
        for future in as_completed(futures):
            h, history = future.result()
            histories[h["name"]] = history
            print(f"    {h['name']}: {len(history)}走分取得")

    # 調教データ取得
    training_data = {}
    if training_url:
        from umasiru_scraper import scrape as scrape_umasiru
        from netkeiba_scraper import TrainingData as TD
        print(f"  [調教] {training_url} からデータ取得中...")
        umasiru_data = scrape_umasiru(training_url)
        training_data = {
            name: TD(horse_name=name, rank=e.rank, comment="", score=e.converted_score)
            for name, e in umasiru_data.items()
        }
        matched = sum(1 for h in result_horses if h["name"] in training_data)
        print(f"  [調教] {matched}/{len(result_horses)}頭マッチ")

    # 血統データ取得
    print(f"  血統データ取得中...")
    bloodlines = {}
    def fetch_bl(h):
        sire, bms = get_bloodline(h["horse_id"])
        return h["name"], sire, bms
    with ThreadPoolExecutor(max_workers=6) as executor:
        for name, sire, bms in [f.result() for f in as_completed(
                {executor.submit(fetch_bl, h): h for h in result_horses})]:
            bloodlines[name] = (sire, bms)
    matched_bl = sum(1 for n, (s, b) in bloodlines.items() if s)
    print(f"  血統: {matched_bl}/{len(result_horses)}頭取得")

    # HorseEntry 構築
    entries = []
    for h in result_horses:
        sire, bms = bloodlines.get(h["name"], ("", ""))
        entries.append(HorseEntry(
            frame_number   = h["frame"],
            horse_number   = h["num"],
            horse_name     = h["name"],
            record         = "",
            prize_money    = "",
            owner          = "",
            trainer        = "",
            age_sex        = h["age_sex"],
            weight_carried = h["weight"],
            jockey         = h["jockey"],
            recent_races   = histories.get(h["name"], []),
            sire           = sire,
            bms            = bms,
        ))

    # 採点
    results = score_all(entries, race_info, training_data=training_data if training_data else None)
    sorted_results = sorted(results, key=lambda x: x[1].total, reverse=True)

    # 予想 vs 実結果 の比較表を出力
    actual_rank_map = {h["name"]: h["actual_rank"] for h in result_horses}
    training_note = "調教込み" if training_data else "調教スコアなし"

    print(f"\n{'='*95}")
    print(f"  予想 vs 実結果  {race_info.name}  {race_info.date}  ※{training_note}")
    print(f"{'='*95}")
    print(f"{'予想':>4}  {'実結果':>6}  {'枠':>2}{'馬番':>3}  {'馬名':<16}  {'合計':>6}  {'加点':<35}  {'減点'}")
    print("-" * 100)

    for pred_rank, (entry, d) in enumerate(sorted_results, 1):
        actual = actual_rank_map.get(entry.horse_name, "-")
        plus_items  = [f"+{getattr(d,k):.1f}:{SCORE_LABELS[k]}" for k in SCORE_LABELS if getattr(d,k) > 0]
        minus_items = [f"{getattr(d,k):.1f}:{SCORE_LABELS[k]}" for k in SCORE_LABELS if getattr(d,k) < 0]
        plus_str  = " ".join(plus_items) or "—"
        minus_str = " ".join(minus_items) or "—"

        medal = {1:"🥇",2:"🥈",3:"🥉"}.get(pred_rank, "  ")
        actual_str = f"→実{actual}着" if isinstance(actual, int) else ""
        hit = "✅" if isinstance(actual, int) and actual <= 3 and pred_rank <= 5 else ""

        print(f"{pred_rank:>2}{medal} {actual_str:<8}  {entry.frame_number:>2}{entry.horse_number:>3}  "
              f"{entry.horse_name:<16}  {d.total:>+6.1f}  {plus_str:<35}  {minus_str}  {hit}")

    # 精度サマリー（予想TOP3/TOP5の中に実1〜3着が何頭含まれるか）
    print()
    top3_pred = {e.horse_name for e, _ in sorted_results[:3]}
    top5_pred = {e.horse_name for e, _ in sorted_results[:5]}
    actual_top3 = {h["name"] for h in result_horses if h["actual_rank"] <= 3}

    hit3 = len(top3_pred & actual_top3)
    hit5 = len(top5_pred & actual_top3)
    print(f"  【精度】予想TOP3に実1〜3着: {hit3}/3頭  ({', '.join(top3_pred & actual_top3) or 'なし'})")
    print(f"  【精度】予想TOP5に実1〜3着: {hit5}/3頭  ({', '.join(top5_pred & actual_top3) or 'なし'})")

    # CSV保存
    import csv, os
    date_clean = re.sub(r"[年月]", "", race_info.date).replace("日", "")
    name_clean = re.sub(r'[\s　/\\:*?"<>|]', "_", race_info.name)
    csv_path = os.path.join(os.path.dirname(__file__), f"prediction_{race_id}_{name_clean}_最終.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([race_info.name, race_info.date, race_info.venue,
                         f"{race_info.distance}({race_info.surface})"])
        writer.writerow([])
        writer.writerow(["実結果", "予想順位", "枠番", "馬番", "馬名", "合計",
                         "前走重賞近差", "前走3F最速", "同コース実績", "調教評価", "叩き2戦目",
                         "前走好走", "血統距離適性",
                         "初馬場", "距離延長", "昇級", "特殊条件", "前走ローカル",
                         "長期休養", "枠不利", "トップハンデ", "急坂歴なし",
                         "体重変動", "回り不適", "季節性別"])
        for pred_rank, (entry, d) in enumerate(sorted_results, 1):
            actual = actual_rank_map.get(entry.horse_name, "")
            writer.writerow([actual, pred_rank,
                             entry.frame_number, entry.horse_number, entry.horse_name,
                             d.total,
                             d.prev_high_grade_close, d.fastest_3f, d.same_course,
                             d.training_rank, d.second_start, d.prev_run_bonus, d.bloodline_distance,
                             d.first_surface, d.distance_up, d.promotion, d.special_condition,
                             d.local_prev, d.long_rest, d.post_surface, d.top_weight,
                             d.no_steep_win, d.weight_change, d.wrong_direction, d.seasonal_sex])
    print(f"  [CSV] {csv_path}")

    return sorted_results, result_horses


if __name__ == "__main__":
    race_id = "202605021211"  # 日本ダービー default
    training_url = None

    if "--race-id" in sys.argv:
        idx = sys.argv.index("--race-id")
        if idx + 1 < len(sys.argv):
            race_id = sys.argv[idx + 1]

    if "--training-url" in sys.argv:
        idx = sys.argv.index("--training-url")
        if idx + 1 < len(sys.argv):
            training_url = sys.argv[idx + 1]

    run_backtest(race_id, training_url)
