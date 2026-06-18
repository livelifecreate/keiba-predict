"""
馬連 買い方戦略の網羅的ROI比較
実際の払い戻しデータ使用
"""
import sys, csv, re, json
from pathlib import Path
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from cache_store import cache_get

BASE     = Path('/Users/du/Documents/競馬予想システム')
CSV_PATH = BASE / 'data' / '検証_新ロジック_調教あり.csv'


def parse_amounts(s):
    return [int(m.replace(',', '')) for m in re.findall(r'[\d,]+(?=円)', s)]

def parse_horse_nums(s):
    nums, i = [], 0
    while i < len(s):
        if i + 2 <= len(s) and int(s[i:i+2]) <= 18:
            nums.append(int(s[i:i+2])); i += 2
        else:
            nums.append(int(s[i:i+1])); i += 1
    return nums

def get_baren_payout(race_id):
    """(winning pair frozenset, 配当) を返す"""
    p = cache_get('payouts', race_id)
    if not p: return None, 0
    v = p.get('馬連', {})
    raw = v.get('raw', [])
    if len(raw) < 3: return None, 0
    hnums   = parse_horse_nums(raw[1]) if raw[1] else []
    amounts = parse_amounts(raw[2])    if raw[2] else []
    if len(hnums) < 2 or not amounts: return None, 0
    return frozenset(hnums[:2]), amounts[0]


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
        if len(horses) < 5: continue
        if surface_filter and horses[0]['コース'] != surface_filter: continue

        actual_top2 = {h['馬名'] for h in horses if h['実着順'] and int(h['実着順']) <= 2}
        if len(actual_top2) < 2: continue

        race_id = name_to_id.get(key, '')
        if not race_id: continue

        try:
            odds = float(horses[0]['単勝オッズ'])
            gap  = float(horses[0]['予想スコア']) - float(horses[1]['予想スコア'])
        except ValueError:
            continue

        def hnum(rank):
            h = horses[rank-1] if len(horses) >= rank else None
            if h is None: return None
            try: return int(h['馬番'])
            except: return None

        predicted = [hnum(i) for i in range(1, min(len(horses)+1, 12))]
        predicted = [n for n in predicted if n]

        win_pair, pay = get_baren_payout(race_id)

        result.append({
            'key': key,
            'class': horses[0]['クラス'],
            'surface': horses[0]['コース'],
            'n_horses': len(horses),
            'race_id': race_id,
            'top1_odds': odds,
            'gap': round(gap, 2),
            'predicted': predicted,
            'win_pair': win_pair,
            'pay': pay,
        })
    return result


# ---- シミュレーター ---------------------------------------------------------

def sim(races, bet_sets_fn, label, cost_per_race=None):
    """bet_sets_fn(race) → list of frozenset(2頭)"""
    invest, collect, hits, n = 0, 0, 0, 0
    for r in races:
        if not r['win_pair'] or r['pay'] == 0: continue
        bets = bet_sets_fn(r)
        if not bets: continue
        c = (cost_per_race or len(bets)) * 100
        invest += c
        n += 1
        for b in bets:
            if b == r['win_pair']:
                collect += r['pay']
                hits += 1
                break
    roi     = collect / invest * 100 if invest > 0 else 0
    hit_pct = hits / n * 100 if n > 0 else 0
    per_r   = collect / n if n > 0 else 0
    inv_r   = invest / n if n > 0 else 0
    pts     = invest / n / 100 if n > 0 else 0
    return {'label': label, 'pts': pts, 'n': n,
            'roi': roi, 'hit_pct': hit_pct, 'hits': hits,
            'per_r': per_r, 'inv_r': inv_r}

def nagashi(races, n_aite):
    """1位軸 → 上位N頭 ながし (N点)"""
    def bets(r):
        p1 = r['predicted'][0] if r['predicted'] else None
        if p1 is None: return []
        return [frozenset([p1, a]) for a in r['predicted'][1:n_aite+1]]
    return sim(races, bets, f'1位軸→上位{n_aite}頭({n_aite}点)')

def box(races, n_horses):
    """上位N頭BOX = C(N,2)点"""
    pts = n_horses * (n_horses - 1) // 2
    def bets(r):
        top = r['predicted'][:n_horses]
        return [frozenset([a, b]) for a, b in combinations(top, 2)]
    return sim(races, bets, f'上位{n_horses}頭BOX({pts}点)')

