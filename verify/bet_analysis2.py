"""
実際の払い戻しデータを使った馬券種別ROI検証
複勝・馬連・ワイド・3連複・単勝を正確計算
"""
import sys, csv, re, json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from cache_store import cache_get

BASE    = Path('/Users/du/Documents/競馬予想システム')
CSV_PATH = BASE / 'data' / '検証_新ロジック_調教あり.csv'


# ---- 払い戻しパーサー --------------------------------------------------------

def parse_amounts(s: str) -> list[int]:
    """'1,390円540円110円' → [1390, 540, 110]"""
    return [int(m.replace(',', '')) for m in re.findall(r'[\d,]+(?=円)', s)]

def parse_horse_nums(s: str) -> list[int]:
    """'11144' → [11, 14, 4]  ※馬番は1〜18"""
    nums, i = [], 0
    while i < len(s):
        if i + 2 <= len(s) and int(s[i:i+2]) <= 18:
            nums.append(int(s[i:i+2]))
            i += 2
        else:
            nums.append(int(s[i:i+1]))
            i += 1
    return nums


def get_payout(race_id: str, bet_type: str) -> tuple[list[int], list[int]]:
    """(horse_nums, amounts) を返す。取得失敗 → ([], [])"""
    p = cache_get('payouts', race_id)
    if not p:
        return [], []
    v = p.get(bet_type, {})
    raw = v.get('raw', [])
    if len(raw) < 3:
        return [], []
    horse_nums = parse_horse_nums(raw[1]) if raw[1] else []
    amounts    = parse_amounts(raw[2])    if raw[2] else []
    return horse_nums, amounts


# ---- データ読み込み ----------------------------------------------------------

def load_races(surface_filter=None):
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    races_dict = defaultdict(list)
    for r in rows:
        key = (r['日付'], r['レース名'])
        races_dict[key].append(r)

    # race_id を race_result から引く（race_id = ファイル名）
    race_result_dir = BASE / 'cache' / 'race_result'
    name_to_id = {}
    for f in race_result_dir.glob('*.json'):
        try:
            d = json.loads(f.read_text())
            k = (d['date'], d['race_name'])
            name_to_id[k] = d['race_id']
        except Exception:
            pass

    result = []
    for key, horses in races_dict.items():
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
            sc1  = float(horses[0]['予想スコア'])
            sc2  = float(horses[1]['予想スコア'])
        except ValueError:
            continue

        gap  = round(sc1 - sc2, 2)
        race_id = name_to_id.get(key, '')

        # 各予想順位の馬番・実着順を収集
        def get_horse(rank):
            h = horses[rank - 1] if len(horses) >= rank else None
            if h is None:
                return None, 99
            try:
                num  = int(h['馬番'])
                act  = int(h['実着順']) if h['実着順'] else 99
            except ValueError:
                return None, 99
            return num, act

        p1_num, p1_act = get_horse(1)
        p2_num, p2_act = get_horse(2)
        p3_num, p3_act = get_horse(3)
        p4_num, p4_act = get_horse(4)
        p5_num, p5_act = get_horse(5)

        top5_nums = [n for n in [p1_num, p2_num, p3_num, p4_num, p5_num] if n]
        top5_in_top3 = sum(1 for h in horses[:5]
                           if h['実着順'] and int(h['実着順']) <= 3)

        result.append({
            'key': key,
            'date': horses[0]['日付'],
            'name': horses[0]['レース名'],
            'class': horses[0]['クラス'],
            'surface': horses[0]['コース'],
            'n_horses': len(horses),
            'race_id': race_id,
            'top1_odds': odds,
            'gap': gap,
            'p1_num': p1_num, 'p1_act': p1_act,
            'p2_num': p2_num, 'p2_act': p2_act,
            'p3_num': p3_num, 'p3_act': p3_act,
            'p4_num': p4_num, 'p4_act': p4_act,
            'p5_num': p5_num, 'p5_act': p5_act,
            'top5_nums': top5_nums,
            'top5_in_top3': top5_in_top3,
            'actual_top3': actual_top3,
        })
    return result


# ---- 各馬券のROI計算 ---------------------------------------------------------

def sim_tan(races):
    """単勝：1位予想馬 1点100円"""
    invest = len(races) * 100
    collect = sum(r['top1_odds'] * 100 for r in races if r['p1_act'] == 1)
    return invest, collect

