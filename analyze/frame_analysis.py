"""
枠番別タイム差・着順差分析スクリプト
対象: 東京・阪神 / ダート1200・1400m / 芝1400・1600m
期間: 2024〜2025年
"""

import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
import time
import random
from pathlib import Path
import pandas as pd
import requests
from bs4 import BeautifulSoup
from cache_store import cache_get, cache_set

def _sleep():
    time.sleep(random.uniform(1.5, 2.5))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 対象条件（None = 全距離）
TARGET = None  # すべての距離を収集

# 東京=05, 中山=06, 阪神=09, 京都=08, 中京=10, 新潟=04, 小倉=03, 福島=01
VENUES_TURF  = [("東京", "05"), ("阪神", "09"), ("京都", "08")]
VENUES_ALL   = [("福島", "01"), ("小倉", "03"), ("新潟", "04"), ("東京", "05"),
                ("中山", "06"), ("京都", "08"), ("阪神", "09"), ("中京", "10")]
VENUES = VENUES_ALL  # デフォルトは全会場


def generate_race_ids(years, venue_codes, max_kai=5, max_nichi=8, max_race=12):
    ids = []
    for year in years:
        for _, code in venue_codes:
            for kai in range(1, max_kai + 1):
                for nichi in range(1, max_nichi + 1):
                    for race in range(1, max_race + 1):
                        ids.append(f"{year}{code}{kai:02d}{nichi:02d}{race:02d}")
    return ids


def time_to_sec(t: str) -> float | None:
    """'1:23.4' → 83.4秒"""
    m = re.match(r"(\d+):(\d+\.\d+)", t.strip())
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    m = re.match(r"(\d+\.\d+)", t.strip())
    if m:
        return float(m.group(1))
    return None


def fetch_race(race_id: str) -> dict | None:
    cached = cache_get("frame_race", race_id)
    if cached is not None:
        return cached
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "lxml")

        # コース・距離取得
        data_el = soup.find(class_="RaceData01")
        if not data_el:
            return None
        data_text = data_el.get_text()
        surface_match = re.search(r"(芝|ダ[ート]*)\s*(\d+)m", data_text)
        if not surface_match:
            return None
        surface = "芝" if surface_match.group(1) == "芝" else "ダ"
        distance = int(surface_match.group(2))

        # 対象条件チェック
        if TARGET is not None and (surface, distance) not in TARGET:
            return None

        # 結果テーブル（着順・枠・馬番・タイム）
        table = soup.find("table", class_="RaceTable01")
        if not table:
            return None

        rows = table.find_all("tr")[1:]
        records = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 8:
                continue
            try:
                rank_text = cols[0].get_text(strip=True)
                rank = int(rank_text) if rank_text.isdigit() else None
                frame = int(cols[1].get_text(strip=True))
                horse_num = int(cols[2].get_text(strip=True))
                time_text = cols[7].get_text(strip=True)
                time_sec = time_to_sec(time_text)
                if rank and time_sec:
                    records.append({
                        "race_id": race_id,
                        "surface": surface,
                        "distance": distance,
                        "frame": frame,
                        "horse_num": horse_num,
                        "rank": rank,
                        "time_sec": time_sec,
                    })
            except (ValueError, IndexError):
                continue

        if len(records) < 8:
            return None

        # 同一レース内のタイム差（1着タイムを基準に）
        winner_time = min(r["time_sec"] for r in records if r["rank"] == 1)
        for r in records:
            r["time_diff"] = r["time_sec"] - winner_time

        result = {"race_id": race_id, "surface": surface, "distance": distance, "records": records}
        cache_set("frame_race", race_id, result)
        return result

    except Exception:
        return None