def two_axis(races, n_aite):
    """1位+2位 2頭軸 → 上位N頭 (N-2点)"""
    def bets(r):
        if len(r['predicted']) < 2: return []
        p1, p2 = r['predicted'][0], r['predicted'][1]
        return [frozenset([p1, p2])]
    # 実はただの1点（1位+2位固定）なので n_aite は意味なし
    return sim(races, bets, f'1位+2位 固定1点')

def axis_gap(races, n_aite):
    """乖離上位2頭 軸 + 残りN頭ながし"""
    def bets(r):
        if len(r['predicted']) < 2: return []
        p1, p2 = r['predicted'][0], r['predicted'][1]
        aite = [x for x in r['predicted'][2:n_aite+2] if x not in (p1, p2)]
        combos = [frozenset([p1, p2])]
        for a in aite:
            combos.append(frozenset([p1, a]))
            combos.append(frozenset([p2, a]))
        return list(set(combos))
    pts_approx = 1 + n_aite * 2
    return sim(races, bets, f'1+2位軸＋{n_aite}頭({pts_approx}点)')


def print_results(label, races):
    strategies = [
        nagashi(races, 1),
        nagashi(races, 2),
        nagashi(races, 3),
        nagashi(races, 4),
        nagashi(races, 5),
        nagashi(races, 6),
        nagashi(races, 7),
        box(races, 3),
        box(races, 4),
        box(races, 5),
        box(races, 6),
        two_axis(races, 0),
        axis_gap(races, 2),
        axis_gap(races, 3),
        axis_gap(races, 4),
    ]
    n = strategies[0]['n']
    print(f"\n[{label}] n={n}レース")
    print(f"  {'戦略':<28} {'点数':>4} {'ROI':>7} {'的中率':>7} {'的中数':>5} {'回収/R':>8}")
    print(f"  {'-'*65}")
    for s in strategies:
        if s['n'] == 0: continue
        mark = ' ◀' if s['roi'] >= 150 else (' △' if s['roi'] >= 120 else '')
        print(f"  {s['label']:<28} {s['pts']:>4.0f}点 {s['roi']:>6.0f}% "
              f"{s['hit_pct']:>6.1f}% {s['hits']:>5} "
              f"{int(s['per_r']):>5,}円/{int(s['inv_r']):,}円{mark}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--surface', choices=['芝', 'ダ'])
    args = parser.parse_args()

    races = load_races(surface_filter=args.surface)
    surf  = args.surface or '全体'

    print(f"\n{'='*68}")
    print(f"  馬連 戦略別ROI比較（実配当）[{surf}]")
    print(f"{'='*68}")

    print_results("全レース", races)

    print("\n── オッズ区分 ──")
    for lbl, cond in [
        ("1.0-2.0倍(断然)",  lambda r: r['top1_odds'] <= 2.0),
        ("2.1-4.9倍(主軸)",  lambda r: 2.0 < r['top1_odds'] <= 4.9),
        ("5.0-9.9倍(中穴)",  lambda r: 5.0 <= r['top1_odds'] <= 9.9),
        ("10.0-19.9倍(穴)",  lambda r: 10.0 <= r['top1_odds'] <= 19.9),
        ("20倍以上(大穴)",   lambda r: r['top1_odds'] >= 20.0),
    ]:
        print_results(lbl, [r for r in races if cond(r)])

    print("\n── スコア乖離 ──")
    for lbl, cond in [
        ("0-2pt(横並び)",  lambda r: r['gap'] < 2.0),
        ("2-4pt(標準)",    lambda r: 2.0 <= r['gap'] < 4.0),
        ("4pt以上(差あり)", lambda r: r['gap'] >= 4.0),
    ]:
        print_results(lbl, [r for r in races if cond(r)])

    print("\n── 頭数別 ──")
    for lbl, cond in [
        ("〜12頭",   lambda r: r['n_horses'] <= 12),
        ("13-17頭",  lambda r: 13 <= r['n_horses'] <= 17),
        ("18頭",     lambda r: r['n_horses'] == 18),
    ]:
        print_results(lbl, [r for r in races if cond(r)])

    print("\n── クラス別 ──")
    for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
        print_results(cls, [r for r in races if r['class'] == cls])
