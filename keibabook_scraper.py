"""
競馬ブックweb 調教データスクレイパー
使い方:
  python3 keibabook_scraper.py <URL> [--output <CSVファイル名>]

例:
  python3 keibabook_scraper.py https://p.keibabook.co.jp/cyuou/cyokyo/0/0/202603040111
  python3 keibabook_scraper.py https://p.keibabook.co.jp/cyuou/cyokyo/0/0/202603040111 --output training_安田記念.csv

クッキー管理:
  初回 or 期限切れ時は keibabook_cookie.txt にクッキー文字列を貼り付ける
  (競馬ブックで F12 → Network → リクエスト右クリック → Copy as cURL → Cookie 部分をコピー)
"""

import re
import sys
import csv
import requests
from pathlib import Path
from bs4 import BeautifulSoup

COOKIE_FILE = Path(__file__).parent / "keibabook_cookie.txt"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

# 矢印 → 状態スコアのベース（→は中立=3で解説スコアに委ねる）
ARROW_SCORE = {
    "↑↑": 5, "⇑": 5,
    "↑": 4,
    "↗": 4,   # やや上昇（kakusuji1keta）
    "→": 3,
    "↘": 2,   # やや下降
    "↓": 2,
    "↓↓": 1, "⇓": 1,
}

# 坂路コース判定（最終1Fの基準を緩めに設定）
SAKARO_COURSES = {"坂", "坂路"}

# 攻め解説キーワード → スコア加算値
# ルール: 長いフレーズを短いフレーズより先にマッチさせる（dict挿入順=評価順）
# ネガティブフレーズが先にマッチしたセグメントは短いPOSにもヒットしてしまうため、
# ネガ打ち消しフレーズをNEGに入れてPOSの+を相殺する方式を採用。
SEME_POS = {
    # +2（明確に良い）
    "かなり具合": 2, "雰囲気は上々": 2, "ダイナミック": 2,
    "申し分": 2, "文句なし": 2, "一番いい": 2,
    "引き続き好調": 2, "絶好調": 2,
    # +1（ポジティブ）
    "好気配": 1, "気配良": 1, "仕上がり良": 1, "状態良": 1,
    "好態勢": 1, "好調": 1, "スムーズ": 1, "シャープ": 1,
    "力強": 1, "余裕": 1, "前向き": 1, "集中": 1,
    "重め感のない": 1, "太め感はない": 1, "硬さもない": 1,
    "上積み": 1, "上向き": 1, "ダメージは特になさそう": 1,
    "及第点以上": 1, "ひと追い毎に": 1,
}
SEME_NEG = {
    # -2（明確に悪い・否定文でPOSが誤ヒットするものを相殺）
    "今ひとつ": -2, "いまひとつ": -2, "今一つ": -2,
    "良化余地を残す": -2, "切れがひと息": -2,
    "上向いてきた感じはない": -2,
    "まだ絶好調": -2,       # 「まだ絶好調とまでは言えない」→絶好調(+2)を相殺
    "絶好調とまでは": -2,   # 同上の念押し
    # POS誤マッチ相殺（長いNEGフレーズで短いPOS+1を打ち消し）
    "力強さに欠け": -2,     # 「力強」+1 を相殺
    "ひと追い毎に悪化": -2, # 「ひと追い毎に」+1 を相殺
    # -2（明確なマイナス評価）
    "脚色見劣る": -2, "失速": -2, "力感乏しく": -2,
    "スピード乗らず": -2, "上昇味薄い": -2,
    "良化ひと息": -2, "活気ひと息": -2,
    "末の粘りひと息": -2, "あまり変わり身なし": -2,
    # -1（マイナス要素）
    "もっさり": -1, "物足りない": -1,
    "もうひと絞り": -1, "実戦で変わる": -1,
    "太め感がある": -1, "重め感がある": -1,  # 具体的な太め表現のみNEG
    "太めが": -1, "太め残り": -1,
    "見劣り": -1, "素軽さ欠く": -1, "手先重く": -1,
    "平凡な動き": -1, "平凡": -1,
    "さほど良化なく": -1, "変わらず": -1,
    "争い物足らず": -1,
}


def load_cookie() -> str:
    if not COOKIE_FILE.exists():
        print(f"[ERROR] クッキーファイルが見つかりません: {COOKIE_FILE}")
        print("競馬ブックのページで F12 → Network → Copy as cURL してクッキーを取得し、")
        print(f"{COOKIE_FILE} に貼り付けてください。")
        sys.exit(1)
    return COOKIE_FILE.read_text(encoding="utf-8").strip()


