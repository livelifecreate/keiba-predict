"""
競馬場巧者指数のキャリブレーション分析（実装前検証・scorer変更なし）

対象: 2025/07 + 2025/10〜2026/06 の 2勝クラス以上（芝・ダ）
各馬の過去走スナップショット（2年縛り内・最大5走）から
「当該レースと同じ競馬場での過去走数・複勝率」を計算し、
実際の3着以内率との関係を出す。

シグナルが存在するか（=当該場の過去複勝率が高い馬は実際に走るか）を確認する。
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
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    dt = datetime(y, mo, d)
    if datetime(2025, 7, 1) <= dt <= datetime(2025, 7, 31):
        return dt
    if datetime(2025, 10, 1) <= dt <= datetime(2026, 6, 30):
        return dt
    return None


def main():
    # バケット: (当該場の過去走数, 複勝率帯) → [3着以内数, 総数]
    by_runs = defaultdict(lambda: [0, 0])          # 場経験数別
    by_rate = defaultdict(lambda: [0, 0])          # 場複勝率帯別(2走以上のみ)
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
        venue = d.get('venue', '')
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

            vruns = [p for p in pasts if p.venue == venue]
            n = len(vruns)
            top3 = 1 if rank <= 3 else 0
            overall[0] += top3
            overall[1] += 1

            key = min(n, 4)  # 0,1,2,3,4+
            by_runs[key][0] += top3
            by_runs[key][1] += 1

            if n >= 2:
                vrate = sum(1 for p in vruns if p.position <= 3) / n
                if vrate >= 0.75:
                    b = '75%+'
                elif vrate >= 0.5:
                    b = '50-75%'
                elif vrate >= 0.25:
                    b = '25-50%'
                elif vrate > 0:
                    b = '1-25%'
                else:
                    b = '0%'
                by_rate[b][0] += top3
                by_rate[b][1] += 1

    base = overall[0] / overall[1] * 100
    print(f"対象: {races}R / {overall[1]}頭  全体3着以内率(ベース): {base:.1f}%")
    print()
    print("【当該場の過去走数別】(2年内・最大5走中)")
    print("  場経験 |   頭数 | 3着以内率 | ベース比")
    for k in sorted(by_runs):
        hit, tot = by_runs[k]
        r = hit / tot * 100
        label = f"{k}走" if k < 4 else "4走+"
        print(f"  {label:>5} | {tot:6} | {r:8.1f}% | {r - base:+.1f}pt")
    print()
    print("【当該場複勝率帯別】(場経験2走以上のみ)")
    print("  複勝率帯 |   頭数 | 3着以内率 | ベース比")
    for b in ['0%', '1-25%', '25-50%', '50-75%', '75%+']:
        if b not in by_rate:
            continue
        hit, tot = by_rate[b]
        r = hit / tot * 100
        print(f"  {b:>7} | {tot:6} | {r:8.1f}% | {r - base:+.1f}pt")


if __name__ == '__main__':
    main()
