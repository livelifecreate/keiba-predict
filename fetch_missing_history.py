"""
バックテスト用：馬歴データが欠落している馬分を補完する。
cache/race_result/ の全レースをスキャンし、7日以内の horse_history がない馬について
db.netkeiba.com/horse/result/{id}/ から全成績を取得。
レース当日より前の成績のみに絞って cache_set する。
"""
import sys, json, re, time, requests
sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from pathlib import Path
from bs4 import BeautifulSoup
from datetime import datetime
from cache_store import cache_get_before, cache_set

CACHE_RACE = Path('/Users/du/Documents/競馬予想システム/cache/race_result')
TARGET_CLASSES = {"2勝クラス", "3勝クラス", "OP", "重賞"}

VENUE_MAP = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
    "05": "東京", "06": "中山", "07": "中京", "08": "京都",
    "09": "阪神", "10": "小倉",
}


def parse_venue(kaisan: str) -> str:
    """'2阪神4' → '阪神'  /  'メイダン' → 'メイダン'"""
    m = re.sub(r'^\d+', '', kaisan)   # 先頭の数字を除去
    m = re.sub(r'\d+$', '', m)        # 末尾の数字を除去
    return m.strip() if m.strip() else kaisan


def parse_race_grade(race_name: str) -> tuple[str, str]:
    """'大阪杯(GI)' → ('大阪杯', 'GI')"""
    m = re.search(r'\((G[I123]+|JpnI+|L|OP|オープン)\)$', race_name)
    if m:
        grade = m.group(1)
        name = race_name[:m.start()].strip()
        return name, grade
    return race_name, ""


def date_netkeiba_to_japanese(date_str: str) -> str:
    """'2026/04/05' → '2026年4月5日'"""
    try:
        dt = datetime.strptime(date_str, "%Y/%m/%d")
        return f"{dt.year}年{dt.month}月{dt.day}日"
    except ValueError:
        return date_str


