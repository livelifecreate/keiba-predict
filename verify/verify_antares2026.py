"""
アンタレスS2026（2026/4/18 阪神ダ1800m G3 16頭）再検証
race_id: 202609020711
"""
import re, sys, time, csv, requests
from bs4 import BeautifulSoup

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from scorer import score_all, ScoreBreakdown, _get_label
from jra_scraper import HorseEntry, RaceInfo

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

RACE_INFO = RaceInfo(
    name="アンタレスS",
    date="2026年4月18日",
    venue="阪神",
    race_number="7R",
    distance="1800m",
    surface="ダ",
    conditions="アンタレスSGIII",
    start_time="15:35",
    url="",
)

ENTRIES_RAW = [
    # (着順, 枠, 馬番, 馬名, 性齢, 斤量, 騎手, horse_id)
    (1,  2,  4, "ムルソー",           "牡5", "57", "坂井瑠星",  "2021103020"),
    (2,  1,  2, "モックモック",       "牡6", "57", "武豊",      "2020100061"),
    (3,  3,  5, "ハグ",               "牡4", "57", "高杉吏麒",  "2022106925"),
    (4,  2,  3, "タガノバビロン",     "牡4", "57", "松山弘平",  "2022106553"),
    (5,  4,  8, "サンデーファンデー", "牡6", "58", "角田大和",  "2020104136"),
    (6,  1,  1, "ブライアンセンス",   "牡6", "57", "岩田望来",  "2020106565"),
    (7,  6, 11, "ハピ",               "牡7", "57", "幸英明",    "2019100630"),
    (8,  7, 14, "シュラザック",       "牡4", "57", "古川吉洋",  "2022102117"),
    (9,  8, 15, "ロードラビリンス",   "牡4", "57", "鮫島克駿",  "2022100653"),
    (10, 5, 10, "ジェイパームス",     "セ6", "57", "レーン",    "2020103331"),
    (11, 4,  7, "ペイシャエス",       "牡7", "58", "田口貫太",  "2019104245"),
    (12, 8, 16, "ジューンアヲニヨシ", "牡6", "57", "浜中俊",    "2020100912"),
    (13, 7, 13, "メイショウズイウン", "牡4", "57", "太宰啓介",  "2022100154"),
    (14, 6, 12, "サイモンザナドゥ",   "牡6", "57", "池添謙一",  "2020104497"),
    (15, 3,  6, "ルシュヴァルドール", "牡5", "57", "西村淳也",  "2021105630"),
    (16, 5,  9, "ピカピカサンダー",   "牡4", "57", "三浦皇成",  "2022105979"),
]

RACE_DATE_CUTOFF = "2026/04/18"


def fetch_past_races(horse_id, max_races=5, cutoff=None):
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    time.sleep(0.5)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception as e:
        print(f"  [ERROR] {e}"); return []
    table = soup.find("table")
    if not table: return []
    rows = table.find_all("tr")
    if not rows: return []
    headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    def gi(n):
        try: return headers.index(n)
        except: return -1
    di, vi, ri, ni, pi, dsti, mi, ci, l3i, hwi = (
        gi("日付"), gi("開催"), gi("レース名"), gi("頭数"), gi("着順"),
        gi("距離"), gi("着差"), gi("通過"), gi("上り"), gi("馬体重")
    )
    recent = []
    for row in rows[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells or len(cells) < 10: continue
        def cell(i): return cells[i] if 0 <= i < len(cells) else ""
        date_raw = cell(di)
        dm = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_raw)
        if not dm: continue
        if cutoff and date_raw >= cutoff: continue
        date_jp = f"{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日"
        if len(recent) >= max_races: break
        vm = re.search(r"(東京|中山|阪神|京都|中京|新潟|福島|小倉|札幌|函館)", cell(vi))
        venue = vm.group(1) if vm else ""
        rname_raw = cell(ri)
        race_name = re.sub(r'\([^)]*\)', '', rname_raw).strip()
        gm = re.search(r'\((GI+|GII+|GIII+)\)', rname_raw)
        grade_str = gm.group(1) if gm else ""
        try: pos = int(cell(pi))
        except ValueError: continue
        try: nheads = int(cell(ni))
        except ValueError: nheads = 0
        dsm = re.match(r"(芝|ダ)(\d+)", cell(dsti))
        surface = dsm.group(1) if dsm else ""
        dist_m  = dsm.group(2) if dsm else ""
        hwm = re.match(r"(\d{3,4})", cell(hwi))
        hw_str = f"{hwm.group(1)}kg" if hwm else ""
        try: l3f_str = f"3F {float(cell(l3i))}"
        except ValueError: l3f_str = ""
        try: mg_str = f"({abs(float(cell(mi)))})"
        except ValueError: mg_str = "(0)"
        corner_parts = re.findall(r"\d+", cell(ci))
        corner_str = f"1角:{corner_parts[0]} 4角:{corner_parts[-1]}" if len(corner_parts) >= 2 else (f"1角:{corner_parts[0]}" if corner_parts else "")
        recent.append(
            f"{date_jp}{venue}{race_name}{grade_str}"
            f"{pos}着{nheads}頭5番人気"
            f"{dist_m}{surface}{hw_str}{l3f_str}"
            f"{mg_str}{corner_str}"
        )
    return recent


