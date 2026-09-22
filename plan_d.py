"""
順位づけ（2026-09-23〜 案G / 2026-09-20〜2026-09-22 案D）

  スコア u = w1·z(能力指数) + w2·z(現行スコアから能力系16因子を除いた残り)
    - 能力指数: 既定は **v3の純粋な能力θ**（`analyze/ability_index_v3.py`）。
      騎手・枠・斤量・年齢性別・休養・距離変化・クラス変化・重不良×道悪適性を同時推定し、
      それらを差し引いた「馬そのものの力」。芝ダ別・レース日より前の結果のみ（先読みなし）。
    - 能力系16因子（前走好走・勝利数・クラス実績・複勝安定など）は指数と役割が重複するため除外。
      残る18因子（調教・騎手フォーム・枠・距離変更・休養・道悪適性など）の合計を第2項に使う。
    - 重み・標準化定数は data/plan_g_params.json（案D時代は plan_d_params.json）。

根拠（テスト2025/07〜・払戻ありn=1009R）:
  案G: 予想1位複勝率56.0% / 単勝ROI93% / ワイド1-2 78% / 現行買いサイン 的中23.7%・ROI88%
  案D: 54.2% / 98% / 68% / 23.1%・85%   現行スコアのみ: 48.0% / 73% / 87% / 19.0%・72%
  ROIは依然100%未満のため、買いサインは記録のみ（購入判断はユーザー）。

環境変数:
  PLAN_D=0       … 順位づけを使わず従来（現行スコア順）に戻す
  PLAN_VARIANT=D … v2ベースの案Dで動かす（比較用）
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
_ABILITY = {}     # (variant, surface, as_of序数) → (θ辞書, 偏差値用の平均, 標準偏差)
_RACES = None
_V3CTX = None     # v3用の前走・馬場・父馬データ（1回だけ作る）


def enabled() -> bool:
    return os.environ.get("PLAN_D", "1") != "0"


def variant() -> str:
    return "D" if os.environ.get("PLAN_VARIANT", "G").upper() == "D" else "G"


def _params():
    global _PARAMS
    if _PARAMS is None:
        f = "plan_d_params.json" if variant() == "D" else "plan_g_params.json"
        _PARAMS = json.loads((BASE / "data" / f).read_text())
    return _PARAMS


def _races():
    global _RACES
    if _RACES is None:
        import ability_index as A
        _RACES = A.load_races()
    return _RACES


def _ability_v2(surface: str, as_of: int):
    import ability_index as A
    p = _params()
    obs, hmap, _ = A.build_obs(_races(), {}, surface)
    theta, W = A.fit(obs, as_of, p["tau"], p["lam"], p["ykey"], len(hmap))
    return theta, W, hmap


def _ability_v3(surface: str, as_of: int):
    """v3（能力と条件の同時推定）。1パス目のθで道悪残差を作り、2パス目で確定させる。"""
    global _V3CTX
    import ability_index_v3 as V
    races = _races()
    if _V3CTX is None:
        _V3CTX = (V.prev_map(), V.going_map(races), V.sire_map())
    prevs, going, sires = _V3CTX
    obs0, hmap, jmap, rr = V.build(races, surface, prevs)
    first = V.fit(obs0, as_of, len(hmap), len(jmap))

    class _Same(dict):                      # どの開催日でも同じ1パス目の推定値を返す
        def get(self, k, d=None):
            return first

    obs, hmap, jmap, rr = V.build(races, surface, prevs, going, sires, _Same())
    theta, W, _, _ = V.fit(obs, as_of, len(hmap), len(jmap))
    return theta, W, hmap


def _ability(surface: str, as_of: int):
    key = (variant(), surface, as_of)
    if key not in _ABILITY:
        theta, W, hmap = (_ability_v2 if variant() == "D" else _ability_v3)(surface, as_of)
        act = W > 0.5
        _ABILITY[key] = ({hid: theta[j] for hid, j in hmap.items() if not np.isnan(theta[j])},
                         float(np.nanmean(theta[act])), float(np.nanstd(theta[act])))
    return _ABILITY[key]


def ability_map(surface: str, race_date):
    """(θ辞書{馬ID: 値}, 偏差値化の平均, 標準偏差) を返す。レースレベルの算出にも使う"""
    return _ability("芝" if surface == "芝" else "ダ", race_date.toordinal())


def rank(results, horse_ids: dict, surface: str, race_date) -> dict:
    """
    results: score_all の戻り値 [(entry, ScoreBreakdown), ...]
    戻り値: {馬名: {"u": スコア, "score": 総合点, "dev": 能力指数(偏差値), "rest": 能力以外の点, "base_rank": 現行順位}}
    """
    p = _params()
    theta, mu_all, sd_all = _ability("芝" if surface == "芝" else "ダ", race_date.toordinal())
    names = [e.horse_name for e, _ in results]
    abil = np.array([theta.get(horse_ids.get(n), np.nan) for n in names], dtype=float)
    rest = np.array([d.total - sum(float(getattr(d, f, 0) or 0) for f in ABILITY_FIELDS) for _, d in results], dtype=float)
    abil_c = np.where(np.isnan(abil), 0.0, abil - np.nanmean(abil)) if np.isfinite(abil).any() else np.zeros(len(names))
    rest_c = rest - rest.mean()
    x = np.column_stack([abil_c, rest_c])
    u = ((x - np.array(p["mu"])) / np.array(p["sd"])) @ np.array(p["w"])
    base_order = sorted(range(len(results)), key=lambda i: results[i][1].total, reverse=True)
    base_rank = {names[i]: k + 1 for k, i in enumerate(base_order)}
    # 総合点 = 50 + 10×スコア（順位を決めた点数を見やすい尺度にしたもの。平均的な馬が50前後）
    return {n: {"u": float(u[i]), "score": round(50 + 10 * float(u[i]), 1),
                "dev": None if np.isnan(abil[i]) else 50 + 10 * (abil[i] - mu_all) / sd_all,
                "rest": float(rest[i]), "base_rank": base_rank[n]} for i, n in enumerate(names)}


def comment_lines(sorted_results, info: dict) -> list[str]:
    v = variant()
    head = ("【案G順位】能力指数v3（騎手・枠・斤量・休養・距離変化・道悪適性を差し引いた純粋な能力）"
            "＋能力以外の因子で順位を決定（2026-09-23〜）。合計スコア列は従来の現行スコア（参考）")
    if v == "D":
        head = "【案D順位】能力指数v2＋能力以外の因子で順位を決定。合計スコア列は従来の現行スコア（参考）"
    lines = [head]
    for k, (e, d) in enumerate(sorted_results, 1):
        r = info[e.horse_name]
        dev = f"{r['dev']:.1f}" if r["dev"] is not None else "データなし"
        lines.append(f"案{v}{k}位 {e.horse_number}番 {e.horse_name} 総合点{r['score']:.1f} / 能力指数{dev} / "
                     f"能力以外{r['rest']:+.1f} / 現行{r['base_rank']}位({d.total:+.1f})")
    return lines


def extra_cols(info: dict) -> dict:
    """CSV末尾に足す列: 総合点（順位の根拠）・能力指数（偏差値）・現行順位（旧ロジックでの順位）"""
    return {"総合点": {n: f"{r['score']:.1f}" for n, r in info.items()},
            "能力指数": {n: ("" if r["dev"] is None else f"{r['dev']:.1f}") for n, r in info.items()},
            "旧順位": {n: r["base_rank"] for n, r in info.items()}}