def fetch_full_history(horse_id: str) -> list[dict]:
    """netkeiba から馬の全成績を取得してリストで返す"""
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    try:
        time.sleep(0.8)
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception as e:
        print(f"    fetch error {horse_id}: {e}")
        return []

    table = soup.find("table", class_="db_h_race_results") or soup.find("table")
    if not table:
        return []
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]

    def idx(name):
        return headers.index(name) if name in headers else -1

    results = []
    for row in rows[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells:
            continue

        def get(col):
            i = idx(col)
            return cells[i] if 0 <= i < len(cells) else ""

        date_raw = get("日付")          # "2026/04/05"
        kaisan   = get("開催")          # "2阪神4"
        race_raw = get("レース名")      # "大阪杯(GI)"
        pos_raw  = get("着順")          # "2" or "取消" etc
        field    = get("頭数")          # "15"
        pop      = get("人気")          # "3"
        dist_raw = get("距離")          # "芝2000"
        track    = get("馬場")          # "良"
        margin   = get("着差")          # "0.1" or "クビ" etc
        corner   = get("通過")          # "1-1-1-1"
        last3f   = get("上り")          # "35.6"
        weight   = get("馬体重")        # "500(-12)"

        if not date_raw or not re.match(r'\d{4}/\d{2}/\d{2}', date_raw):
            continue

        results.append({
            "date_raw": date_raw,
            "kaisan":   kaisan,
            "race_raw": race_raw,
            "pos_raw":  pos_raw,
            "field":    field,
            "pop":      pop,
            "dist_raw": dist_raw,
            "track":    track,
            "margin":   margin,
            "corner":   corner,
            "last3f":   last3f,
            "weight":   weight,
        })
    return results


def format_as_history_string(rec: dict) -> str | None:
    """
    parse_past_race() が読める文字列に変換。
    例: "2026年4月5日阪神大阪杯GI2着15頭3番人気2000芝500kg3F 35.6(0.1)1角:1 4角:1"
    """
    # 着順が数字でない場合はスキップ
    try:
        pos = int(rec["pos_raw"])
    except (ValueError, TypeError):
        return None

    date_jp = date_netkeiba_to_japanese(rec["date_raw"])
    venue   = parse_venue(rec["kaisan"])
    rname, grade = parse_race_grade(rec["race_raw"])

    # 距離・コース面
    dist_m = re.search(r'(\d+)', rec["dist_raw"])
    surface_char = "芝" if rec["dist_raw"].startswith("芝") else "ダ"
    dist_str = f"{dist_m.group(1)}{surface_char}" if dist_m else ""

    # 馬体重
    w_m = re.search(r'(\d+)', rec["weight"])
    weight_str = f"{w_m.group(1)}kg" if w_m else ""

    # 上がり3F
    try:
        lf = float(rec["last3f"])
        lf_str = f"3F {lf:.1f}"
    except (ValueError, TypeError):
        lf_str = ""

    # 着差（秒に変換できるものだけ）
    try:
        mg = float(rec["margin"])
        mg_str = f"({mg:.1f})"
    except (ValueError, TypeError):
        mg_str = "(0)" if rec["margin"] in ("", "0", "同着") else ""

    # コーナー通過（1角と4角）
    corners = rec["corner"].split("-")
    c1 = corners[0].strip() if corners else ""
    c4 = corners[-1].strip() if corners else ""
    corner_str = ""
    if c1 and re.match(r'\d+', c1):
        corner_str = f"1角:{c1} 4角:{c4}"

    parts = [
        date_jp, venue, f"{rname}{grade}",
        f"{pos}着", f"{rec['field']}頭",
        f"{rec['pop']}番人気" if rec['pop'] else "",
        dist_str, weight_str, lf_str, mg_str, corner_str,
    ]
    return "".join(p for p in parts if p)


def cutoff_to_comparable(cutoff: str) -> str:
    """'2026/06/14' → '2026/06/14' (そのまま比較可能)"""
    return cutoff


def main():
    files = sorted(CACHE_RACE.glob("*.json"))
    total = len(files)
    filled = 0
    skipped = 0
    already = 0

    # 全馬×全レースで「欠落している」リストを収集
    missing: list[tuple[str, str, str]] = []  # (horse_id, cutoff, race_label)

    print("欠落チェック中...")
    seen = set()
    for f in files:
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if data.get("race_class") not in TARGET_CLASSES:
            continue
        if data.get("surface") not in ("芝", "ダ"):
            continue

        date_str = data["date"]
        dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
        if not dm:
            continue
        cutoff = f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}"

        for e in data["entries"]:
            hid = e.get("horse_id", "")
            if not hid:
                continue
            key = (hid, cutoff)
            if key in seen:
                continue
            seen.add(key)
            existing = cache_get_before("horse_history", hid, cutoff, max_days_back=7)
            if existing:
                already += 1
            else:
                missing.append((hid, cutoff, f"{date_str} {data['race_name']}"))

    print(f"  既にキャッシュあり: {already}件")
    print(f"  取得が必要:        {len(missing)}件（ユニーク馬×レース日）")

    if not missing:
        print("補完なし、終了。")
        return

    # ユニーク horse_id 単位でまとめてフェッチ
    horse_dates: dict[str, list[str]] = {}
    for hid, cutoff, _ in missing:
        horse_dates.setdefault(hid, []).append(cutoff)

    print(f"\nユニーク馬数: {len(horse_dates)}頭 → netkeiba取得開始\n")

    for i, (hid, cutoffs) in enumerate(horse_dates.items()):
        if i % 20 == 0:
            print(f"  {i}/{len(horse_dates)}頭処理中...", flush=True)

        raw_records = fetch_full_history(hid)
        if not raw_records:
            skipped += 1
            continue

        # 各レース日ごとにフィルタしてキャッシュ
        for cutoff in cutoffs:
            pre_records = [
                rec for rec in raw_records
                if rec["date_raw"] < cutoff.replace("/", "/")  # "2026/01/15" < "2026/06/14"
            ]
            if not pre_records:
                continue

            history_strings = []
            for rec in pre_records[:5]:  # 直近5走
                s = format_as_history_string(rec)
                if s:
                    history_strings.append(s)

            if history_strings:
                cache_set("horse_history", f"{hid}_{cutoff}", history_strings)
                filled += 1

    print(f"\n完了: 補完={filled}件 / スキップ={skipped}件")


if __name__ == "__main__":
    # まず3頭だけテスト
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="3頭だけテスト実行")
    parser.add_argument("--run", action="store_true", help="本番実行")
    args = parser.parse_args()

    if args.test:
        test_horses = [
            ("2021103272", "2026/06/14", "メイショウタバル 宝塚記念"),
            ("2021100651", "2026/06/14", "ファミリータイム 宝塚記念"),
            ("2022105102", "2026/06/14", "クロワデュノール 宝塚記念"),
        ]
        for hid, cutoff, label in test_horses:
            print(f"\n--- {label} ---")
            recs = fetch_full_history(hid)
            pre = [r for r in recs if r["date_raw"] < cutoff]
            print(f"  全{len(recs)}走 → {cutoff}前: {len(pre)}走")
            for rec in pre[:5]:
                s = format_as_history_string(rec)
                print(f"  → {s}")
    elif args.run:
        main()
    else:
        print("--test か --run を指定してください")