def analyze(df: pd.DataFrame):
    print("\n" + "=" * 70)
    print("■ 枠番別 平均着順・平均タイム差（1着比）")
    print("=" * 70)

    for (surface, distance), group in df.groupby(["surface", "distance"]):
        print(f"\n【{surface}{distance}m】  レース数: {group['race_id'].nunique()}  頭数: {len(group)}")
        stats = group.groupby("frame").agg(
            レース数=("race_id", "nunique"),
            平均着順=("rank", "mean"),
            平均タイム差=("time_diff", "mean"),
            勝利数=("rank", lambda x: (x == 1).sum()),
            複勝数=("rank", lambda x: (x <= 3).sum()),
            総頭数=("rank", "count"),
        ).round(3)
        stats["勝率%"] = (stats["勝利数"] / stats["総頭数"] * 100).round(1)
        stats["複勝率%"] = (stats["複勝数"] / stats["総頭数"] * 100).round(1)
        print(stats[["レース数", "平均着順", "平均タイム差", "勝率%", "複勝率%"]].to_string())

    print("\n" + "=" * 70)
    print("■ スコア換算基準（参考）")
    print("  現システム: 調教+3点 ≈ 有力馬の質的差")
    print("  タイム換算: 1秒 ≈ 約5馬身 ≈ 実力差として大きい")
    print("  0.1秒差 → 約0.5点が妥当ラインの目安")
    print("=" * 70)


def main():
    test_mode  = "--test"   in sys.argv
    dirt_only  = "--surface" in sys.argv and sys.argv[sys.argv.index("--surface") + 1] == "ダ"

    # --years 2024 2025 形式で指定可能（デフォルト: 2024 2025）
    if "--years" in sys.argv:
        idx = sys.argv.index("--years")
        years = []
        for a in sys.argv[idx + 1:]:
            if a.startswith("--"): break
            try: years.append(int(a))
            except ValueError: pass
    else:
        years = [2024, 2025]

    max_nichi = 3 if test_mode else 8

    # ダートのみモード: TARGET をダートに絞る
    global TARGET
    if dirt_only:
        TARGET = None   # fetch_race 内で surface=="ダ" のみ残す（下記フィルタで対応）
        print(f"[ダートのみ] years={years}")
    else:
        print(f"[全コース] years={years}")

    OUT_CSV = Path(__file__).parent.parent / "data" / "frame_analysis_all_2024_2025.csv"

    # 既存データを読み込んで重複除外
    existing_ids: set[str] = set()
    if OUT_CSV.exists():
        import csv as _csv
        with open(OUT_CSV, encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                existing_ids.add(row["race_id"])
        print(f"  既存データ: {len(existing_ids)}レース")

    race_ids = generate_race_ids(years, VENUES, max_kai=6, max_nichi=max_nichi)
    # 取得済みをスキップ
    race_ids = [r for r in race_ids if r not in existing_ids]
    print(f"  候補（未取得）: {len(race_ids)}件")

    records_all = []
    found = 0
    skipped = 0

    for i, rid in enumerate(race_ids):
        result = fetch_race(rid)
        if result:
            # ダートのみモードで芝が混入した場合は除外
            if dirt_only and result["surface"] != "ダ":
                skipped += 1
            else:
                records_all.extend(result["records"])
                found += 1
                if found % 50 == 0:
                    print(f"  {found}レース取得済 ({i+1}/{len(race_ids)})")
        else:
            skipped += 1

        if test_mode and found >= 20:
            print("  テストモード: 20レース取得で終了")
            break

        _sleep()

    if not records_all:
        print("新規データなし。")
        return

    df_new = pd.DataFrame(records_all)

    # 既存CSVに追記
    write_header = not OUT_CSV.exists()
    df_new.to_csv(OUT_CSV, mode="a", index=False, header=write_header, encoding="utf-8")
    print(f"\n保存: {OUT_CSV} (+{len(df_new)}行, {found}レース追加)")

    # 全データで分析
    df_all = pd.read_csv(OUT_CSV, on_bad_lines="skip")
    analyze(df_all)


if __name__ == "__main__":
    main()
