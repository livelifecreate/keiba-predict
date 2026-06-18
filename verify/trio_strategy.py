"""
3連複 買い方戦略の網羅的ROI比較
ながし / フォーメーション / BOX を実際の払い戻しデータで検証
"""
import sys, csv, re, json
from pathlib import Path
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from cache_store import cache_get

BASE    = Path('/Users/du/Documents/競馬予想システム')
CSV_PATH = BASE / 'data' / '検証_新ロジック_調教あり.csv'


# ---- パーサー ----------------------------------------------------------------

def parse_amounts(s: str) -> list[int]:
    return [int(m.replace(',', '')) for m in re.findall(r'[\d,]+(?=円)', s)]

def parse_horse_nums(s: str) -> list[int]:
    nums, i = [], 0
    while i < len(s):
        if i + 2 <= len(s) and int(s[i:i+2]) <= 18:
            nums.append(int(s[i:i+2]))
            i += 2
        else:
            nums.append(int(s[i:i+1]))
            i += 1
    return nums

def get_trio_payout(race_id: str) -> tuple[frozenset, int]:
    """(winning 3頭, 3連複配当)"""
    p = cache_get('payouts', race_id)
    if not p:
        return None, 0
    v = p.get('3連複', {})
    raw = v.get('raw', [])
    if len(raw) < 3:
        return None, 0
    hnums   = parse_horse_nums(raw[1]) if raw[1] else []
    amounts = parse_amounts(raw[2])    if raw[2] else []
    if len(hnums) < 3 or not amounts:
        return None, 0
    return frozenset(hnums[:3]), amounts[0]


# ---- データ読み込み -----------------------------------------------------------

