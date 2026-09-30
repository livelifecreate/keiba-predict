"""
軸の参考表示（2026-09-30・表示のみ。AXIS_HINT=0 で無効）

予想1位が1番人気ではなく、1番人気が予想2〜3位にいるとき、
「1番人気を軸にした三連複」を参考として評価コメントに出す。本番の軸（予想1位）は変えない。

根拠（案G・2勝クラス以上・8頭以上・学習〜2025/06 / テスト2025/07〜。検証は 2026-09-30）:
  予想1位≠1番人気のとき、3着内率は1番人気のほうが高い（学習+22.9pt / テスト+17.1pt・n=719）。
  - 1番人気=予想2位（n=309）: 3着内率 予想1位40% / 1番人気67%、三連複的中 12.6%→19.1%、ROI 61%→90%
  - 1番人気=予想3位（n=177）: 3着内率 40% / 58%、三連複的中 16.4%→15.8%（ROIは上がるが高配当依存）
  - 1番人気=予想4〜5位: 3着内率は1番人気が上だが、軸を替えると三連複ROIが下がる（53〜75%）ので出さない
  買い条件（10〜13頭・重賞以外）に絞ると n=77/47 で結論は出ていない。ゲート基準（ROI>100%・高配当に依存しない）は未達。
  バックテストの人気は締切時のオッズ。予想時点（朝）の人気とは入れ替わることがある。
"""
import os
from itertools import combinations

NOTE = {
    2: "過去の同じ形（n=309）では 3着内率 予想1位40%・1番人気67%、三連複の的中率 13%→19%",
    3: "過去の同じ形（n=177）では 3着内率 予想1位40%・1番人気58%、三連複の的中率はほぼ同じ（16%）",
}


def enabled() -> bool:
    return os.environ.get("AXIS_HINT", "1") != "0"


def comment_lines(sorted_results, odds_map: dict) -> list[str]:
    """sorted_results は予想順（案G順）の [(entry, score), ...]。"""
    odds = [(i, odds_map.get(e.horse_name) or 0) for i, (e, _) in enumerate(sorted_results)]
    odds = [(i, o) for i, o in odds if o > 0]
    if len(odds) < 5:
        return []
    fav_i = min(odds, key=lambda x: x[1])[0]
    k = fav_i + 1
    if k not in NOTE:
        return []
    top5 = [e for e, _ in sorted_results[:5]]
    fav = top5[fav_i]
    top1 = top5[0]
    pop1 = 1 + sum(1 for _, o in odds if o < (odds_map.get(top1.horse_name) or 0))
    others = [e.horse_number for e in top5 if e is not fav]
    pts = len(list(combinations(others, 2)))
    return [f"【軸の参考】1番人気 {fav.horse_number}番{fav.horse_name}（{odds_map[fav.horse_name]:.1f}倍）は予想{k}位。"
            f"予想1位 {top1.horse_number}番{top1.horse_name} は{pop1}番人気。{NOTE[k]}",
            f"軸を替えるなら: 三連複 {fav.horse_number}番軸 - 相手 {','.join(map(str, others))}（{pts}点）"
            f" ※参考。本番の軸は予想1位のまま（買い条件内ではサンプル不足で未確定）"]
