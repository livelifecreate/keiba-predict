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


def cache_stats() -> dict:
    if not CACHE_DIR.exists():
        return {}
    stats = {}
    for ns_dir in CACHE_DIR.iterdir():
        if ns_dir.is_dir():
            stats[ns_dir.name] = len(list(ns_dir.glob("*.json")))
    return stats
