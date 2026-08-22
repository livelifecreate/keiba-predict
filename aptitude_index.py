"""
条件適性指数モジュール（2026-07-18 新設）

競馬場巧者指数・季節指数・コース属性適性・開催時期補正の4指数を管理する。
各指数は FEATURE_FLAGS で個別に ON/OFF できる。
keiba-feature-gate（バックテスト合格）を通過するまでフラグを True にしないこと。

指数は各馬の過去走（scorer 側で 2年縛りフィルタ済みの PastRace リスト）から
複勝率ベースで計算する。サンプル不足（最低走数未満）は常に 0.0 を返す。
"""

FEATURE_FLAGS = {
    "venue_aptitude": False,  # 競馬場巧者指数（検証中 2026-07-18）
    "season_index":   False,  # 季節指数（未実装）
    "course_attr":    False,  # コース属性適性（未実装）
    "meet_phase":     False,  # 開催時期補正（未実装）
}


# -------------------------------------------------------------------
# 1. 競馬場巧者指数
# -------------------------------------------------------------------
# キャリブレーション（2026-07-18・708R・9,769頭・2勝クラス以上・2025/07+2025/10〜2026/06）
# 当該場2走以上のとき、場複勝率帯ごとの実際の3着以内率（ベース21.8%）:
#   75%以上   → 38.3% (+16.5pt)  n=580
#   50〜75%   → 28.4% (+6.6pt)   n=1184
#   25〜50%   → 20.0% (-1.8pt)   n=405
#   25%未満   → 11.8% (-10.1pt)  n=1063
# 場経験0〜1走はベースと有意差なし → 0.0（分析: analyze/venue_aptitude_calibration.py）
_MIN_VENUE_RUNS = 2

# 配点（バックテストスイープで最適化する。キーは場複勝率帯）
# 【却下 2026-07-19】4配点案すべてで実運用買い目のROIがベースライン比で改善せず:
#   案1 +2/+1/0/-1.5   : 馬連1-2 128.1→107.1% / 三連複1-2-3 143.6→82.2%
#   案A 減点のみ-1.5    : 馬連 123.3% / 三連複1-2-3 143.6%（同値）だが1軸4頭 79.5→71.1%
#   案B 半減 +1/+0.5/-0.75: 馬連 116.3% / 三連複1-2-3 76.8%
#   案C 加点のみ +1/+0.5 : 馬連 116.3% / 三連複1-2-3 76.8%
# 原因: 馬単位の予測力（キャリブレーション+16.5pt）は本物だが、
#   場巧者は市場・既存項目（複勝安定/同コース実績）に織り込み済みで順位入替が配当を悪化させる。
# → FEATURE_FLAGS["venue_aptitude"] は False 固定（本番使用禁止）
VENUE_WEIGHTS = {
    "hi":  2.0,   # 場複勝率 75%以上
    "mid": 1.0,   # 50〜75%
    "low": 0.0,   # 25〜50%
    "bad": -1.5,  # 25%未満
}


def venue_aptitude_score(pasts: list, race_venue: str) -> float:
    """当該競馬場での過去走複勝率に基づく加減点"""
    if not FEATURE_FLAGS["venue_aptitude"]:
        return 0.0
    runs = [p for p in pasts if p.venue == race_venue and p.position > 0]
    if len(runs) < _MIN_VENUE_RUNS:
        return 0.0
    rate = sum(1 for p in runs if p.position <= 3) / len(runs)
    if rate >= 0.75:
        return VENUE_WEIGHTS["hi"]
    if rate >= 0.50:
        return VENUE_WEIGHTS["mid"]
    if rate >= 0.25:
        return VENUE_WEIGHTS["low"]
    return VENUE_WEIGHTS["bad"]
