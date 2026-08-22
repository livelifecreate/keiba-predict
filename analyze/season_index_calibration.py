"""
季節指数のキャリブレーション分析（実装前検証・scorer変更なし）

対象: 2025/07 + 2025/10〜2026/06 の 2勝クラス以上（芝・ダ）
各馬の過去走（2年縛り内・最大5走）から「当該レースと同じ季節バケットでの複勝率」を
3パターンで計算し、実際の3着以内率との関係を比較する。

パターン:
  P1 月別:   レース月と同じ月の過去走
  P2 四季:   春(3-5)/夏(6-8)/秋(9-11)/冬(12-2)
  P3 夏冬2区分: 夏(6-8) vs それ以外

各パターンで「同季節2走以上」の馬の季節複勝率帯別 → 実際3着以内率を出す。
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
    'P1_月別':  lambda m: m,
    'P2_四季':  season4,
    'P3_夏冬':  lambda m: '夏' if m in (6, 7, 8) else '非夏',
}


def rate_bucket(rate):
    if rate >= 0.75:
        return '75%+'
    if rate >= 0.50:
        return '50-75%'
    if rate >= 0.25:
        return '25-50%'
    return '<25%'


def main():
    # pattern → 複勝率帯 → [hit, total]
    results = {p: defaultdict(lambda: [0, 0]) for p in PATTERNS}
    coverage = {p: [0, 0] for p in PATTERNS}  # [2走以上該当, 全馬]
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
                sruns = []
                for p in pasts:
                    pdt = parse_date(p.date)
                    if pdt and fn(pdt.month) == race_bucket:
                        sruns.append(p)
                coverage[pname][1] += 1
                if len(sruns) >= 2:
                    coverage[pname][0] += 1
                    srate = sum(1 for p in sruns if p.position <= 3) / len(sruns)
                    results[pname][rate_bucket(srate)][0] += top3
                    results[pname][rate_bucket(srate)][1] += 1

    base = overall[0] / overall[1] * 100
    print(f"対象: {races}R / {overall[1]}頭  全体3着以内率(ベース): {base:.1f}%\n")

    for pname in PATTERNS:
        cov = coverage[pname]
        print(f"【{pname}】 同季節2走以上の馬: {cov[0]}/{cov[1]}頭 ({cov[0]/cov[1]*100:.1f}%)")
        print("  季節複勝率帯 |   頭数 | 3着以内率 | ベース比")
        for b in ['<25%', '25-50%', '50-75%', '75%+']:
            if b not in results[pname]:
                continue
            hit, tot = results[pname][b]
            r = hit / tot * 100
            print(f"  {b:>10} | {tot:6} | {r:8.1f}% | {r - base:+.1f}pt")
        print()


if __name__ == '__main__':
    main()
