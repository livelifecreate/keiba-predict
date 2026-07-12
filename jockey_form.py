"""
騎手フォームボーナス（時点複勝率ベース）

検証: 2026-07-11（n=660、cache/race_result全件・2勝クラス以上）
  対象: 予想上位1〜3位の再選定に騎手の通算複勝率を加点として使用
  閾値: 30%未満+0.0 / 30〜40%+1.0 / 40%以上+2.0（20騎乗未満はサンプル不足で+0.0）
  結果: OP・2勝クラス・重賞で複勝率・ROIともに改善（特にOP三連複5頭BOX 86.0%→131.0%）
        3勝クラスのみ一貫して悪化（馬連1-2 -50pt、三連複4頭BOX 59.8%→30-36%等）のため除外
  検証詳細: data/騎手ボーナス順位分布レポート_20260711.html

先読み禁止の要件はバックテスト専用（cache_get_before等）。
本モジュールは当日予想でのみ使用し、cache/race_result は常に過去の確定結果のみを
含むため、素直に全件を通算成績として使ってよい。
"""
import json
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent
CACHE_RACE = BASE / "cache" / "race_result"

_MIN_RIDES = 20
_LOW_CUT, _LOW_BONUS = 0.30, 1.0
_HIGH_CUT, _HIGH_BONUS = 0.40, 2.0
_EXCLUDE_RACE_CLASS = 3  # 3勝クラス：バックテストで悪化確認のため常に+0

_rate_table: dict[str, tuple[int, int]] | None = None


def _build_rate_table() -> dict[str, tuple[int, int]]:
    """{騎手名: (複勝数, 騎乗数)} を cache/race_result 全件から構築する（プロセス内で1回のみ）"""
    global _rate_table
    if _rate_table is not None:
        return _rate_table

    hist: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f in CACHE_RACE.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        for e in data.get("entries", []):
            jockey = (e.get("jockey") or "").strip()
            rank = e.get("rank", 99)
            if not jockey or not isinstance(rank, int):
                continue
            hist[jockey][1] += 1
            if rank <= 3:
                hist[jockey][0] += 1

    _rate_table = {k: (v[0], v[1]) for k, v in hist.items()}
    return _rate_table


def get_jockey_form_bonus(jockey: str, race_class: int) -> float:
    """
    騎手の通算複勝率に基づくボーナス（0.0 / +1.0 / +2.0）。
    3勝クラスは検証で悪化が確認されているため常に+0.0を返す。
    """
    if race_class == _EXCLUDE_RACE_CLASS:
        return 0.0

    jockey = (jockey or "").strip()
    if not jockey:
        return 0.0

    table = _build_rate_table()
    hits, rides = table.get(jockey, (0, 0))
    if rides < _MIN_RIDES:
        return 0.0

    rate = hits / rides
    if rate >= _HIGH_CUT:
        return _HIGH_BONUS
    if rate >= _LOW_CUT:
        return _LOW_BONUS
    return 0.0
