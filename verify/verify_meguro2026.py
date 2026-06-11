"""
目黒記念2026（2026/5/31 東京芝2500m 14頭）再検証スクリプト
race_id: 202605021212
"""
import re
import sys
import time
import csv
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from scorer import (
    parse_past_race, score_all, parse_race_class,
    SCORE_LABELS, _get_label, ScoreBreakdown,
)
from jra_scraper import HorseEntry, RaceInfo

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

RACE_INFO = RaceInfo(
    name="目黒記念",
    date="2026年5月31日",
    venue="東京",
    race_number="12R",
    distance="2500m",
    surface="芝",
    conditions="目黒記念GII",
    start_time="17:00",
    url="",
)

# result.htmlから取得済み（着順, 枠, 馬番, 馬名, 性齢, 斤量, 騎手, horse_id）
ENTRIES_RAW = [
    (1,  3,  4, "ファイアンクランツ",  "牡4", "56.0", "レーン",   "2022104720"),
    (2,  4,  6, "ウィクトルウェルス",  "牡4", "57.0", "ルメール", "2022104655"),
    (3,  7, 11, "ダノンシーマ",        "牡4", "57.5", "川田将雅", "2022104645"),
    (4,  5,  8, "ミラージュナイト",    "牡4", "56.0", "西村淳也", "2022105109"),
    (5,  8, 14, "キングスコール",      "牡4", "55.0", "坂井瑠星", "2022104207"),
    (6,  5,  7, "アスクセクシーモア",  "牡4", "55.0", "北村友一", "2022105202"),
    (7,  7, 12, "キングズパレス",      "牡7", "57.0", "松岡正海", "2019104828"),
    (8,  6, 10, "マイネルケレリウス",  "牡6", "55.0", "丹内祐次", "2020105781"),
    (9,  1,  1, "アマキヒ",            "牡4", "56.0", "武豊",     "2022104615"),
    (10, 6,  9, "ハーツコンチェルト",  "牡6", "54.0", "横山武史", "2020105681"),
    (11, 3,  3, "ボーンディスウェイ",  "牡7", "57.0", "松山弘平", "2019104658"),
    (12, 8, 13, "ヴェルミセル",        "牝6", "54.0", "ゴンサレス","2020103945"),
    (13, 2,  2, "ショウナンバシット",  "牡6", "57.0", "浜中俊",   "2020103333"),
    (14, 4,  5, "ギャンブルルーム",    "牡5", "55.0", "幸英明",   "2021105559"),
]

RACE_DATE_CUTOFF = "2026/05/31"


def fetch_past_races(horse_id: str, max_races: int = 5, cutoff: str = None) -> list[str]:
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    time.sleep(0.5)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception as e:
        print(f"  [ERROR] {horse_id}: {e}")
        return []

    table = soup.find("table")
    if not table:
        return []
    rows = table.find_all("tr")
    if not rows:
        return []

    headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    def get_idx(name):
        try: return headers.index(name)
        except ValueError: return -1

    date_idx    = get_idx("日付")
    venue_idx   = get_idx("開催")
    rname_idx   = get_idx("レース名")
    nheads_idx  = get_idx("頭数")
    pos_idx     = get_idx("着順")
    dist_idx    = get_idx("距離")
    margin_idx  = get_idx("着差")
    corner_idx  = get_idx("通過")
    last3f_idx  = get_idx("上り")
    hw_idx      = get_idx("馬体重")

    recent = []
    for row in rows[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells or len(cells) < 10:
            continue
        def cell(idx):
            return cells[idx] if 0 <= idx < len(cells) else ""

        date_raw = cell(date_idx)
        dm = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_raw)
        if not dm:
            continue
        if cutoff and date_raw >= cutoff:
            continue
        date_jp = f"{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日"
        if len(recent) >= max_races:
            break

        vm = re.search(r"(東京|中山|阪神|京都|中京|新潟|福島|小倉|札幌|函館)", cell(venue_idx))
        venue = vm.group(1) if vm else ""

        rname_raw = cell(rname_idx)
        race_name = re.sub(r'\([^)]*\)', '', rname_raw).strip()
        gm = re.search(r'\((GI+|GII+|GIII+)\)', rname_raw)
        grade_str = gm.group(1) if gm else ""

        try:
            pos = int(cell(pos_idx))
        except ValueError:
            continue
        try:
            nheads = int(cell(nheads_idx))
        except ValueError:
            nheads = 0

        dist_surf = cell(dist_idx)
        dsm = re.match(r"(芝|ダ)(\d+)", dist_surf)
        surface = dsm.group(1) if dsm else ""
        dist_m  = dsm.group(2) if dsm else ""

        hwm = re.match(r"(\d{3,4})", cell(hw_idx))
        hw_str = f"{hwm.group(1)}kg" if hwm else ""

        try:
            last3f_str = f"3F {float(cell(last3f_idx))}"
        except ValueError:
            last3f_str = ""

        try:
            margin_val = abs(float(cell(margin_idx)))
            margin_str = f"({margin_val})"
        except ValueError:
            margin_str = "(0)"

        cm = re.match(r"(\d+)[-]", cell(corner_idx))
        corner_str = f"1角:{cm.group(1)}" if cm else ""

        text = (
            f"{date_jp}{venue}{race_name}{grade_str}"
            f"{pos}着{nheads}頭5番人気"
            f"{dist_m}{surface}{hw_str}{last3f_str}"
            f"{margin_str}{corner_str}"
        )
        recent.append(text)

    return recent


