"""
馬券種別・条件別ROI検証
検証_新ロジック_調教あり.csv を使用
単勝ROIは正確計算、三連複はモデル推定
"""
import sys, csv, json
from pathlib import Path
from collections import defaultdict

BASE = Path('/Users/du/Documents/競馬予想システム')
CSV_PATH = BASE / 'data' / '検証_新ロジック_調教あり.csv'

# ---- データ読み込み --------------------------------------------------------

def load_races(surface_filter=None):
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    races = defaultdict(list)
    for r in rows:
        key = (r['日付'], r['レース名'])
        races[key].append(r)

    result = []
    for key, horses in races.items():
        horses.sort(key=lambda x: int(x['予想順位']))
        if len(horses) < 5:
            continue
        if surface_filter and horses[0]['コース'] != surface_filter:
            continue

        actual_top3 = {h['馬名'] for h in horses if h['実着順'] and int(h['実着順']) <= 3}
        if len(actual_top3) < 3:
            continue

        top1 = horses[0]
        odds_str = top1['単勝オッズ']
        if not odds_str:
            continue
        try:
            odds = float(odds_str)
        except ValueError:
            continue

        # スコア乖離（1位と2位の差）
        try:
            sc1 = float(horses[0]['予想スコア'])
            sc2 = float(horses[1]['予想スコア'])
            gap = round(sc1 - sc2, 2)
        except (ValueError, IndexError):
            gap = 0.0

        top5_names = {h['馬名'] for h in horses[:5]}
        top5_in_top3 = len(top5_names & actual_top3)
        top1_actual = int(top1['実着順']) if top1['実着順'] else 99

        result.append({
            'key': key,
            'date': horses[0]['日付'],
            'name': horses[0]['レース名'],
            'class': horses[0]['クラス'],
            'surface': horses[0]['コース'],
            'n_horses': len(horses),
            'top1_odds': odds,
            'gap': gap,
            'top1_actual': top1_actual,
            'top5_in_top3': top5_in_top3,
            'actual_top3': actual_top3,
            'top5_names': top5_names,
            'horses': horses,
        })
    return result


# ---- 分析関数 ---------------------------------------------------------------

def calc_segment(races):
    """1セグメントの各指標を計算"""
    n = len(races)
    if n == 0:
        return None

    tan_hit = sum(1 for r in races if r['top1_actual'] == 1)
    fuku_hit = sum(1 for r in races if r['top1_actual'] <= 3)
    box5_hit = sum(1 for r in races if r['top5_in_top3'] == 3)
    formb_hit = sum(1 for r in races if r['top1_actual'] <= 3 and r['top5_in_top3'] >= 2)
    cover_avg = sum(r['top5_in_top3'] for r in races) / n

    # 単勝ROI（1点100円想定）
    tan_collect = sum(r['top1_odds'] * 100 for r in races if r['top1_actual'] == 1)
    tan_roi = tan_collect / (n * 100) * 100

    # 三連複5頭BOX想定（10点×100円=1000円投資）
    # 的中時平均配当を実際の配当がないため推定: クラス別平均
    # 2勝C≈3000, 3勝C≈4000, OP≈5000, 重賞≈7000
    class_avg_payout = {'2勝クラス': 3000, '3勝クラス': 4000, 'OP': 5000, '重賞': 7000}
    box5_collect = 0
    for r in races:
        if r['box5_in_top3'] if 'box5_in_top3' in r else r['top5_in_top3'] == 3:
            c = class_avg_payout.get(r['class'], 4000)
            box5_collect += c
    box5_roi = box5_collect / (n * 1000) * 100

    # フォームB（1位軸×{2〜5位}×{2〜9位} 三連複フォーメーション）
    # 点数: ≤10頭→12点, ≤13頭→18点, 14頭以上→22点
    def formb_cost(n_h):
        if n_h <= 10: return 1200
        if n_h <= 13: return 1800
        return 2200

    formb_collect = 0
    formb_invest = 0
    for r in races:
        cost = formb_cost(r['n_horses'])
        formb_invest += cost
        if r['top1_actual'] <= 3 and r['top5_in_top3'] >= 2:
            c = class_avg_payout.get(r['class'], 4000)
            formb_collect += c
    formb_roi = formb_collect / formb_invest * 100 if formb_invest > 0 else 0

    return {
        'n': n,
        'tan_pct': 100 * tan_hit / n,
        'fuku_pct': 100 * fuku_hit / n,
        'box5_pct': 100 * box5_hit / n,
        'formb_pct': 100 * formb_hit / n,
        'cover_avg': cover_avg,
        'tan_roi': tan_roi,
        'box5_roi': box5_roi,
        'formb_roi': formb_roi,
    }