def calc_time_score(last1f: float, course: str) -> int:
    """最終1Fタイムとコースから時計スコア(1-5)を計算"""
    is_sakaro = any(k in course for k in SAKARO_COURSES)
    if is_sakaro:
        # 坂路は基準が遅め
        if last1f <= 12.3:  return 5
        if last1f <= 12.6:  return 4
        if last1f <= 13.0:  return 3
        if last1f <= 13.4:  return 2
        return 1
    else:
        # ウッド・芝・ダートは速め基準
        if last1f <= 11.7:  return 5
        if last1f <= 12.0:  return 4
        if last1f <= 12.4:  return 3
        if last1f <= 12.8:  return 2
        return 1


def calc_cond_score(arrow_text: str, tanpyo: str, semekaisetu: str = "") -> int:
    """矢印・短評・攻め解説から状態スコア(1-5)を計算"""
    # 矢印が→以外なら矢印を優先ベースとして使用
    arrow_base = None
    for arrow, score in ARROW_SCORE.items():
        if arrow in arrow_text:
            arrow_base = score
            break

    # 攻め解説のキーワードスコア
    combined = tanpyo + semekaisetu
    delta = 0
    for kw, val in SEME_POS.items():
        if kw in combined:
            delta += val
    for kw, val in SEME_NEG.items():
        if kw in combined:
            delta += val  # val は負数

    if arrow_base is not None and arrow_base != 3:
        # 矢印が明確な場合は矢印をベースにdelaで微調整
        score = arrow_base + max(-1, min(1, delta))
    else:
        # 矢印が→（中立）または不明の場合は解説のみで判定
        score = 3 + delta

    return max(1, min(5, score))


def scrape(url: str) -> list[dict]:
    cookie_str = load_cookie()
    session = requests.Session()
    session.headers.update(HEADERS)

    # クッキーをパースしてセッションに設定
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            session.cookies.set(k.strip(), v.strip(), domain="p.keibabook.co.jp")

    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "lxml")

    tables = soup.find_all("table", id=re.compile(r"^cyokyo\d+$"))
    if not tables:
        print("[ERROR] 調教データが見つかりません。ログイン状態を確認してください。")
        sys.exit(1)

    results = []
    for tbl in tables:
        tbody = tbl.find("tbody")
        if not tbody:
            continue
        rows = tbody.find_all("tr")
        if not rows:
            continue

        # 馬名・短評・矢印
        horse_row = rows[0]
        kbamei = horse_row.find("td", class_="kbamei")
        tanpyo = horse_row.find("td", class_="tanpyo")
        yajirusi = horse_row.find("td", class_="yajirusi")

        name = kbamei.get_text(strip=True) if kbamei else ""
        tanpyo_text = tanpyo.get_text(strip=True) if tanpyo else ""
        arrow_text = yajirusi.get_text(strip=True) if yajirusi else "→"

        if not name:
            continue

        # 調教タイムテーブルから最終追い切り行（■マーク）を探す
        data_tbl = tbl.find("table", class_="cyokyodata")
        last1f = None
        last_course = ""

        if data_tbl:
            data_tbody = data_tbl.find("tbody")
            data_rows = data_tbody.find_all("tr") if data_tbody else []

            # ■マーク行を優先、なければ最後の行
            target_row = None
            for r in data_rows:
                mark_td = r.find("td", class_="mark")
                tukihi_td = r.find("td", class_="tukihi")
                if tukihi_td and tukihi_td.get_text(strip=True) == "■":
                    target_row = r
                    break
            if target_row is None and data_rows:
                target_row = data_rows[-1]

            if target_row:
                corse_td = target_row.find("td", class_="corse")
                last_course = corse_td.get_text(strip=True) if corse_td else ""

                # タイム列を抽出（数値x.x形式）
                tds = target_row.find_all("td")
                nums = [float(td.get_text(strip=True))
                        for td in tds
                        if re.match(r"^\d+\.\d+$", td.get_text(strip=True))]
                if nums:
                    last1f = nums[-1]  # 最終1Fは一番右の数値

        # 攻め解説
        semekaisetu_div = tbl.find("div", class_="semekaisetu")
        semekaisetu_text = ""
        if semekaisetu_div:
            p = semekaisetu_div.find("p")
            semekaisetu_text = p.get_text(strip=True) if p else ""

        time_score = calc_time_score(last1f, last_course) if last1f else 3
        cond_score = calc_cond_score(arrow_text, tanpyo_text, semekaisetu_text)

        results.append({
            "馬名": name,
            "時計スコア(1-5)": time_score,
            "状態スコア(1-5)": cond_score,
            "メモ": tanpyo_text,
            "_last1f": last1f,
            "_course": last_course,
            "_arrow": arrow_text,
            "_semekaisetu": semekaisetu_text,
        })

    return results


