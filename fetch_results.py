"""
レース結果を JRA 公式サイトから自動取得して CSV に追記するスクリプト

使い方:
  python3 fetch_results.py               # 今日
  python3 fetch_results.py --date 2026-06-13
  python3 fetch_results.py --all         # results/以下の全日付
  python3 fetch_results.py --debug       # HTML 構造をダンプして確認

race_id の取得方法（優先順）:
  1. CSV の ■レース情報 行に保存済み（weekend_predict.py 実行後）
  2. db.netkeiba 全レースリスト（日付が過去の場合）
  3. 取得不可 → スキップ
"""
import sys, argparse, csv, re, datetime, time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from jra_scraper import build_jra_result_url, get_race_result, fetch_html

RESULTS_DIR = Path(__file__).parent / "results"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

VENUE_CODE = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


def get_all_race_ids(date: datetime.date) -> dict[tuple, str]:
    """
    db.netkeiba から全レースの race_id を取得して {(venue, race_num): race_id} で返す。
    当日は race_list_sub（後半レースのみ）も合わせて使う。
    """
    race_map: dict[tuple, str] = {}

    def _scrape(url: str):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                return
            soup = BeautifulSoup(r.content, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                rid = None
                if "shutuba.html?race_id=" in href:
                    rid = href.split("race_id=")[1].split("&")[0]
                else:
                    m = re.search(r"/race/(\d{12})/", href)
                    if m:
                        rid = m.group(1)
                if rid and len(rid) == 12:
                    vc = rid[4:6]
                    rn = int(rid[10:12])
                    vn = VENUE_CODE.get(vc, "?")
                    race_map[(vn, rn)] = rid
        except Exception:
            pass

    # db.netkeiba（全レース一覧）
    _scrape(f"https://db.netkeiba.com/race/list/{date:%Y%m%d}/")
    # race_list_sub（当日用：未公開でも race_id を持つ）
    _scrape(f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date:%Y%m%d}")

    return race_map


def read_race_id_from_csv(csv_path: Path) -> str:
    """■レース情報 行から race_id を取得する（2列目）"""
    with open(csv_path, encoding="utf-8-sig") as f:
        for line in f:
            parts = list(csv.reader([line.strip()]))[0]
            if parts and parts[0] == "■レース情報" and len(parts) >= 3 and parts[2].isdigit():
                return parts[2]
    return ""


def read_predictions(csv_path: Path) -> dict[str, int]:
    """CSV から {馬名: 予想順位} を返す"""
    pred = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = list(csv.reader([line]))[0]
            if len(parts) >= 4 and parts[0].strip().isdigit():
                pred[parts[3]] = int(parts[0])
    return pred


def already_has_result(csv_path: Path) -> bool:
    with open(csv_path, encoding="utf-8-sig") as f:
        return "■レース結果（実際）" in f.read()


def append_result_to_csv(csv_path: Path, results, race_name: str,
                          surface_dist: str, date_str: str, pred: dict,
                          overwrite: bool = False):
    # 上書き時は既存の■レース結果（実際）セクションを除去
    if overwrite:
        with open(csv_path, encoding="utf-8-sig") as f:
            content = f.read()
        # ■レース結果（実際）以降を切り取る
        idx = content.find("\n■レース結果（実際）")
        if idx == -1:
            idx = content.find("■レース結果（実際）")
        if idx != -1:
            content = content[:idx]
        with open(csv_path, "w", encoding="utf-8-sig") as f:
            f.write(content)

    lines = [
        "",
        f"■レース結果（実際）,{race_name},{surface_dist},{date_str}",
        "着順,馬番,馬名,タイム,馬体重(増減),人気,予想順位",
    ]
    for r in results:
        diff_str   = f"{r.weight_diff:+d}" if r.weight_diff != 0 else "0"
        pred_rank  = pred.get(r.horse_name)
        pred_str   = f"予想{pred_rank}位" if pred_rank else "予想外"
        weight_str = f"{r.horse_weight}({diff_str})" if r.horse_weight else ""
        lines.append(
            f"{r.rank},{r.horse_number},{r.horse_name},"
            f"{r.time},{weight_str},{r.popularity}人気,{pred_str}"
        )

    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        f.write("\n" + "\n".join(lines) + "\n")

    print(f"    → {len(results)}頭の結果を追記")


def debug_dump(url: str):
    soup = fetch_html(url)
    table = soup.find("table", class_="basic")
    if not table:
        print("  [DEBUG] table.basic が見つかりません")
        for i, t in enumerate(soup.find_all("table")[:3]):
            print(f"  [DEBUG] table[{i}] class={t.get('class')} 行数={len(t.find_all('tr'))}")
        return
    print(f"  [DEBUG] table.basic 行数: {len(table.find_all('tr'))}")
    for row in table.find_all("tr")[:4]:
        cells = row.find_all(["td", "th"])
        print("  [DEBUG] | " + " | ".join(
            f"{c.get('class','?')}:{c.get_text(strip=True)[:20]}" for c in cells[:7]
        ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",      default="",         help="対象日付 (例: 2026-06-13)")
    parser.add_argument("--all",       action="store_true", help="results/以下の全日付")
    parser.add_argument("--debug",     action="store_true", help="HTML 構造をダンプ")
    parser.add_argument("--overwrite", action="store_true", help="取得済み結果を上書き（頭数不足時の再取得）")
    args = parser.parse_args()

    if args.all:
        dates = sorted(
            datetime.date.fromisoformat(d.name)
            for d in RESULTS_DIR.iterdir()
            if d.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}", d.name)
        )
    elif args.date:
        dates = [datetime.date.fromisoformat(args.date)]
    else:
        dates = [datetime.date.today()]

    for target_date in dates:
        print(f"\n{'='*55}")
        print(f"  {target_date}  結果自動取得")
        print(f"{'='*55}")

        date_dir = RESULTS_DIR / str(target_date)
        if not date_dir.exists():
            print(f"  フォルダなし: {date_dir}")
            continue

        # フォールバック用 race_id マップ（db.netkeiba）
        fallback_map = get_all_race_ids(target_date)
        print(f"  フォールバックmap: {len(fallback_map)} レース取得")

        csv_files = sorted(date_dir.glob("*/score_*.csv"))
        print(f"  CSV: {len(csv_files)} 件\n")

        for csv_path in csv_files:
            venue = csv_path.parent.name
            fname = csv_path.stem

            # ファイル名から race_num・surface_dist・race_name を抽出
            m_new = re.search(r'_(\d+)R_(芝\d+m|ダート\d+m|障害\d+m)_(.+?)(?:_★|$)', fname)
            m_old = re.search(r'_(\d+)R_(.+?)(?:_★|$)', fname)
            if m_new:
                race_num     = int(m_new.group(1))
                surface_dist = m_new.group(2)
                race_name    = m_new.group(3).replace("_", " ")
            elif m_old:
                race_num     = int(m_old.group(1))
                surface_dist = ""
                race_name    = m_old.group(2).replace("_", " ")
            else:
                continue

            print(f"  {venue} {race_num}R {surface_dist} {race_name}")

            if already_has_result(csv_path):
                if not args.overwrite:
                    print(f"    → スキップ（結果取得済み）")
                    continue
                print(f"    → 上書き取得（--overwrite）")

            # race_id: CSV 保存 > フォールバックmap
            race_id = read_race_id_from_csv(csv_path)
            if not race_id:
                entry = fallback_map.get((venue, race_num))
                race_id = entry if entry else ""

            if not race_id:
                print(f"    → race_id 不明（スキップ）")
                continue

            result_url = build_jra_result_url(race_id, target_date)
            print(f"    URL: {result_url}")

            if args.debug:
                debug_dump(result_url)
                time.sleep(1)
                continue

            results = get_race_result(result_url)
            if not results:
                print(f"    → 結果未公開またはパース失敗")
                time.sleep(1)
                continue

            pred = read_predictions(csv_path)
            append_result_to_csv(csv_path, results, race_name, surface_dist,
                                  str(target_date), pred,
                                  overwrite=args.overwrite and already_has_result(csv_path))
            time.sleep(1.5)

        print(f"\n  完了")


if __name__ == "__main__":
    main()