def print_segment(label, races):
    s = calc_segment(races)
    if not s:
        print(f"  {label}: データなし")
        return
    print(f"  {label} (n={s['n']})")
    print(f"    単勝ROI: {s['tan_roi']:.0f}%  命中率:{s['tan_pct']:.1f}%")
    print(f"    複勝命中率: {s['fuku_pct']:.1f}%")
    print(f"    5頭BOX的中: {s['box5_pct']:.1f}%  推定ROI: {s['box5_roi']:.0f}%  (10点1000円/レース想定)")
    print(f"    フォームB的中: {s['formb_pct']:.1f}%  推定ROI: {s['formb_roi']:.0f}%  (22点2200円/レース想定)")
    print(f"    上位5頭カバー: {s['cover_avg']:.2f}頭/3頭中")


# ---- メイン ----------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--surface', choices=['芝', 'ダ'], help='芝/ダート絞り込み')
    args = parser.parse_args()

    races = load_races(surface_filter=args.surface)
    surf_label = args.surface or '全体'
    print(f"\n{'='*60}")
    print(f"  馬券戦略別ROI検証 [{surf_label}] n={len(races)}")
    print(f"{'='*60}")

    # ---- 1. 全体 -----------------------------------------------------------
    print("\n▼ 全体")
    print_segment("全レース", races)

    # ---- 2. オッズ区分 ------------------------------------------------------
    print("\n▼ 1位馬オッズ区分")
    bands = [
        ("1.0-2.0倍(断然)", lambda r: r['top1_odds'] <= 2.0),
        ("2.1-4.9倍(主軸)", lambda r: 2.0 < r['top1_odds'] <= 4.9),
        ("5.0-9.9倍(中穴)", lambda r: 5.0 <= r['top1_odds'] <= 9.9),
        ("10.0-19.9倍(穴)", lambda r: 10.0 <= r['top1_odds'] <= 19.9),
        ("20倍以上(大穴)",  lambda r: r['top1_odds'] >= 20.0),
    ]
    for label, cond in bands:
        print_segment(label, [r for r in races if cond(r)])

    # ---- 3. スコア乖離区分 ---------------------------------------------------
    print("\n▼ スコア乖離区分（1位と2位の差）")
    gap_bands = [
        ("0-2pt (横並び)",  lambda r: r['gap'] < 2.0),
        ("2-4pt (標準)",    lambda r: 2.0 <= r['gap'] < 4.0),
        ("4-6pt (やや差)",  lambda r: 4.0 <= r['gap'] < 6.0),
        ("6pt以上 (明確差)", lambda r: r['gap'] >= 6.0),
    ]
    for label, cond in gap_bands:
        print_segment(label, [r for r in races if cond(r)])

    # ---- 4. オッズ×乖離 クロス（主要帯のみ） --------------------------------
    print("\n▼ オッズ×乖離 クロス（2.1-9.9倍）")
    mid_races = [r for r in races if 2.0 < r['top1_odds'] <= 9.9]
    for label, cond in gap_bands:
        print_segment(label, [r for r in mid_races if cond(r)])

    # ---- 5. クラス別 --------------------------------------------------------
    print("\n▼ クラス別")
    for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
        print_segment(cls, [r for r in races if r['class'] == cls])

    # ---- 6. 頭数別 ----------------------------------------------------------
    print("\n▼ 頭数別")
    head_bands = [
        ("〜12頭",   lambda r: r['n_horses'] <= 12),
        ("13-15頭",  lambda r: 13 <= r['n_horses'] <= 15),
        ("16-17頭",  lambda r: 16 <= r['n_horses'] <= 17),
        ("18頭(フルゲート)", lambda r: r['n_horses'] == 18),
    ]
    for label, cond in head_bands:
        print_segment(label, [r for r in races if cond(r)])

    # ---- 7. オッズ×乖離 最良条件サマリー -----------------------------------
    print("\n▼ 最良条件の組み合わせ（フォームB推定ROI上位）")
    conditions = []
    for o_label, o_cond in bands:
        for g_label, g_cond in gap_bands:
            seg = [r for r in races if o_cond(r) and g_cond(r)]
            s = calc_segment(seg)
            if s and s['n'] >= 10:
                conditions.append((o_label, g_label, s))

    conditions.sort(key=lambda x: x[2]['formb_roi'], reverse=True)
    print(f"  {'条件':<36} {'n':>4} {'単勝ROI':>8} {'複勝%':>7} {'フォームB%':>10} {'フォームBROI':>12}")
    print(f"  {'-'*80}")
    for o_l, g_l, s in conditions[:10]:
        label = f"{o_l} × {g_l}"
        print(f"  {label:<36} {s['n']:>4} {s['tan_roi']:>7.0f}% {s['fuku_pct']:>6.1f}% {s['formb_pct']:>9.1f}% {s['formb_roi']:>10.0f}%")
