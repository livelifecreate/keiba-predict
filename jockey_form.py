"""
騎手フォームボーナス（時点複勝率ベース）

検証: 2026-07-11（n=660、cache/race_result全件・2勝クラス以上）
  対象: 予想上位1〜3位の再選定に騎手の通算複勝率を加点として使用
  閾値: 30%未満+0.0 / 30〜40%+1.0 / 40%以上+2.0（20騎乗未満はサンプル不足で+0.0）
  結果: OP・2勝クラス・重賞で複勝率・ROIともに改善（特にOP三連複5頭BOX 86.0%→131.0%）
        3勝クラスのみ一貫して悪化（馬連1-2 -50pt、三連複4頭BOX 59.8%→30-36%等）のため除外
  検証詳細: data/騎手ボーナス順位分布レポート_20260711.html

時点統計（2026-09-18 修正）:
  旧実装は cache/race_result 全件（未来の結果を含む）で通算複勝率を作り、バックテストにも
  使っていた（先読み）。as_of（レース日）を渡すと、その日より前の騎乗だけで複勝率を計算する。
  当日予想では as_of=当日なので従来と同じ結果になる。省略時は全件統計（後方互換）。
"""
import json
import re
from bisect import bisect_left
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent
CACHE_RACE = BASE / "cache" / "race_result"

_MIN_RIDES = 20
_LOW_CUT, _LOW_BONUS = 0.30, 1.0
_HIGH_CUT, _HIGH_BONUS = 0.40, 2.0
_EXCLUDE_RACE_CLASS = 3  # 3勝クラス：バックテストで悪化確認のため常に+0

# {騎手名: (日付キー昇順リスト, 累積複勝数, 累積騎乗数)}
_jockey_index: dict[str, tuple[list, list, list]] | None = None


def _date_key(date_str: str):
    m = re.search(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})", date_str or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _build_jockey_index() -> dict[str, tuple[list, list, list]]:
    global _jockey_index
    if _jockey_index is not None:
        return _jockey_index

    events: dict[str, list[tuple[tuple, int]]] = defaultdict(list)
    for f in CACHE_RACE.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        dk = _date_key(data.get("date", ""))
        if not dk:
            continue
        for e in data.get("entries", []):
            jockey = (e.get("jockey") or "").strip()
            rank = e.get("rank", 99)
            if not jockey or not isinstance(rank, int):
                continue
            events[jockey].append((dk, 1 if rank <= 3 else 0))

    index = {}
    for j, ev in events.items():
        ev.sort(key=lambda x: x[0])
        dates, cum_h, cum_n = [], [], []
        h = n = 0
        for dk, hit in ev:
            h += hit
            n += 1
            dates.append(dk)
            cum_h.append(h)
            cum_n.append(n)
        index[j] = (dates, cum_h, cum_n)
    _jockey_index = index
    return index


def _build_rate_table() -> dict[str, tuple[int, int]]:
    """{騎手名: (複勝数, 騎乗数)} 全件統計（後方互換・分析用）"""
    return {j: (ch[-1], cn[-1]) for j, (_, ch, cn) in _build_jockey_index().items()}


def _resolve_name(jockey: str):
    """race_result の騎手名は JRA 形式で3文字程度に切り詰められている（例: 'ルメー', '横山武'）。
    出馬表側のフルネーム（'ルメール', '横山武史'）と一致しない場合、前方一致で一意に決まればそれを使う。"""
    index = _build_jockey_index()
    if jockey in index:
        return jockey
    if len(jockey) < 2:
        return None
    cands = [k for k in index if (k.startswith(jockey) or jockey.startswith(k)) and len(k) >= 2]
    if not cands:
        return None
    # 出馬表側が '横山' のように姓だけで、キャッシュ側に '横山武'/'横山和'/'横山琉' が並ぶ場合は特定不能
    longer = [k for k in cands if k.startswith(jockey) and k != jockey]
    if len(longer) >= 2 and len(longer) == len(cands):
        return None
    # 同一騎手が '丹内' と '丹内祐' のように複数表記で入っていることがあるため、騎乗数最多の表記を採用
    return max(cands, key=lambda k: index[k][2][-1])


def jockey_stats_as_of(jockey: str, as_of=None) -> tuple[int, int]:
    key = _resolve_name(jockey)
    idx = _build_jockey_index().get(key) if key else None
    if not idx:
        return 0, 0
    dates, cum_h, cum_n = idx
    if as_of is None:
        return cum_h[-1], cum_n[-1]
    dk = as_of if isinstance(as_of, tuple) else _date_key(str(as_of))
    if dk is None:
        return cum_h[-1], cum_n[-1]
    k = bisect_left(dates, dk)
    if k == 0:
        return 0, 0
    return cum_h[k - 1], cum_n[k - 1]


def get_jockey_form_bonus(jockey: str, race_class: int, as_of=None) -> float:
    """
    騎手の通算複勝率に基づくボーナス（0.0 / +1.0 / +2.0）。
    3勝クラスは検証で悪化が確認されているため常に+0.0を返す。
    as_of: レース日。指定時はその日より前の騎乗だけで複勝率を計算する。
    """
    if race_class == _EXCLUDE_RACE_CLASS:
        return 0.0

    jockey = (jockey or "").strip()
    if not jockey:
        return 0.0

    hits, rides = jockey_stats_as_of(jockey, as_of)
    if rides < _MIN_RIDES:
        return 0.0

    rate = hits / rides
    if rate >= _HIGH_CUT:
        return _HIGH_BONUS
    if rate >= _LOW_CUT:
        return _LOW_BONUS
    return 0.0
