"""三連複フォーメーション設定（1軸-相手）を一元管理するモジュール。

買い目を「1軸（予想1位固定）+ 相手（予想 N〜M 位）」の型に一本化する。
相手の順位幅だけをここで調整すれば weekend_predict.py / scorer_turf.py /
scorer_dart.py すべてに反映される（＝柔軟に対応するための唯一のパラメータ）。

決定根拠（全期間 n=688 バックテスト・払戻ベース）:
  1軸-相手2〜6位(10点)  的中18.5% / ROI115.4%  ← 5頭BOX(17.9%/108.8%)を両面で上回る
  1軸-相手2〜5位(6点)   的中14.1% / ROI138.5%  ← 攻めるならこちら
  予想順位別の複勝率は 1位49% > 2位42% > 3位35%… と単調で、1位が最も信頼できる軸。
  2軸型は不安定な予想2位を必須にするため夏に弱く、1軸型に統一した（2026-08-02）。
"""
from itertools import combinations

# 相手 = 予想 start〜end 位（1始まり・両端含む）。クラス別に上書き可能。
#   race_class: 0=未勝利 1=1勝 2=2勝 3=3勝 4=OP 5=GIII 6=GII 7=GI
# 例: 攻めたいクラスだけ (2, 5) にする等、ここを編集するだけで全体に反映される。
TRIO_RELAY = {
    "default": (2, 6),   # 1軸-相手5頭 = 10点
}


def _sort_key(x):
    return int(x) if str(x).isdigit() else 99


def relay_range(race_class):
    """そのクラスの相手順位範囲 (start, end) を返す。"""
    return TRIO_RELAY.get(race_class, TRIO_RELAY["default"])


def point_count(race_class):
    """買い点数（相手からの2頭組み合わせ数）を返す。"""
    start, end = relay_range(race_class)
    w = end - start + 1
    return w * (w - 1) // 2


def formation(nums, race_class):
    """予想順位順の馬番リスト nums から 1軸-相手 の三連複を組む。

    Returns: (axis, relay_list, combos, points)
      axis    : 軸馬番（予想1位）
      relay   : 相手馬番リスト（予想 start〜end 位）
      combos  : 三連複組み合わせ tuple のリスト（各要素は馬番3つ・昇順）
      points  : 点数
    """
    start, end = relay_range(race_class)
    axis = nums[0]
    relay = nums[start - 1:end]
    combos = sorted(
        {tuple(sorted((axis, a, b), key=_sort_key)) for a, b in combinations(relay, 2)},
        key=lambda c: tuple(_sort_key(x) for x in c),
    )
    return axis, relay, combos, len(combos)


def label(race_class):
    """CSV/表示用のラベル（例: '1軸-相手5頭 (10点)'）。"""
    start, end = relay_range(race_class)
    return f"1軸-相手{end - start + 1}頭 ({point_count(race_class)}点)"
