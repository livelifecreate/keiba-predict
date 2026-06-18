"""
netkeiba 調教キャッシュ一括取得スクリプト
race_result キャッシュ済みの全レースに対して調教データを取得・保存する。
実行: python3 fetch_training_cache.py
"""
import sys, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from netkeiba_scraper import fetch_training_data
from cache_store import _path, cache_set

BASE = Path(__file__).parent
RR_DIR = BASE / "cache" / "race_result"
NT_DIR = BASE / "cache" / "netkeiba_training"
NT_DIR.mkdir(exist_ok=True)

race_files = sorted(RR_DIR.glob("*.json"))
total = len(race_files)
hit, skip, empty, err = 0, 0, 0, 0

print(f"対象: {total}件")
for i, f in enumerate(race_files, 1):
    race_id = f.stem
    cache_path = NT_DIR / f"{race_id}.json"

    # キャッシュ済みはスキップ
    if cache_path.exists():
        skip += 1
        continue

    try:
        result = fetch_training_data(race_id)
        data = {name: {"rank": td.rank, "score": td.score, "comment": td.comment}
                for name, td in result.items()}
        cache_path.write_text(json.dumps(data, ensure_ascii=False))

        if result:
            hit += 1
        else:
            empty += 1

        if i % 50 == 0 or i == total:
            print(f"  {i}/{total}件 (取得:{hit} 空:{empty} スキップ:{skip} エラー:{err})")

        time.sleep(0.5)

    except Exception as e:
        err += 1
        cache_path.write_text("{}")  # エラーも空ファイルで記録して再試行しない

print(f"\n完了: 取得={hit} 空={empty} スキップ={skip} エラー={err}")
