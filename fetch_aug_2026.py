"""2026年8月の中央開催(札幌・新潟・中京)のレース結果をキャッシュへ取得。
8/8・8/9・8/15・8/16 のバックテスト/照合用。fetch_race_result はキャッシュ済スキップ。
"""
import sys, datetime
sys.path.insert(0, '.')
from netkeiba_race_scraper import get_race_list, fetch_race_result

TARGET_VENUES = {"札幌", "新潟", "中京"}
DATES = [datetime.date(2026, 8, d) for d in (8, 9, 15, 16)]

races = [r for r in get_race_list(DATES) if r['venue'] in TARGET_VENUES]
print(f"対象: {len(races)}レース")
hit = skip = err = 0
per = {}
for i, r in enumerate(races, 1):
    try:
        res = fetch_race_result(r['race_id'])
        if res:
            hit += 1
            per[r['venue']] = per.get(r['venue'], 0) + 1
        else:
            skip += 1
    except Exception as e:
        err += 1
    if i % 30 == 0:
        print(f"  {i}/{len(races)} (取得{hit} 空{skip} エラー{err})", flush=True)
print(f"完了: 取得={hit} 空={skip} エラー={err} 会場別={per}")
