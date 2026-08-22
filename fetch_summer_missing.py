"""
夏開催で未取得だった3場（札幌・新潟・中京）のレース結果を cache/race_result に補完する。
既存の fetch_summer_2024/2025.py は {小倉,函館,福島} の3場・〜8/3 のみだったため、
札幌記念(8月)・新潟/中京の8〜9月開催が欠落していた。それを埋める。

fetch_race_result() はキャッシュ済みをスキップするので再実行・重複は安全。

使い方:
  python3 fetch_summer_missing.py --test    # 各年1日分のみ動作確認
  python3 fetch_summer_missing.py           # 本番（2024・2025の6/14〜9/15 週末全日）
"""
import sys, datetime, argparse
sys.path.insert(0, '.')
from netkeiba_race_scraper import get_race_list, fetch_race_result

TARGET_VENUES = {"札幌", "新潟", "中京"}

# 札幌(8月〜9月中旬)・新潟/中京(9月まで)を取りこぼさないよう窓を広めに取る
SPANS = {
    2024: (datetime.date(2024, 6, 14), datetime.date(2024, 9, 15)),
    2025: (datetime.date(2025, 6, 14), datetime.date(2025, 9, 15)),
}
TEST_DATES = [datetime.date(2024, 8, 17), datetime.date(2025, 8, 16)]  # 札幌記念ウィーク近辺


def weekend_dates(start: datetime.date, end: datetime.date) -> list:
    dates, d = [], start
    while d <= end:
        if d.weekday() in (5, 6):
            dates.append(d)
        d += datetime.timedelta(days=1)
    return dates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    if args.test:
        dates = TEST_DATES
    else:
        dates = []
        for y in sorted(SPANS):
            dates += weekend_dates(*SPANS[y])

    print(f"対象会場: {sorted(TARGET_VENUES)}")
    print(f"対象日数: {len(dates)}日 ({dates[0]} 〜 {dates[-1]})")

    total_fetched = total_skipped = total_error = 0
    per_venue = {}

    for i, date in enumerate(dates):
        print(f"\n[{i+1}/{len(dates)}] {date} のレース一覧取得中...")
        races = get_race_list([date])
        target = [r for r in races if r['venue'] in TARGET_VENUES]
        print(f"  対象(札幌/新潟/中京): {len(target)}件")

        for r in target:
            try:
                result = fetch_race_result(r['race_id'])
                if result:
                    total_fetched += 1
                    per_venue[r['venue']] = per_venue.get(r['venue'], 0) + 1
                    if total_fetched % 20 == 0:
                        print(f"    ...累計{total_fetched}件取得")
                else:
                    total_skipped += 1
            except Exception as e:
                total_error += 1
                print(f"    エラー {r['race_id']}: {e}")

    print(f"\n完了: 取得={total_fetched}  スキップ={total_skipped}  エラー={total_error}")
    print(f"会場別: {per_venue}")


if __name__ == "__main__":
    main()
