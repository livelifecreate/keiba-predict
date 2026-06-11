"""
日本ダービー2026（2026/5/31 東京芝2400m）再検証スクリプト
result.html取得済みhorse_idを使いdb.netkeibaから近走データを取得してスコア計算
"""
import re
import sys
import time
import csv
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from scorer import (
    parse_past_race, score_all, parse_race_class,
    SCORE_LABELS, _get_label, ScoreBreakdown,
)
from jra_scraper import HorseEntry, RaceInfo

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# ── レース情報 ──────────────────────────────────────────────
RACE_INFO = RaceInfo(
    name="日本ダービー",
    date="2026年5月31日",
    venue="東京",
    race_number="11R",
    distance="2400m",
    surface="芝",
    conditions="東京優駿GI",
    start_time="15:40",
    url="",
)

# ── 出走馬（result.htmlから取得済み）──────────────────────
ENTRIES_RAW = [
    # (着順, 枠, 馬番, 馬名, 騎手, horse_id)  ← db.netkeibaで確認済み着順
    (1,  8, 17, "ロブチェン",       "松山弘平",   "2023107089"),
    (2,  7, 13, "パントルナイーフ",  "ルメール",   "2023107377"),
    (3,  3,  5, "バステール",       "川田将雅",   "2023107247"),
    (4,  7, 14, "ゴーイントゥスカイ","北村友一",   "2023105378"),
    (5,  1,  2, "マテンロウゲイル",  "横山典弘",   "2023100946"),
    (6,  2,  4, "アルトラムス",     "クリスチャン","2023103480"),
    (7,  6, 11, "リアライズシリウス","団野大成",   "2023103604"),
    (8,  1,  1, "ライヒスアドラー",  "戸崎圭太",   "2023103687"),
    (9,  3,  6, "コンジェスタス",   "松岡正海",   "2023106963"),
    (10, 6, 12, "アスクエジンバラ",  "浜中俊",     "2023106400"),
    (11, 5,  9, "アウダーシア",     "岩田望来",   "2023107321"),
    (12, 7, 15, "フォルテアンジェロ","荻野極",     "2023107345"),
    (13, 4,  7, "メイショウハチコウ","坂井瑠星",   "2023102039"),
    (14, 8, 18, "エムズビギン",     "西村淳也",   "2023107127"),
    (15, 2,  3, "ケントン",         "横山武史",   "2023103824"),
    (16, 8, 16, "グリーンエナジー",  "池添謙一",   "2023105456"),
    (17, 4,  8, "ショウナンガルフ",  "田辺裕信",   "2023105332"),
    (18, 5, 10, "ジャスティンビスタ","武豊",       "2023102807"),
]

# 再検証基準日：本番レース当日（この日以降のデータは除外）
RACE_DATE_CUTOFF = "2026/05/31"


def fetch_past_races(horse_id: str, max_races: int = 5, cutoff: str = None) -> list[str]:
    """db.netkeiba.com/horse/result/{id}/ から近走データを取得して
    parse_past_race互換テキストのリストを返す"""
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

        # 日付
        date_raw = cell(date_idx)
        dm = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_raw)
        if not dm:
            continue
        # cutoffより前のデータのみ使用（本番レース当日のデータを除外）
        if cutoff and date_raw >= cutoff:
            continue
        date_jp = f"{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日"
        if len(recent) >= max_races:
            break

        # 競馬場
        vm = re.search(r"(東京|中山|阪神|京都|中京|新潟|福島|小倉|札幌|函館)", cell(venue_idx))
        venue = vm.group(1) if vm else ""

        # レース名（グレード表記付き）
        rname_raw = cell(rname_idx)
        race_name = re.sub(r'\([^)]*\)', '', rname_raw).strip()
        gm = re.search(r'\((GI+|GII+|GIII+)\)', rname_raw)
        grade_str = gm.group(1) if gm else ""

        # 着順（中止・除外はスキップ）
        try:
            pos = int(cell(pos_idx))
        except ValueError:
            continue

        # 頭数
        try:
            nheads = int(cell(nheads_idx))
        except ValueError:
            nheads = 0

        # 距離・馬場
        dist_surf = cell(dist_idx)
        dsm = re.match(r"(芝|ダ)(\d+)", dist_surf)
        surface = dsm.group(1) if dsm else ""
        dist_m  = dsm.group(2) if dsm else ""

        # 馬体重
        hwm = re.match(r"(\d{3,4})", cell(hw_idx))
        hw_str = f"{hwm.group(1)}kg" if hwm else ""

        # 上がり3F
        try:
            last3f_str = f"3F {float(cell(last3f_idx))}"
        except ValueError:
            last3f_str = ""

        # 着差（abs値）
        try:
            margin_val = abs(float(cell(margin_idx)))
            margin_str = f"({margin_val})"
        except ValueError:
            margin_str = "(0)"

        # 1コーナー通過順
        corner_raw = cell(corner_idx)
        cm = re.match(r"(\d+)[-]", corner_raw)
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
    """db.netkeiba.com/horse/ped/{id}/ から父名を取得（母父は構造が複雑なため省略）"""
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
    # [0]が父（最初のb_mlまたは最初のtd）
    raw = tds[0].get_text(strip=True)
    m = re.match(r"([^\d\[\(]+)", raw)
    sire = m.group(1).strip() if m else ""
    return sire, ""


