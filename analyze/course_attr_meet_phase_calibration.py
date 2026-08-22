"""
指数3コース属性適性・指数4開催時期補正のキャリブレーション（実装前検証・scorer変更なし）

対象: 2025/07 + 2025/10〜2026/06 の 2勝クラス以上（芝・ダ）

【指数3 コース属性】右左回り・急坂は既存項目と重複のため除外（2026-07-18ユーザー決定）。
残り4次元について、指数1・2の教訓から「乖離方式」（属性複勝率 − 非属性複勝率）で
季節指数と同様に独立シグナルの有無を判定する:
  - 回りサイズ: 小回り(中山福島小倉函館札幌) vs 大回り(東京京都阪神中京新潟)
  - 直線長さ:   長い(東京新潟阪神中京) vs 短い(中山京都福島小倉函館札幌)
  - 起伏:       平坦(京都新潟福島小倉札幌函館) vs 坂あり(東京中山阪神中京)
  - 芝種:       洋芝(札幌函館) vs 野芝(その他) ※芝レースのみ

【指数4 開催時期】race conditions「N回 場名 M日目」から開催フェーズを判定し、
脚質（detect_running_style）別の3着以内率をフェーズ別に比較する。
  開幕(1-2日目) / 中盤(3-6日目) / 終盤(7日目以降)
仮説: 開幕週=前残り(逃げ先行有利) / 終盤=差し有利
"""
import sys, re, json, glob
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from cache_store import cache_get_before
from scorer_turf import parse_past_race, parse_date, detect_running_style

TARGET = {"2勝クラス", "3勝クラス", "OP", "重賞"}

ATTR_DIMS = {
    '回りサイズ': {'小回り': {'中山', '福島', '小倉', '函館', '札幌'},
                '大回り': {'東京', '京都', '阪神', '中京', '新潟'}},
    '直線長さ':  {'長い': {'東京', '新潟', '阪神', '中京'},
                '短い': {'中山', '京都', '福島', '小倉', '函館', '札幌'}},
    '起伏':     {'平坦': {'京都', '新潟', '福島', '小倉', '札幌', '函館'},
                '坂あり': {'東京', '中山', '阪神', '中京'}},
    '芝種':     {'洋芝': {'札幌', '函館'},
                '野芝': {'東京', '中山', '京都', '阪神', '中京', '新潟', '福島', '小倉'}},
}


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


def attr_of(dim, venue):
    for label, venues in ATTR_DIMS[dim].items():
        if venue in venues:
            return label
    return None


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


def meet_phase(conditions):
    m = re.search(r"(\d+)日目", conditions or "")
    if not m:
        return None
    d = int(m.group(1))
    if d <= 2:
        return '開幕(1-2日)'
    if d <= 6:
        return '中盤(3-6日)'
    return '終盤(7日〜)'


def main():
    # 指数3: dim → 乖離帯 → [hit, total]
    attr_results = {d: defaultdict(lambda: [0, 0]) for d in ATTR_DIMS}
    attr_cov = {d: [0, 0] for d in ATTR_DIMS}
    # 指数4: phase → style → [hit, total]
    phase_results = defaultdict(lambda: defaultdict(lambda: [0, 0]))
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
        surface = d.get('surface', '')
        phase = meet_phase(d.get('conditions', ''))
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

            # --- 指数3: 属性乖離 ---
            for dim in ATTR_DIMS:
                if dim == '芝種' and surface != '芝':
                    continue
                race_attr = attr_of(dim, venue)
                if race_attr is None:
                    continue
                same, other = [], []
                for p in pasts:
                    if dim == '芝種' and p.surface != '芝':
                        continue
                    pa = attr_of(dim, p.venue)
                    if pa is None:
                        continue
                    (same if pa == race_attr else other).append(p)
                attr_cov[dim][1] += 1
                if len(same) >= 2 and len(other) >= 2:
                    attr_cov[dim][0] += 1
                    s = sum(1 for p in same if p.position <= 3) / len(same)
                    o = sum(1 for p in other if p.position <= 3) / len(other)
                    attr_results[dim][dev_bucket(s - o)][0] += top3
                    attr_results[dim][dev_bucket(s - o)][1] += 1

            # --- 指数4: 開催フェーズ×脚質 ---
            if phase:
                style = detect_running_style(pasts)
                phase_results[phase][style][0] += top3
                phase_results[phase][style][1] += 1

    base = overall[0] / overall[1] * 100
    print(f"対象: {races}R / {overall[1]}頭  全体3着以内率(ベース): {base:.1f}%\n")

    print("=" * 60)
    print("【指数3 コース属性適性】乖離方式（属性複勝率 − 非属性複勝率）")
    print("=" * 60)
    order = ['-0.5以下', '-0.25〜-0.5', '±0.25内', '+0.25〜0.5', '+0.5以上']
    for dim in ATTR_DIMS:
        cov = attr_cov[dim]
        pct = cov[0] / cov[1] * 100 if cov[1] else 0
        print(f"\n〔{dim}〕 乖離計算可能: {cov[0]}/{cov[1]}頭 ({pct:.1f}%)")
        print("  乖離帯        |   頭数 | 3着以内率 | ベース比")
        for b in order:
            if b not in attr_results[dim]:
                continue
            hit, tot = attr_results[dim][b]
            r = hit / tot * 100
            print(f"  {b:>10} | {tot:6} | {r:8.1f}% | {r - base:+.1f}pt")

    print()
    print("=" * 60)
    print("【指数4 開催時期補正】フェーズ×脚質別の3着以内率")
    print("=" * 60)
    for phase in ['開幕(1-2日)', '中盤(3-6日)', '終盤(7日〜)']:
        if phase not in phase_results:
            continue
        styles = phase_results[phase]
        n = sum(v[1] for v in styles.values())
        print(f"\n〔{phase}〕 n={n}頭")
        print("  脚質    |   頭数 | 3着以内率 | ベース比")
        for style in ['逃げ', '先行', '差し', '追込', '不明']:
            if style not in styles:
                continue
            hit, tot = styles[style]
            r = hit / tot * 100
            print(f"  {style:>4} | {tot:6} | {r:8.1f}% | {r - base:+.1f}pt")


if __name__ == '__main__':
    main()
