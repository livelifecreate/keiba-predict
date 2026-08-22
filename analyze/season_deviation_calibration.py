"""
季節指数キャリブレーション第2弾: 「馬自身の通常成績との乖離」方式

絶対複勝率は近走の好調さ（複勝安定ボーナス・市場評価と重複）を測ってしまうため、
  乖離 = 同季節での複勝率 − 他季節での複勝率
で「季節固有の得意不得意」だけを分離し、実際の3着以内率と比較する。

条件: 同季節2走以上 かつ 他季節2走以上（両方ないと乖離が計算できない）
パターン: P2四季 / P3夏冬 の2種
"""
import sys, re, json, glob
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from cache_store import cache_get_before
from scorer_turf import parse_past_race, parse_date

TARGET = {"2勝クラス", "3勝クラス", "OP", "重賞"}


def in_scope(date_str):
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not m:
        return None
    dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if datetime(2025, 7, 1) <= dt <= datetime(2025, 7, 31):
        return dt
    if datetime(2025, 10, 1) <= dt <= datetime(2026, 6, 30):
        return dt
    return None


def season4(month):
    if month in (3, 4, 5):
        return '春'
    if month in (6, 7, 8):
        return '夏'
    if month in (9, 10, 11):
        return '秋'
    return '冬'


PATTERNS = {
    'P2_四季': season4,
    'P3_夏冬': lambda m: '夏' if m in (6, 7, 8) else '非夏',
}


def dev_bucket(dev):
    if dev >= 0.5:
        return '+0.5以上'
    if dev >= 0.25:
        return '+0.25〜0.5'
    if dev > -0.25:
        return '±0.25内'
    if dev > -0.5:
        return '-0.25〜-0.5'
    return '-0.5以下'


def main():
    results = {p: defaultdict(lambda: [0, 0]) for p in PATTERNS}
    coverage = {p: [0, 0] for p in PATTERNS}
    overall = [0, 0]
    races = 0

    for f in sorted(glob.glob('cache/race_result/*.json')):
        d = json.load(open(f))
        if d.get('race_class') not in TARGET or d.get('surface') not in ('芝', 'ダ'):
            continue
        dt = in_scope(d.get('date', ''))
        if dt is None:
            continue
        cutoff = dt.strftime('%Y/%m/%d')
        cutoff_2y = dt - timedelta(days=365 * 2)
        races += 1

        for e in d['entries']:
            hid = e.get('horse_id', '')
            rank = e.get('rank', 99)
            if not hid or not isinstance(rank, int):
                continue
            recent = cache_get_before('horse_history', hid, cutoff) or []
            pasts = [p for p in (parse_past_race(r) for r in recent) if p]
            pasts = [p for p in pasts
                     if (parse_date(p.date) or cutoff_2y) >= cutoff_2y
                     and p.position > 0 and not p.is_overseas]
            top3 = 1 if rank <= 3 else 0
            overall[0] += top3
            overall[1] += 1

            for pname, fn in PATTERNS.items():
                race_bucket = fn(dt.month)
                same, other = [], []
                for p in pasts:
                    pdt = parse_date(p.date)
                    if not pdt:
                        continue
                    (same if fn(pdt.month) == race_bucket else other).append(p)
                coverage[pname][1] += 1
                if len(same) >= 2 and len(other) >= 2:
                    coverage[pname][0] += 1
                    s_rate = sum(1 for p in same if p.position <= 3) / len(same)
                    o_rate = sum(1 for p in other if p.position <= 3) / len(other)
                    dev = s_rate - o_rate
                    results[pname][dev_bucket(dev)][0] += top3
                    results[pname][dev_bucket(dev)][1] += 1

    base = overall[0] / overall[1] * 100
    print(f"対象: {races}R / {overall[1]}頭  全体3着以内率(ベース): {base:.1f}%\n")

    order = ['-0.5以下', '-0.25〜-0.5', '±0.25内', '+0.25〜0.5', '+0.5以上']
    for pname in PATTERNS:
        cov = coverage[pname]
        print(f"【{pname}】 乖離計算可能な馬: {cov[0]}/{cov[1]}頭 ({cov[0]/cov[1]*100:.1f}%)")
        print("  季節乖離帯     |   頭数 | 3着以内率 | ベース比")
        for b in order:
            if b not in results[pname]:
                continue
            hit, tot = results[pname][b]
            r = hit / tot * 100
            print(f"  {b:>10} | {tot:6} | {r:8.1f}% | {r - base:+.1f}pt")
        print()


if __name__ == '__main__':
    main()