def sim_fuku(races):
    """複勝：1位予想馬 1点100円"""
    invest, collect = 0, 0
    for r in races:
        invest += 100
        if r['p1_act'] > 3 or not r['race_id']:
            continue
        hnums, amounts = get_payout(r['race_id'], '複勝')
        if not hnums or not amounts or len(hnums) < 3:
            continue
        try:
            idx = hnums.index(r['p1_num'])
            if idx < len(amounts):
                collect += amounts[idx]
        except ValueError:
            pass
    return invest, collect

def sim_baren(races):
    """馬連：1位+2位 1点100円"""
    invest, collect = 0, 0
    for r in races:
        invest += 100
        if not r['race_id'] or r['p1_num'] is None or r['p2_num'] is None:
            continue
        hnums, amounts = get_payout(r['race_id'], '馬連')
        if not hnums or not amounts:
            continue
        # 馬連は1着・2着の2頭（hnumsの最初の2頭）
        winning = frozenset(hnums[:2])
        bet     = frozenset([r['p1_num'], r['p2_num']])
        if bet == winning:
            collect += amounts[0]
    return invest, collect

def sim_wide_1(races):
    """ワイド：1位+2位 1点100円"""
    invest, collect = 0, 0
    for r in races:
        invest += 100
        if not r['race_id'] or r['p1_num'] is None or r['p2_num'] is None:
            continue
        hnums, amounts = get_payout(r['race_id'], 'ワイド')
        if not hnums or not amounts:
            continue
        # ワイド = 3ペア × 各1点
        pairs = [(hnums[i*2], hnums[i*2+1]) for i in range(len(amounts))
                 if i*2+1 < len(hnums)]
        bet = frozenset([r['p1_num'], r['p2_num']])
        for j, (a, b) in enumerate(pairs):
            if bet == frozenset([a, b]) and j < len(amounts):
                collect += amounts[j]
                break
    return invest, collect

def sim_wide_3(races):
    """ワイド：1位+2位, 1位+3位, 2位+3位 3点300円"""
    invest, collect = 0, 0
    for r in races:
        invest += 300
        if not r['race_id']:
            continue
        hnums, amounts = get_payout(r['race_id'], 'ワイド')
        if not hnums or not amounts:
            continue
        pairs = [(hnums[i*2], hnums[i*2+1]) for i in range(len(amounts))
                 if i*2+1 < len(hnums)]
        winning_pairs = {frozenset([a, b]) for a, b in pairs}
        payout_map    = {frozenset([a, b]): amounts[j]
                         for j, (a, b) in enumerate(pairs) if j < len(amounts)}

        bets = []
        for a, b in [(r['p1_num'], r['p2_num']),
                     (r['p1_num'], r['p3_num']),
                     (r['p2_num'], r['p3_num'])]:
            if a and b:
                bets.append(frozenset([a, b]))

        for bet in bets:
            if bet in payout_map:
                collect += payout_map[bet]
    return invest, collect

def sim_wide_box5(races):
    """ワイド5頭BOX：C(5,2)=10点 1000円"""
    invest, collect = 0, 0
    for r in races:
        invest += 1000
        if not r['race_id'] or len(r['top5_nums']) < 2:
            continue
        hnums, amounts = get_payout(r['race_id'], 'ワイド')
        if not hnums or not amounts:
            continue
        pairs = [(hnums[i*2], hnums[i*2+1]) for i in range(len(amounts))
                 if i*2+1 < len(hnums)]
        payout_map = {frozenset([a, b]): amounts[j]
                      for j, (a, b) in enumerate(pairs) if j < len(amounts)}

        top5 = r['top5_nums']
        for i in range(len(top5)):
            for j in range(i+1, len(top5)):
                bet = frozenset([top5[i], top5[j]])
                if bet in payout_map:
                    collect += payout_map[bet]
    return invest, collect

def sim_trio_formb(races):
    """3連複フォームB（1位軸×{2〜5位}×{2〜9位}）22点 2200円"""
    def formb_cost(n_h):
        if n_h <= 10: return 1200
        if n_h <= 13: return 1800
        return 2200

    invest, collect = 0, 0
    for r in races:
        cost = formb_cost(r['n_horses'])
        invest += cost
        if not r['race_id']:
            continue
        hnums, amounts = get_payout(r['race_id'], '3連複')
        if not hnums or not amounts:
            continue
        # フォームB的中 = 1位が3着以内 AND top5_in_top3 >= 2
        if r['p1_act'] <= 3 and r['top5_in_top3'] >= 2:
            collect += amounts[0]
    return invest, collect