def fetch_bloodline(horse_id: str) -> tuple[str, str]:
    url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
    time.sleep(0.5)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception:
        return "", ""
    table = soup.find("table")
    if not table:
        return "", ""
    tds = table.find_all("td")
    if not tds:
        return "", ""
    raw = tds[0].get_text(strip=True)
    m = re.match(r"([^\d\[\(]+)", raw)
    sire = m.group(1).strip() if m else ""
    return sire, ""


def format_breakdown(d: ScoreBreakdown) -> tuple[str, str]:
    plus_parts, minus_parts = [], []
    for k, v in vars(d).items():
        if k == "manual_inner_post" or v == 0:
            continue
        label = _get_label(k, v)
        if v > 0:
            plus_parts.append(f"+{v:.1f}{label}")
        elif v < 0:
            minus_parts.append(f"{v:.1f}{label}")
    return " / ".join(plus_parts), " / ".join(minus_parts)


def main():
    print("=== 目黒記念2026 再検証 ===")
    print("全14頭の近走データをdb.netkeibaから取得します...\n")

    entries = []
    for (actual_rank, frame, horse_num, name, age_sex, weight, jockey, horse_id) in ENTRIES_RAW:
        print(f"  [{horse_num:2d}] {name} ({horse_id}) 近走取得中...")
        recent = fetch_past_races(horse_id, max_races=5, cutoff=RACE_DATE_CUTOFF)
        sire, bms = fetch_bloodline(horse_id)
        print(f"       近走{len(recent)}件  父={sire or '不明'}")
        entry = HorseEntry(
            frame_number   = str(frame),
            horse_number   = str(horse_num),
            horse_name     = name,
            record         = "",
            prize_money    = "",
            owner          = "",
            trainer        = "",
            age_sex        = age_sex,
            weight_carried = weight,
            jockey         = jockey,
            recent_races   = recent,
            sire           = sire,
            bms            = bms,
        )
        entries.append((actual_rank, entry))

    print("\n採点計算中...")
    entry_list = [e for _, e in entries]
    results = score_all(entry_list, RACE_INFO)

    scored = [(entry, d) for entry, d in results]
    scored.sort(key=lambda x: x[1].total, reverse=True)

    rank_map = {e.horse_name: r for r, e in entries}

    print("\n" + "=" * 75)
    print(f"{'':2} {'順':>3} {'実着':>3} {'枠':>2} {'馬番':>3} {'馬名':<18} {'スコア':>6}  加点内訳")
    print("-" * 75)

    csv_rows = []
    for i, (entry, d) in enumerate(scored, 1):
        actual_rank = rank_map.get(entry.horse_name, "?")
        score = d.total
        plus_str, minus_str = format_breakdown(d)
        mark = "★" if isinstance(actual_rank, int) and actual_rank <= 3 else "  "
        print(f"{mark}{i:2d}位  実{actual_rank:>2}着 {entry.frame_number:>2}枠 {entry.horse_number:>2}番 "
              f"{entry.horse_name:<18} {score:+.1f}  {plus_str}"
              + (f"  /  {minus_str}" if minus_str else ""))
        csv_rows.append({
            "順位": i, "実際着順": actual_rank,
            "枠": entry.frame_number, "馬番": entry.horse_number,
            "馬名": entry.horse_name,
            "合計スコア": f"+{score:.1f}" if score >= 0 else f"{score:.1f}",
            "加点内訳": plus_str, "減点内訳": minus_str,
        })

    out_path = "/Users/du/Documents/競馬予想システム/score_202605021212_東京_目黒記念.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["順位", "実際着順", "枠", "馬番", "馬名", "合計スコア", "加点内訳", "減点内訳"])
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\nCSV保存: {out_path}")

    top5_actual = [rank_map[e.horse_name] for e, _ in scored[:5]]
    in3 = sum(1 for r in top5_actual if isinstance(r, int) and r <= 3)
    print(f"\n上位5頭の実際着順: {top5_actual}")
    print(f"上位5頭に入着3頭含む: {in3}頭")


if __name__ == "__main__":
    main()