def load_races(surface_filter=None):
    with open(CSV_PATH, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    races_dict = defaultdict(list)
    for r in rows:
        races_dict[(r['日付'], r['レース名'])].append(r)

    name_to_id = {}
    for f in (BASE / 'cache' / 'race_result').glob('*.json'):
        try:
            d = json.loads(f.read_text())
            name_to_id[(d['date'], d['race_name'])] = d['race_id']
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

        race_id = name_to_id.get(key, '')
        if not race_id:
            continue

        try:
            odds = float(horses[0]['単勝オッズ'])
            gap  = float(horses[0]['予想スコア']) - float(horses[1]['予想スコア'])
        except ValueError:
            continue

        def horse_num(rank):
            h = horses[rank-1] if len(horses) >= rank else None
            if h is None: return None
            try: return int(h['馬番'])
            except: return None

        predicted_nums = [horse_num(i) for i in range(1, min(len(horses)+1, 16))]
        predicted_nums = [n for n in predicted_nums if n]

        trio_win, trio_pay = get_trio_payout(race_id)

        result.append({
            'key': key,
            'class': horses[0]['クラス'],
            'surface': horses[0]['コース'],
            'n_horses': len(horses),
            'race_id': race_id,
            'top1_odds': odds,
            'gap': round(gap, 2),
            'predicted_nums': predicted_nums,
            'trio_win': trio_win,
            'trio_pay': trio_pay,
        })
    return result


# ---- 戦略シミュレーター ------------------------------------------------------

def sim_nagashi(races, n_aite: int) -> dict:
    """1位軸 + 上位N頭から2頭 ながし = C(n,2)点"""
    points = n_aite * (n_aite - 1) // 2
    invest, collect, hits = 0, 0, 0
    for r in races:
        if not r['trio_win'] or r['trio_pay'] == 0:
            continue
        invest += points * 100
        p1 = r['predicted_nums'][0] if r['predicted_nums'] else None
        aite = set(r['predicted_nums'][1:n_aite+1])
        if p1 is None: continue
        # 的中: 1位が winning trio に含まれ、残り2頭が aite に含まれる
        if p1 in r['trio_win'] and r['trio_win'].issubset({p1} | aite):
            collect += r['trio_pay']
            hits += 1
    n = sum(1 for r in races if r['trio_win'] and r['trio_pay'] > 0)
    return {'name': f'1軸-{n_aite}頭ながし({points}点)', 'points': points,
            'n': n, 'invest': invest, 'collect': collect, 'hits': hits}

def sim_formation(races, a_size: int, b_size: int) -> dict:
    """フォーメーション: 1位軸 × {2〜A+1位}(A頭) × {2〜B+1位}(B頭)"""
    # 点数 = C(A,2) + A×(B-A)  ※B > A前提
    a_set_size = a_size
    b_set_size = b_size
    # 重複排除済みの組み合わせ数を正確計算
    invest, collect, hits = 0, 0, 0
    actual_points_list = []
    for r in races:
        if not r['trio_win'] or r['trio_pay'] == 0:
            continue
        p1 = r['predicted_nums'][0] if r['predicted_nums'] else None
        a_horses = set(r['predicted_nums'][1:a_size+1])
        b_horses = set(r['predicted_nums'][1:b_size+1])
        if p1 is None: continue

        # ユニーク組み合わせ生成（フォームBと同ロジック）
        combos = set()
        for a in a_horses:
            for b in b_horses:
                if a != b:
                    combos.add(frozenset([p1, a, b]))
        pts = len(combos)
        actual_points_list.append(pts)
        invest += pts * 100
        if r['trio_win'] in combos:
            collect += r['trio_pay']
            hits += 1

    avg_pts = sum(actual_points_list) / len(actual_points_list) if actual_points_list else 0
    n = len(actual_points_list)
    return {'name': f'1-{a_size}-{b_size} フォーメーション({avg_pts:.0f}点)',
            'points': avg_pts, 'n': n, 'invest': invest, 'collect': collect, 'hits': hits}

def sim_box(races, n_horses: int) -> dict:
    """N頭BOX = C(N,3)点"""
    points = n_horses * (n_horses-1) * (n_horses-2) // 6
    invest, collect, hits = 0, 0, 0
    for r in races:
        if not r['trio_win'] or r['trio_pay'] == 0:
            continue
        invest += points * 100
        top_n = set(r['predicted_nums'][:n_horses])
        if r['trio_win'].issubset(top_n):
            collect += r['trio_pay']
            hits += 1
    n = sum(1 for r in races if r['trio_win'] and r['trio_pay'] > 0)
    return {'name': f'{n_horses}頭BOX({points}点)', 'points': points,
            'n': n, 'invest': invest, 'collect': collect, 'hits': hits}


# ---- 出力 -------------------------------------------------------------------

def print_results(label, races):
    strategies = [
        sim_nagashi(races, 3),
        sim_nagashi(races, 4),
        sim_nagashi(races, 5),
        sim_nagashi(races, 6),
        sim_nagashi(races, 7),
        sim_nagashi(races, 8),
        sim_formation(races, 3, 7),    # 1-3-7
        sim_formation(races, 3, 9),    # 1-3-9
        sim_formation(races, 4, 7),    # 1-4-7
        sim_formation(races, 4, 8),    # 1-4-8 (現フォームB)
        sim_formation(races, 4, 9),    # 1-4-9
        sim_formation(races, 5, 9),    # 1-5-9
        sim_box(races, 4),
        sim_box(races, 5),
        sim_box(races, 6),
        sim_box(races, 7),
    ]

    n = strategies[0]['n']
    print(f"\n[{label}] n={n}レース")
    print(f"  {'戦略':<34} {'点数':>5} {'ROI':>7} {'的中率':>7} {'的中数':>5} {'回収/R':>8}")
    print(f"  {'-'*72}")
    for s in strategies:
        if s['invest'] == 0: continue
        roi     = s['collect'] / s['invest'] * 100
        hit_pct = s['hits'] / s['n'] * 100 if s['n'] > 0 else 0
        per_r   = s['collect'] / s['n'] if s['n'] > 0 else 0
        invest_r = s['invest'] / s['n'] if s['n'] > 0 else 0
        marker  = ' ◀' if roi >= 200 else (' △' if roi >= 150 else '')
        print(f"  {s['name']:<34} {s['points']:>5.0f}点 {roi:>6.0f}% {hit_pct:>6.1f}% {s['hits']:>5} {int(per_r):>6,}円/{int(invest_r):,}円{marker}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--surface', choices=['芝', 'ダ'])
    args = parser.parse_args()

    races = load_races(surface_filter=args.surface)
    surf_label = args.surface or '全体'

    print(f"\n{'='*78}")
    print(f"  3連複 戦略別ROI比較（実配当使用）[{surf_label}]")
    print(f"  ※回収/R = 1レースあたり回収額/投資額")
    print(f"{'='*78}")

    print_results("全レース", races)

    print(f"\n── オッズ区分 ──")
    for label, cond in [
        ("1.0-2.0倍(断然)",  lambda r: r['top1_odds'] <= 2.0),
        ("2.1-4.9倍(主軸)",  lambda r: 2.0 < r['top1_odds'] <= 4.9),
        ("5.0-9.9倍(中穴)",  lambda r: 5.0 <= r['top1_odds'] <= 9.9),
        ("10.0-19.9倍(穴)",  lambda r: 10.0 <= r['top1_odds'] <= 19.9),
        ("20倍以上(大穴)",   lambda r: r['top1_odds'] >= 20.0),
    ]:
        print_results(label, [r for r in races if cond(r)])

    print(f"\n── 頭数別 ──")
    for label, cond in [
        ("〜12頭",   lambda r: r['n_horses'] <= 12),
        ("13-17頭",  lambda r: 13 <= r['n_horses'] <= 17),
        ("18頭",     lambda r: r['n_horses'] == 18),
    ]:
        print_results(label, [r for r in races if cond(r)])

    print(f"\n── クラス別 ──")
    for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
        print_results(cls, [r for r in races if r['class'] == cls])
