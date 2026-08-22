"""任意期間の中央競馬 全会場レース結果を cache/race_result に取得する汎用スクリプト。
欠損期間のバックフィル用。fetch_race_result はキャッシュ済をスキップするので再実行安全。

使い方:
  python3 fetch_period.py --start 2025-03-01 --end 2025-05-31 --test  # 最初の1日だけ
  python3 fetch_period.py --start 2025-03-01 --end 2025-05-31          # 本番
"""
import sys, datetime, argparse
sys.path.insert(0, '.')
from netkeiba_race_scraper import get_race_list, fetch_race_result

JRA_VENUES = {"札幌","函館","福島","新潟","東京","中山","中京","京都","阪神","小倉"}


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += datetime.timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    start = datetime.date.fromisoformat(a.start)
    end = datetime.date.fromisoformat(a.end)
    dates = list(daterange(start, end))  # 全日スキャン（祝日開催も拾う。非開催日はget_race_listが空）

    if a.test:
        dates = dates[:1]
    print(f"対象日数: {len(dates)}日 ({dates[0]} 〜 {dates[-1]})")

    hit = skip = err = 0
    per = {}
    for i, date in enumerate(dates, 1):
        races = [r for r in get_race_list([date]) if r['venue'] in JRA_VENUES]
        if not races:
            continue
        for r in races:
            try:
                res = fetch_race_result(r['race_id'])
                if res:
                    hit += 1; per[r['venue']] = per.get(r['venue'], 0) + 1
                else:
                    skip += 1
            except Exception:
                err += 1
        if i % 5 == 0:
            print(f"  {i}/{len(dates)}日 (取得{hit} 空{skip} エラー{err})", flush=True)
    print(f"完了: 取得={hit} 空={skip} エラー={err}")
    print(f"会場別: {per}")


if __name__ == "__main__":
    main()