def print_results(results: list[dict]):
    print(f"\n{'馬名':<16} {'時計':>4} {'状態':>4}  {'1F':>5}  {'コース':<8}  短評 / 攻め解説")
    print("-" * 90)
    for r in results:
        last1f_str = f"{r['_last1f']:.1f}" if r["_last1f"] else "  -  "
        seme = r.get("_semekaisetu", "")
        seme_short = seme[:35] + "…" if len(seme) > 35 else seme
        print(f"{r['馬名']:<16} {r['時計スコア(1-5)']:>4} {r['状態スコア(1-5)']:>4}  {last1f_str:>5}  {r['_course']:<8}  {r['メモ']} / {seme_short}")


def save_csv(results: list[dict], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["馬名", "時計スコア(1-5)", "状態スコア(1-5)", "メモ"])
        writer.writeheader()
        for r in results:
            writer.writerow({k: r[k] for k in ["馬名", "時計スコア(1-5)", "状態スコア(1-5)", "メモ"]})
    print(f"\n[保存] {path}")


VENUE_NAMES = ['中山', '阪神', '福島', '東京', '京都', '中京', '新潟', '小倉', '札幌', '函館']


def find_kb_race_id(date: str, race_number: int, venue: str = "") -> str | None:
    """日付・R番号から競馬ブックの12桁IDを取得する。
    date       : "20260418" 形式
    race_number: 11（R番号の数字）
    venue      : "阪神" などの競馬場名（同日複数会場の絞り込み用・省略可）
    """
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    url = f"https://p.keibabook.co.jp/cyuou/nittei/{date}/"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    target_rr = f"{race_number:02d}"  # IDの末尾2桁がR番号
    for tbl in soup.find_all("table", class_="kaisai"):
        th = tbl.find("th")
        th_txt = th.get_text(strip=True) if th else ""
        tbl_venue = next((v for v in VENUE_NAMES if v in th_txt), None)
        if venue and tbl_venue != venue:
            continue
        for a in tbl.find_all("a", href=True):
            if "cyokyo" not in a["href"]:
                continue
            m = re.search(r"(\d{12})", a["href"])
            if m and m.group(1)[10:12] == target_rr:
                return m.group(1)
    return None


def get_today_race_ids() -> list[dict]:
    """競馬ブックのtopページから当日の調教URLを取得する"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    r = requests.get("https://p.keibabook.co.jp/cyuou/top", headers=headers, timeout=15)
    soup = BeautifulSoup(r.text, "lxml")
    races = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/cyuou/cyokyo/\d+/\d+/(\d{12})", href)
        if m:
            race_id = m.group(1)
            if not any(rc["race_id"] == race_id for rc in races):
                parent = a.find_parent()
                race_name = parent.get_text(strip=True)[:40] if parent else ""
                races.append({"race_id": race_id, "url": f"https://p.keibabook.co.jp{href}", "label": race_name})
    return races


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("使い方: python3 keibabook_scraper.py <URL> [--output <ファイル名>]")
        print("        python3 keibabook_scraper.py --list  # 当日レース一覧表示")
        sys.exit(1)

    if args[0] == "--list":
        races = get_today_race_ids()
        print(f"本日の調教データ ({len(races)}レース)")
        for rc in races:
            print(f"  {rc['race_id']}: {rc['label']}")
        sys.exit(0)

    url = args[0]
    output = None
    if "--output" in args:
        idx = args.index("--output")
        if idx + 1 < len(args):
            output = args[idx + 1]

    results = scrape(url)
    print_results(results)

    if output:
        save_csv(results, output)
    else:
        race_id = url.rstrip("/").split("/")[-1]
        training_dir = Path(__file__).parent / "results" / "training"
        training_dir.mkdir(parents=True, exist_ok=True)
        auto_path = training_dir / f"training_{race_id}.csv"
        save_csv(results, str(auto_path))


if __name__ == "__main__" and "--list" in sys.argv:
    races = get_today_race_ids()
    print(f"本日の調教データ ({len(races)}レース)")
    for r in races:
        print(f"  {r['race_id']}: {r['label']}")
