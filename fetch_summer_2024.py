"""
2024年夏（小倉・函館・福島の夏開催）のレース結果を取得してcache/race_resultに追加する。
2025年夏のサンプル(n=24, 3勝+OP合計)が薄すぎるため、もう1年分追加してサンプルを増やす。

使い方:
  python3 fetch_summer_2024.py --test   # 1日分のみ
  python3 fetch_summer_2024.py          # 本番（2024/6/14〜8/3の週末全日）
"""
import sys, datetime, argparse
sys.path.insert(0, '.')
from netkeiba_race_scraper import get_race_list, fetch_race_result

TARGET_VENUES = {"小倉", "函館", "福島"}


def weekend_dates(start: datetime.date, end: datetime.date) -> list:
    dates = []
    d = start
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
        dates = [datetime.date(2024, 7, 6)]
    else:
        dates = weekend_dates(datetime.date(2024, 6, 14), datetime.date(2024, 8, 3))

    print(f"対象日数: {len(dates)}日 ({dates[0]} 〜 {dates[-1]})")

    total_fetched = total_skipped = total_error = 0

    for i, date in enumerate(dates):
        print(f"\n[{i+1}/{len(dates)}] {date} のレース一覧取得中...")
        races = get_race_list([date])
        target = [r for r in races if r['venue'] in TARGET_VENUES]
        print(f"  対象(小倉/函館/福島): {len(target)}件")

        for r in target:
            try:
                result = fetch_race_result(r['race_id'])
                if result:
                    total_fetched += 1
                    if total_fetched % 20 == 0:
                        print(f"    ...累計{total_fetched}件取得")
                else:
                    total_skipped += 1
            except Exception as e:
                total_error += 1
                print(f"    エラー {r['race_id']}: {e}")

    print(f"\n完了: 取得={total_fetched}  スキップ={total_skipped}  エラー={total_error}")


if __name__ == "__main__":
    main()