def fetch_sire(horse_id):
    url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
    time.sleep(0.5)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except: return ""
    tbl = soup.find("table")
    if not tbl: return ""
    tds = tbl.find_all("td")
    if not tds: return ""
    m = re.match(r"([^\d\[\(]+)", tds[0].get_text(strip=True))
    return m.group(1).strip() if m else ""


def fmt(d: ScoreBreakdown):
    plus_, minus_ = [], []
    for k, v in vars(d).items():
        if k == "manual_inner_post" or v == 0: continue
        lbl = _get_label(k, v)
        (plus_ if v > 0 else minus_).append(f"{'+' if v>0 else ''}{v:.1f}{lbl}")
    return " / ".join(plus_), " / ".join(minus_)


def main():
    print("=== アンタレスS2026 再検証 ===\n")
    entries = []
    for (rank, frame, hnum, name, agesex, weight, jockey, hid) in ENTRIES_RAW:
        print(f"  [{hnum:2d}] {name} 近走取得中...")
        recent = fetch_past_races(hid, max_races=5, cutoff=RACE_DATE_CUTOFF)
        sire = fetch_sire(hid)
        print(f"       近走{len(recent)}件  父={sire or '不明'}")
        entries.append((rank, HorseEntry(
            frame_number=str(frame), horse_number=str(hnum),
            horse_name=name, record="", prize_money="", owner="", trainer="",
            age_sex=agesex, weight_carried=weight, jockey=jockey,
            recent_races=recent, sire=sire, bms="",
        )))

    print("\n採点計算中...")
    results = score_all([e for _, e in entries], RACE_INFO)
    scored = sorted(results, key=lambda x: x[1].total, reverse=True)
    rank_map = {e.horse_name: r for r, e in entries}

    print("\n" + "=" * 78)
    print(f"{'':2} {'順':>3} {'実着':>3} {'枠':>2} {'馬番':>3} {'馬名':<18} {'スコア':>6}  加点内訳")
    print("-" * 78)
    csv_rows = []
    for i, (entry, d) in enumerate(scored, 1):
        ar = rank_map.get(entry.horse_name, "?")
        sc = d.total
        ps, ms = fmt(d)
        mark = "★" if isinstance(ar, int) and ar <= 3 else "  "
        print(f"{mark}{i:2d}位  実{ar:>2}着 {entry.frame_number:>2}枠 {entry.horse_number:>2}番 "
              f"{entry.horse_name:<18} {sc:+.1f}  {ps}" + (f"  /  {ms}" if ms else ""))
        csv_rows.append({"順位": i, "実際着順": ar, "枠": entry.frame_number,
                         "馬番": entry.horse_number, "馬名": entry.horse_name,
                         "合計スコア": f"+{sc:.1f}" if sc >= 0 else f"{sc:.1f}",
                         "加点内訳": ps, "減点内訳": ms})

    out = "/Users/du/Documents/競馬予想システム/score_202609020711_阪神_アンタレスS.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=list(csv_rows[0].keys())).writeheader()
        csv.DictWriter(f, fieldnames=list(csv_rows[0].keys())).writerows(csv_rows)
    print(f"\nCSV保存: {out}")

    top5 = [rank_map[e.horse_name] for e, _ in scored[:5]]
    in3 = sum(1 for r in top5 if isinstance(r, int) and r <= 3)
    print(f"上位5頭の実際着順: {top5}")
    print(f"上位5頭に入着3頭含む: {in3}頭")


if __name__ == "__main__":
    main()
