"""
主軸帯（2〜4.9倍）を多軸クロス分析
クラス×頭数×コース×スコア差×芝ダ で「買える条件」を探す
"""
import sys, csv, re, json
from pathlib import Path
from collections import defaultdict

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

def get_trio_payout(race_id):
    p = cache_get('payouts', race_id)
    if not p: return None, 0
    v = p.get('3連複', {})
    raw = v.get('raw', [])
    if len(raw) < 3: return None, 0
    hnums   = parse_horse_nums(raw[1]) if raw[1] else []
    amounts = parse_amounts(raw[2])    if raw[2] else []
    if len(hnums) < 3 or not amounts: return None, 0
    return frozenset(hnums[:3]), amounts[0]

def load_races():
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
        actual_top3 = {h['馬名'] for h in horses if h['実着順'] and int(h['実着順']) <= 3}
        if len(actual_top3) < 3: continue
        race_id = name_to_id.get(key, '')
        if not race_id: continue
        try:
            odds = float(horses[0]['単勝オッズ'])
            gap  = float(horses[0]['予想スコア']) - float(horses[1]['予想スコア'])
        except ValueError:
            continue

        predicted_nums = []
        for i in range(1, min(len(horses)+1, 16)):
            h = horses[i-1]
            try: predicted_nums.append(int(h['馬番']))
            except: pass

        trio_win, trio_pay = get_trio_payout(race_id)
        result.append({
            'key':    key,
            'class':  horses[0]['クラス'],
            'surface': horses[0]['コース'],
            'n_horses': len(horses),
            'top1_odds': odds,
            'gap':    round(gap, 2),
            'predicted_nums': predicted_nums,
            'trio_win': trio_win,
            'trio_pay': trio_pay,
        })
    return result

def box5_roi(races):
    """5頭BOX（10点）ROI / 的中率"""
    invest = collect = hits = 0
    for r in races:
        if not r['trio_win'] or r['trio_pay'] == 0: continue
        invest += 1000
        top5 = set(r['predicted_nums'][:5])
        if r['trio_win'].issubset(top5):
            collect += r['trio_pay']; hits += 1
    n = sum(1 for r in races if r['trio_win'] and r['trio_pay'] > 0)
    if n == 0: return None
    roi     = collect / invest * 100 if invest else 0
    hit_pct = hits / n * 100
    return {'n': n, 'roi': roi, 'hit': hit_pct, 'hits': hits}

def print_row(label, races, indent=0):
    r = box5_roi(races)
    if r is None or r['n'] < 5: return
    mark = ' ◀' if r['roi'] >= 150 else (' △' if r['roi'] >= 100 else '')
    pad = '  ' * indent
    print(f"  {pad}{label:<30} n={r['n']:>3}  ROI={r['roi']:>5.0f}%  的中率={r['hit']:>4.1f}%  ({r['hits']}件){mark}")

# ---------------------------------------------------------------
races_all = load_races()
shuji = [r for r in races_all if 2.0 < r['top1_odds'] <= 4.9]

print(f"\n{'='*68}")
print(f"  主軸帯（2〜4.9倍）クロス分析　5頭BOX(10点)　n={len([r for r in shuji if r['trio_win'] and r['trio_pay']>0])}")
print(f"{'='*68}")

# ── クラス別
print("\n[クラス別]")
for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
    print_row(cls, [r for r in shuji if r['class'] == cls])

# ── コース別
print("\n[コース別]")
for surf in ['芝', 'ダ']:
    print_row(surf, [r for r in shuji if r['surface'] == surf])

# ── 頭数別
print("\n[頭数別]")
for label, cond in [
    ('〜12頭',   lambda r: r['n_horses'] <= 12),
    ('13〜17頭', lambda r: 13 <= r['n_horses'] <= 17),
    ('18頭',     lambda r: r['n_horses'] == 18),
]:
    print_row(label, [r for r in shuji if cond(r)])

# ── スコア差別（1位と2位の差）
print("\n[スコア差別（1位-2位）]")
for label, cond in [
    ('差0〜2',   lambda r: r['gap'] <= 2),
    ('差2〜5',   lambda r: 2 < r['gap'] <= 5),
    ('差5〜10',  lambda r: 5 < r['gap'] <= 10),
    ('差10以上', lambda r: r['gap'] > 10),
]:
    print_row(label, [r for r in shuji if cond(r)])

# ── クラス×頭数 クロス
print("\n[クラス × 頭数 クロス]")
for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
    for label, cond in [
        ('〜12頭',   lambda r: r['n_horses'] <= 12),
        ('13〜17頭', lambda r: 13 <= r['n_horses'] <= 17),
    ]:
        sub = [r for r in shuji if r['class'] == cls and cond(r)]
        if len([r for r in sub if r['trio_win'] and r['trio_pay']>0]) >= 5:
            print_row(f"{cls} × {label}", sub, indent=1)

# ── クラス×コース クロス
print("\n[クラス × コース クロス]")
for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
    for surf in ['芝', 'ダ']:
        sub = [r for r in shuji if r['class'] == cls and r['surface'] == surf]
        if len([r for r in sub if r['trio_win'] and r['trio_pay']>0]) >= 5:
            print_row(f"{cls} × {surf}", sub, indent=1)

# ── 頭数×コース クロス
print("\n[頭数 × コース クロス]")
for label, cond in [
    ('〜12頭',   lambda r: r['n_horses'] <= 12),
    ('13〜17頭', lambda r: 13 <= r['n_horses'] <= 17),
]:
    for surf in ['芝', 'ダ']:
        sub = [r for r in shuji if cond(r) and r['surface'] == surf]
        if len([r for r in sub if r['trio_win'] and r['trio_pay']>0]) >= 5:
            print_row(f"{label} × {surf}", sub, indent=1)

# ── スコア差×クラス
print("\n[スコア差 × クラス]")
for gap_label, gap_cond in [
    ('差5以上',  lambda r: r['gap'] > 5),
    ('差10以上', lambda r: r['gap'] > 10),
]:
    for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
        sub = [r for r in shuji if gap_cond(r) and r['class'] == cls]
        if len([r for r in sub if r['trio_win'] and r['trio_pay']>0]) >= 5:
            print_row(f"{gap_label} × {cls}", sub, indent=1)

# ── 参考：中穴帯との比較
print(f"\n[参考: 中穴帯（5〜9.9倍）クラス別]")
chuana = [r for r in races_all if 5.0 <= r['top1_odds'] <= 9.9]
for cls in ['2勝クラス', '3勝クラス', 'OP', '重賞']:
    print_row(cls, [r for r in chuana if r['class'] == cls])