def build_entry(rank: int, frame: int, horse_num: int, name: str, jockey: str,
                horse_id: str, age_sex: str = "牡3") -> HorseEntry:
    """db.netkeibaから近走取得してHorseEntryを構築"""
    print(f"  [{horse_num:2d}] {name} ({horse_id}) 近走取得中...")
    recent = fetch_past_races(horse_id, max_races=5, cutoff=RACE_DATE_CUTOFF)
    sire, bms = fetch_bloodline(horse_id)
    print(f"       近走{len(recent)}件  父={sire or '不明'} 母父={bms or '不明'}")
    return HorseEntry(
        frame_number   = str(frame),
        horse_number   = str(horse_num),
        horse_name     = name,
        record         = "",
        prize_money    = "",
        owner          = "",
        trainer        = "",
        age_sex        = age_sex,
        weight_carried = "57.0",
        jockey         = jockey,
        recent_races   = recent,
        sire           = sire,
        bms            = bms,
    )


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
    print("=== 日本ダービー2026 再検証 ===")
    print("全18頭の近走データをdb.netkeibaから取得します...\n")

    entries = []
    for (actual_rank, frame, horse_num, name, jockey, horse_id) in ENTRIES_RAW:
        entry = build_entry(actual_rank, frame, horse_num, name, jockey, horse_id)
        entries.append((actual_rank, entry))

    print("\n採点計算中...")
    entry_list = [e for _, e in entries]
    results = score_all(entry_list, RACE_INFO)

    # スコアでソート
    scored = [(entry, d) for entry, d in results]
    scored.sort(key=lambda x: x[1].total, reverse=True)

    # 着順マップ
    rank_map = {e.horse_name: r for r, e in entries}

    print("\n" + "=" * 70)
    print(f"{'順位':>3} {'実着':>3} {'枠':>2} {'馬番':>3} {'馬名':<16} {'スコア':>7} {'加点内訳'}")
    print("-" * 70)

    csv_rows = []
    for i, (entry, d) in enumerate(scored, 1):
        actual_rank = rank_map.get(entry.horse_name, "?")
        score = d.total
        plus_str, minus_str = format_breakdown(d)
        breakdown = plus_str + ("  /  " + minus_str if minus_str else "")
        mark = "★" if actual_rank <= 3 else "  "
        print(f"{mark}{i:2d}位  実{actual_rank:>2}着 {entry.frame_number:>2}枠 {entry.horse_number:>2}番 {entry.horse_name:<16} {score:+.1f}  {breakdown}")
        csv_rows.append({
            "順位": i, "実際着順": actual_rank,
            "枠": entry.frame_number, "馬番": entry.horse_number,
            "馬名": entry.horse_name,
            "合計スコア": f"+{score:.1f}" if score >= 0 else f"{score:.1f}",
            "加点内訳": plus_str, "減点内訳": minus_str,
        })

    # CSV保存
    out_path = "/Users/du/Documents/競馬予想システム/score_202605021211_東京_日本ダービー.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["順位", "実際着順", "枠", "馬番", "馬名", "合計スコア", "加点内訳", "減点内訳"])
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\nCSV保存: {out_path}")

    # サマリー
    top5_actual = [rank_map[e.horse_name] for e, _ in scored[:5]]
    in3 = sum(1 for r in top5_actual if r <= 3)
    print(f"\n上位5頭の実際着順: {top5_actual}")
    print(f"上位5頭に入着3頭含む: {in3}頭")


if __name__ == "__main__":
    main()
