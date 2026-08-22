"""クラス実績スコア（格×着差テーブル）。

各馬の近走における「格上(G1/G2/G3/OP)での通用度」を、格×着差で評価して加点する。
既存の grade_history / prev_high_grade_close / prev2_high_grade_close を置き換える統合版。

配点根拠（grade_table_calib.py・cache全件 n=13492ベースライン複勝23.0%）:
  価値は「格」より「着差(通用度)」で決まる。上のクラスを使っても着外はベース以下なので0。
  格順は小サンプルの凸凹を避け単調化。近5走の最高実績セルを採用。

A/Bバックテスト用に環境変数 CLASS_ACH=1 でON（既定OFF=従来ロジック）。
"""
import os

GRADE_LABEL = {7: "G1", 6: "G2", 5: "G3", 4: "OP"}

# 格 → {着差バケツ: 加点}
TABLE = {
    "G1": {"1着": 4.0, "0.2差": 4.0, "0.5差": 3.0, "掲示板": 2.0, "着外": 1.0},
    "G2": {"1着": 3.5, "0.2差": 3.5, "0.5差": 2.5, "掲示板": 1.5, "着外": 0.5},
    "G3": {"1着": 3.0, "0.2差": 3.0, "0.5差": 2.0, "掲示板": 1.0, "着外": 0.0},
    "OP": {"1着": 2.0, "0.2差": 2.0, "0.5差": 1.0, "掲示板": 0.5, "着外": 0.0},
}


def _bucket(p) -> str:
    pos = getattr(p, "position", 0) or 0
    if pos == 1:
        return "1着"
    m = getattr(p, "margin", -1.0)
    if m is None or m < 0:
        return "掲示板" if 0 < pos <= 5 else "着外"
    if m <= 0.2:
        return "0.2差"
    if m <= 0.5:
        return "0.5差"
    return "掲示板" if 0 < pos <= 5 else "着外"


def class_achievement_score(recent, current_class: int = 0, max_runs: int = 5) -> float:
    """近走(最大max_runs走)の「現在クラスより上での実績」のうち最高値を返す。

    current_class より上のクラス(真のクラス落ち)のみ評価する。同格・格下は0。
    根拠(op_special.py): 2勝戦で「OP実績どまり」は複勝21%とベース23%以下＝同格・格下
    実績はプラスにならず、格上(G1-G3)経験のみ30%で有効。OP戦でOP実績を加点すると
    同格を拾って差別化できず悪化するため、現クラス超えのみに限定する。
    """
    best = 0.0
    for p in (recent or [])[:max_runs]:
        rc = getattr(p, "race_class", None)
        if rc is None or rc <= current_class:   # 現クラス以下は評価しない
            continue
        g = GRADE_LABEL.get(rc)
        if not g:
            continue
        best = max(best, TABLE[g][_bucket(p)])
    return best


def enabled() -> bool:
    # 既定ON（本番採用）。A/B検証で CLASS_ACH=0 なら従来ロジックに戻せる。
    return os.environ.get("CLASS_ACH", "1") == "1"
