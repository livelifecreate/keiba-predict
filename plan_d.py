"""
案D順位づけ（2026-09-20〜・実運用の主順位）

  案Dスコア u = w1·z(能力指数v2) + w2·z(現行スコアから能力系16因子を除いた残り)
    - 能力指数v2: analyze/ability_index.py（対戦相手の強さ＋相対着順の同時推定・芝ダ別・レース日より前の結果のみ）
    - 能力系16因子（前走好走・勝利数・クラス実績・複勝安定など「過去の成績」を測る因子）は v2 と役割が重複するため除外
    - 重み・標準化定数は data/plan_d_params.json（analyze/ability_blend_backtest.py が 〜2025/06 で学習）

根拠（テスト2025/07〜・n=1009R）: 予想1位複勝率 48.0→54.2%、単勝ROI 73→98%、三連複5頭BOX 的中21.6→25.5%/ROI72→81%。
  ROI>100%は未達で検証ゲート上は「継続観察」だが、ユーザー判断で 2026-09-20 から主順位に採用。
  環境変数 PLAN_D=0 で従来順位（現行スコア順）に戻せる。
"""
import json, os, sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "analyze"))

# ScoreBreakdown のうち「過去の成績＝能力」を測るフィールド（CSVの能力系16因子に対応）
ABILITY_FIELDS = ["prev_high_grade_close", "prev2_high_grade_close", "fastest_3f", "same_course", "rising_trend",
                  "prev_run_bonus", "prev2_run_bonus", "grade_history", "class_achievement", "place_consistency",
                  "win_count", "content_score", "steep_power", "venue_aptitude", "promotion", "local_prev"]

_PARAMS = None
_ABILITY = {}     # (surface, as_of序数) → (θ辞書, 偏差値用の平均, 標準偏差)
_RACES = None


def enabled() -> bool:
    return os.environ.get("PLAN_D", "1") != "0"


def _params():
    global _PARAMS
    if _PARAMS is None:
        _PARAMS = json.loads((BASE / "data" / "plan_d_params.json").read_text())
    return _PARAMS


def _ability(surface: str, as_of: int):
    """能力指数v2を as_of（序数日）より前のレースだけで推定。プロセス内でキャッシュ"""
    global _RACES
    key = (surface, as_of)
    if key not in _ABILITY:
        import ability_index as A
        p = _params()
        if _RACES is None:
            _RACES = A.load_races()
        obs, hmap, _ = A.build_obs(_RACES, {}, surface)          # 着順型(yr)は着差データ不要
        theta, W = A.fit(obs, as_of, p["tau"], p["lam"], p["ykey"], len(hmap))
        act = W > 0.5
        _ABILITY[key] = ({hid: theta[j] for hid, j in hmap.items() if not np.isnan(theta[j])},
                         float(np.nanmean(theta[act])), float(np.nanstd(theta[act])))
    return _ABILITY[key]


def rank(results, horse_ids: dict, surface: str, race_date) -> dict:
    """
    results: score_all の戻り値 [(entry, ScoreBreakdown), ...]
    戻り値: {馬名: {"u": 案Dスコア, "dev": 能力指数(偏差値・無ければNone), "rest": 能力以外の点数, "base_rank": 現行順位}}
    """
    p = _params()
    theta, mu_all, sd_all = _ability("芝" if surface == "芝" else "ダ", race_date.toordinal())
    names = [e.horse_name for e, _ in results]
    v2 = np.array([theta.get(horse_ids.get(n), np.nan) for n in names], dtype=float)
    rest = np.array([d.total - sum(float(getattr(d, f, 0) or 0) for f in ABILITY_FIELDS) for _, d in results], dtype=float)
    v2_c = np.where(np.isnan(v2), 0.0, v2 - np.nanmean(v2)) if np.isfinite(v2).any() else np.zeros(len(names))
    rest_c = rest - rest.mean()
    x = np.column_stack([v2_c, rest_c])
    u = ((x - np.array(p["mu"])) / np.array(p["sd"])) @ np.array(p["w"])
    base_order = sorted(range(len(results)), key=lambda i: results[i][1].total, reverse=True)
    base_rank = {names[i]: k + 1 for k, i in enumerate(base_order)}
    return {n: {"u": float(u[i]), "dev": None if np.isnan(v2[i]) else 50 + 10 * (v2[i] - mu_all) / sd_all,
                "rest": float(rest[i]), "base_rank": base_rank[n]} for i, n in enumerate(names)}


def comment_lines(sorted_results, info: dict) -> list[str]:
    lines = ["【案D順位】能力指数v2＋能力以外の因子（調教・騎手・枠・距離変更など）で順位を決定（2026-09-20〜）。合計スコア列は従来の現行スコア（参考）"]
    for k, (e, d) in enumerate(sorted_results, 1):
        r = info[e.horse_name]
        dev = f"{r['dev']:.1f}" if r["dev"] is not None else "データなし"
        lines.append(f"案D{k}位 {e.horse_number}番 {e.horse_name} 案D{r['u']:+.2f} / 能力指数{dev} / 能力以外{r['rest']:+.1f} / 現行{r['base_rank']}位({d.total:+.1f})")
    return lines
