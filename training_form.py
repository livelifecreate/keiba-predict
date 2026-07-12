"""
調教評価スコア（コメントベース）

検証: 2026-07-12（n=660、cache/race_result全件・2勝クラス以上）
  従来のA/B/C/D評価は同じB評価内でも実際の複勝率が7.7%〜43.3%まで開いており、
  評価情報の大半を捨てていた（コメント文言に細かい差があるのに一律+2点扱いだった）。
  コメント文言別の実績複勝率を使うことで同じ調教評価という情報源からより多くの
  シグナルを抽出する。

配点（2026-07-12 配点スイープで確定）:
  コメントの複勝率が
    35%以上         → +3
    25%以上35%未満  → +2
    15%以上25%未満  → +1
    8%以上15%未満   → 0
    8%未満          → -1
  該当コメントの母数が30件未満の場合は従来のA/B/C/D評価（RANK_SCORE）にフォールバック。

検証結果: 3勝クラス 馬連1-2 255.5%→256.5%、ワイド1-2 101.1%→104.5%、
          三連複5頭BOX 64.9%→75.8%。OP ワイド1-2 131.3%→149.0%。
検証詳細: 2026-07-12のセッション内バックテスト（training_comment_sweep.py相当）。
"""
import json
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent
CACHE_RACE = BASE / "cache" / "race_result"
NETKEIBA_TRAINING_DIR = BASE / "cache" / "netkeiba_training"

TARGET_CLASSES = {"2勝クラス", "3勝クラス", "OP", "重賞"}
RANK_SCORE = {"A": 3, "B": 2, "C": 1, "D": 0}

_MIN_N = 30
_CUTS = [0.35, 0.25, 0.15, 0.08]
_POINTS = [3, 2, 1, 0, -1]

_comment_stats: dict[str, tuple[int, int]] | None = None


def _build_comment_stats() -> dict[str, tuple[int, int]]:
    """{コメント文言: (複勝数, 出現数)} を cache/race_result 全件から構築する（プロセス内で1回のみ）"""
    global _comment_stats
    if _comment_stats is not None:
        return _comment_stats

    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f in CACHE_RACE.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if data.get("race_class") not in TARGET_CLASSES:
            continue
        if data.get("surface") not in ("芝", "ダ"):
            continue

        race_id = data.get("race_id", "")
        training_path = NETKEIBA_TRAINING_DIR / f"{race_id}.json"
        if not training_path.exists():
            continue
        try:
            training = json.loads(training_path.read_text())
        except Exception:
            continue

        for e in data.get("entries", []):
            td = training.get(e.get("horse_name", ""))
            if not td or not td.get("comment"):
                continue
            comment = td["comment"]
            stats[comment][1] += 1
            if e.get("rank", 99) <= 3:
                stats[comment][0] += 1

    _comment_stats = {k: (v[0], v[1]) for k, v in stats.items()}
    return _comment_stats


def get_training_score(rank: str, comment: str) -> float:
    """
    調教評価スコアを返す。
    コメントの実績データが十分（30件以上）あればその複勝率ベースの点数を、
    不足していれば従来のA/B/C/D評価（RANK_SCORE）にフォールバックする。
    """
    if comment:
        stats = _build_comment_stats()
        hits, n = stats.get(comment, (0, 0))
        if n >= _MIN_N:
            rate = hits / n
            for cut, pt in zip(_CUTS, _POINTS):
                if rate >= cut:
                    return float(pt)
            return float(_POINTS[-1])
    return float(RANK_SCORE.get(rank, 0))