def sim_trio_box5(races):
    """3連複5頭BOX：C(5,3)=10点 1000円"""
    invest, collect = 0, 0
    for r in races:
        invest += 1000
        if not r['race_id'] or len(r['top5_nums']) < 3:
            continue
        hnums, amounts = get_payout(r['race_id'], '3連複')
        if not hnums or not amounts:
            continue
        winning = frozenset(hnums[:3])
        top5    = set(r['top5_nums'])
        if winning.issubset(top5):
            collect += amounts[0]
    return invest, collect


# ---- サマリー出力 ------------------------------------------------------------

def print_summary(label, races):
    if not races:
        print(f"  {label}: データなし")
        return
    n = len(races)

    sims = [
        ("単勝  1点", sim_tan(races), 100),
        ("複勝  1点", sim_fuku(races), 100),
        ("馬連  1点", sim_baren(races), 100),
        ("ワイド1点(1+2位)", sim_wide_1(races), 100),
        ("ワイド3点(上位3頭)", sim_wide_3(races), 300),
        ("ワイドBOX10点(上位5頭)", sim_wide_box5(races), 1000),
        ("3連複フォームB", sim_trio_formb(races), None),
        ("3連複5頭BOX10点", sim_trio_box5(races), 1000),
    ]

    print(f"\n  [{label}] n={n}レース")
    print(f"  {'馬券種別':<22} {'投資合計':>8} {'回収合計':>8} {'ROI':>7}  {'的中率':>7}")
    print(f"  {'-'*60}")
    for name, (inv, col), _unit in sims:
        roi = col / inv * 100 if inv > 0 else 0
        hit_count = '-'
        print(f"  {name:<22} {inv:>8,}円 {col:>8,.0f}円 {roi:>6.0f}%")


# ---- メイン ----------------------------------------------------------------

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--surface', choices=['芝', 'ダ'])
    parser.add_argument('--class_', dest='cls')
    args = parser.parse_args()

    races = load_races(surface_filter=args.surface)
    surf_label = args.surface or '全体'

    print(f"\n{'='*65}")
    print(f"  馬券種別ROI検証（実際の払い戻しデータ使用）[{surf_label}]")
    print(f"{'='*65}")

    # ---- 全体 ---------------------------------------------------------------
    print_summary("全レース", races)

    # ---- オッズ区分 ----------------------------------------------------------
    print(f"\n  ── オッズ区分 ──")
    bands = [
        ("1.0-2.0倍(断然)",  lambda r: r['top1_odds'] <= 2.0),
        ("2.1-4.9倍(主軸)",  lambda r: 2.0 < r['top1_odds'] <= 4.9),
        ("5.0-9.9倍(中穴)",  lambda r: 5.0 <= r['top1_odds'] <= 9.9),
        ("10.0-19.9倍(穴)",  lambda r: 10.0 <= r['top1_odds'] <= 19.9),
        ("20倍以上(大穴)",   lambda r: r['top1_odds'] >= 20.0),
    ]
    for label, cond in bands:
        print_summary(label, [r for r in races if cond(r)])

    # ---- スコア乖離 ---------------------------------------------------------
    print(f"\n  ── スコア乖離区分 ──")
    gap_bands = [
        ("0-2pt(横並び)",  lambda r: r['gap'] < 2.0),
        ("2-4pt(標準)",    lambda r: 2.0 <= r['gap'] < 4.0),
        ("4pt以上(差あり)", lambda r: r['gap'] >= 4.0),
    ]
    for label, cond in gap_bands:
        print_summary(label, [r for r in races if cond(r)])

    # ---- 頭数別 -------------------------------------------------------------
    print(f"\n  ── 頭数別 ──")
    head_bands = [
        ("〜12頭",          lambda r: r['n_horses'] <= 12),
        ("13-17頭",         lambda r: 13 <= r['n_horses'] <= 17),
        ("18頭",            lambda r: r['n_horses'] == 18),
    ]
    for label, cond in head_bands:
        print_summary(label, [r for r in races if cond(r)])

    # ---- クラス別 -----------------------------------------------------------
    print(f"\n  ── クラス別 ──")
    for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
        print_summary(cls, [r for r in races if r['class'] == cls])
