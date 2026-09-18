"""
調教評価スコア（コメントベース・時点統計）

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

時点統計（2026-09-18 修正）:
  旧実装は cache/race_result 全件（採点対象レースより未来の結果を含む）で統計を作り、
  それをバックテストにも使っていた（先読み）。as_of（レース日）を渡すと、その日より
  前のレースだけで複勝率を計算する。当日予想では as_of=当日なので従来と同じ結果になる。
  as_of を省略した場合は全件統計（後方互換）。
"""
import json
import re
from bisect import bisect_left
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

# {コメント: (日付キー昇順リスト, 累積複勝数リスト, 累積出現数リスト)}
_comment_index: dict[str, tuple[list, list, list]] | None = None


def _date_key(date_str: str):
    """'2026年7月25日' / '2026/07/25' → (2026, 7, 25)。解釈不能なら None"""
    m = re.search(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})", date_str or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _build_comment_index() -> dict[str, tuple[list, list, list]]:
    """コメントごとに日付順の累積統計を構築する（プロセス内で1回のみ）"""
    global _comment_index
    if _comment_index is not None:
        return _comment_index

    events: dict[str, list[tuple[tuple, int]]] = defaultdict(list)  # comment -> [(date_key, hit)]
    for f in CACHE_RACE.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if data.get("race_class") not in TARGET_CLASSES:
            continue
        if data.get("surface") not in ("芝", "ダ"):
            continue
        dk = _date_key(data.get("date", ""))
        if not dk:
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
            events[td["comment"]].append((dk, 1 if e.get("rank", 99) <= 3 else 0))

    index = {}
    for comment, ev in events.items():
        ev.sort(key=lambda x: x[0])
        dates, cum_h, cum_n = [], [], []
        h = n = 0
        for dk, hit in ev:
            h += hit
            n += 1
            dates.append(dk)
            cum_h.append(h)
            cum_n.append(n)
        index[comment] = (dates, cum_h, cum_n)
    _comment_index = index
    return index


def _build_comment_stats() -> dict[str, tuple[int, int]]:
    """{コメント文言: (複勝数, 出現数)} 全件統計（後方互換・分析用）"""
    return {c: (ch[-1], cn[-1]) for c, (_, ch, cn) in _build_comment_index().items()}


def comment_stats_as_of(comment: str, as_of=None) -> tuple[int, int]:
    """as_of（日付キー or 日付文字列）より前のレースだけで (複勝数, 出現数) を返す"""
    idx = _build_comment_index().get(comment)
    if not idx:
        return 0, 0
    dates, cum_h, cum_n = idx
    if as_of is None:
        return cum_h[-1], cum_n[-1]
    dk = as_of if isinstance(as_of, tuple) else _date_key(str(as_of))
    if dk is None:
        return cum_h[-1], cum_n[-1]
    k = bisect_left(dates, dk)  # dates[k] >= dk → k件が as_of より前
    if k == 0:
        return 0, 0
    return cum_h[k - 1], cum_n[k - 1]


def get_training_score(rank: str, comment: str, as_of=None) -> float:
    """
    調教評価スコアを返す。
    コメントの実績データが十分（30件以上）あればその複勝率ベースの点数を、
    不足していれば従来のA/B/C/D評価（RANK_SCORE）にフォールバックする。
    as_of: レース日（'2026年7月25日' 等）。指定時はその日より前の実績のみ使う。
    """
    if comment:
        hits, n = comment_stats_as_of(comment, as_of)
        if n >= _MIN_N:
            rate = hits / n
            for cut, pt in zip(_CUTS, _POINTS):
                if rate >= cut:
                    return float(pt)
            return float(_POINTS[-1])
    return float(RANK_SCORE.get(rank, 0))
