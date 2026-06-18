"""
シンプルなディスクキャッシュ。
取得済みデータをJSONファイルに保存し、2回目以降のネットアクセスを省略する。

使い方:
    from cache_store import cache_get, cache_set

    data = cache_get("race_result", race_id)
    if data is None:
        data = fetch_from_web(race_id)
        cache_set("race_result", race_id, data)
"""

import json
import os
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"


def _path(namespace: str, key: str) -> Path:
    d = CACHE_DIR / namespace
    d.mkdir(parents=True, exist_ok=True)
    safe_key = str(key).replace("/", "_").replace(":", "_")
    return d / f"{safe_key}.json"


def cache_get(namespace: str, key: str):
    p = _path(namespace, key)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def cache_set(namespace: str, key: str, data) -> None:
    p = _path(namespace, key)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def cache_exists(namespace: str, key: str) -> bool:
    return _path(namespace, key).exists()


def cache_get_before(namespace: str, horse_id: str, cutoff_date: str, max_days_back: int = 7):
    """horse_id に対応するキャッシュの中で cutoff_date 以前の最新のものを返す。
    cutoff_date 形式: 'YYYY/MM/DD'
    exact matchがあればそれを、なければ max_days_back 日以内のものをフォールバック。
    """
    import re as _re
    from datetime import datetime, timedelta
    exact = _path(namespace, f"{horse_id}_{cutoff_date}")
    if exact.exists():
        with open(exact, encoding="utf-8") as f:
            return json.load(f)

    # フォールバック: max_days_back 日以内の最新キャッシュを探す
    try:
        cutoff_dt = datetime.strptime(cutoff_date, "%Y/%m/%d")
        earliest_dt = cutoff_dt - timedelta(days=max_days_back)
        earliest_safe = earliest_dt.strftime("%Y_%m_%d")
    except ValueError:
        return None

    cutoff_safe = cutoff_date.replace("/", "_")  # YYYY_MM_DD
    ns_dir = CACHE_DIR / namespace
    if not ns_dir.exists():
        return None

    pattern = _re.compile(r"^" + _re.escape(str(horse_id)) + r"_(\d{4}_\d{2}_\d{2})\.json$")
    candidates = []
    for p in ns_dir.glob(f"{horse_id}_*.json"):
        m = pattern.match(p.name)
        if m:
            d = m.group(1)  # YYYY_MM_DD
            if earliest_safe <= d <= cutoff_safe:
                candidates.append((d, p))

    if not candidates:
        return None

    best = max(candidates, key=lambda x: x[0])
    with open(best[1], encoding="utf-8") as f:
        return json.load(f)


def cache_stats() -> dict:
    if not CACHE_DIR.exists():
        return {}
    stats = {}
    for ns_dir in CACHE_DIR.iterdir():
        if ns_dir.is_dir():
            stats[ns_dir.name] = len(list(ns_dir.glob("*.json")))
    return stats
