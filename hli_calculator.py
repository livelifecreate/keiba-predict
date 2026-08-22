"""
Horse Level Index (HLI) calculator
過去走履歴から競走馬の潜在能力を数値化する。
目的: 市場人気との差異を発見すること（能力順位付けではない）。

V1 制約:
  - 上がり3F「順位」は未取得（タイムのみ保存）。次バージョンで対応予定。
  - 相手レベル補正はクラス到達点を代理値として使用（循環依存回避）。
"""

import re
import json
import time
import requests
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

BASE_DIR  = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache' / 'horse_history'
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
}

# ─── クラス定義 ───────────────────────────────────────────────────────────────

CLASS_POINTS = {
    '新馬': 20, '未勝利': 25, '1勝': 45, '2勝': 65,
    '3勝': 85, 'OP': 110, 'G3': 130, 'G2': 150, 'G1': 180,
}
CLASS_ORDER  = ['新馬', '未勝利', '1勝', '2勝', '3勝', 'OP', 'G3', 'G2', 'G1']
CLASS_RANK   = {c: i for i, c in enumerate(CLASS_ORDER)}
GRADED       = {'G1', 'G2', 'G3'}

# 昇級速度ボーナス: クラス内で勝つまでの試行数 → 加点
SPEED_TABLE = {
    '新馬':   {1: 20, 2: 15, 3: 10, 4: 5},
    '未勝利': {1: 15, 2: 10, 3: 5},
    '1勝':    {1: 20, 2: 12, 3: 5},
    '2勝':    {1: 20, 2: 12, 3: 5},
    '3勝':    {1: 20, 2: 12, 3: 5},
    'OP':     {1: 20, 2: 12, 3: 5},
    'G3':     {1: 20, 2: 12, 3: 5},
    'G2':     {1: 20, 2: 12, 3: 5},
}

# 停滞ペナルティ: 同クラスで勝てない継続レース数
STAGNATION_TABLE = [(1, 3, 0), (4, 5, -5), (6, 8, -10), (9, 999, -20)]


# ─── レース名 → クラス判定 ────────────────────────────────────────────────────

def _detect_class(race_name: str) -> str:
    n = race_name
    if re.search(r'GⅠ|GI\b|（GⅠ）|\(G1\)|ＧⅠ', n):  return 'G1'
    if re.search(r'GⅡ|GII\b|（GⅡ）|\(G2\)|ＧⅡ', n):  return 'G2'
    if re.search(r'GⅢ|GIII\b|（GⅢ）|\(G3\)|ＧⅢ', n): return 'G3'
    if re.search(r'新馬|メイクデビュー', n):        return '新馬'
    if re.search(r'未勝利', n):                    return '未勝利'
    if re.search(r'3勝クラス|1600万', n):          return '3勝'
    if re.search(r'2勝クラス|1000万', n):          return '2勝'
    if re.search(r'1勝クラス|500万', n):           return '1勝'
    return 'OP'


# ─── データ取得・キャッシュ ────────────────────────────────────────────────────

def fetch_horse_history(horse_id: str) -> list[dict]:
    """
    netkeiba の馬成績ページから全過去走を取得してキャッシュに保存。
    列マッピング（db.netkeiba.com/horse/result/{id}/）:
      [0]日付 [4]レース名 [6]頭数 [10]人気 [11]着順
      [19]着差 [27]上り(上がり3F秒) [14]距離
    """
    cache_path = CACHE_DIR / f'{horse_id}.json'
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding='utf-8'))

    url = f'https://db.netkeiba.com/horse/result/{horse_id}/'
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')
    except Exception:
        return []

    table = soup.find('table')
    if not table:
        return []

    history = []
    for row in table.find('tbody').find_all('tr'):
        cells = [td.get_text(strip=True) for td in row.find_all('td')]
        if len(cells) < 28:
            continue

        finish = 99
        try:
            finish = int(cells[11])
        except ValueError:
            pass

        margin = 0.0
        try:
            margin = abs(float(cells[19].replace('−', '-').replace('－', '-')))
        except ValueError:
            pass

        agari3f = 0.0
        try:
            agari3f = float(cells[27])
        except ValueError:
            pass

        history.append({
            'date':      cells[0],            # YYYY/MM/DD
            'race_name': cells[4],
            # class はキャッシュに持たない → calculate_hli() で動的に判定
            'n_horses':  int(cells[6]) if cells[6].isdigit() else 0,
            'popularity': int(cells[10]) if cells[10].isdigit() else 99,
            'finish':    finish,
            'margin':    margin,              # 勝利時の着差（秒）
            'agari3f':   agari3f,             # 上がり3F秒（順位はV2で対応）
            'distance':  cells[14],           # 例: 芝2200
        })

    cache_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    time.sleep(0.6)
    return history


# ─── HLI計算 ──────────────────────────────────────────────────────────────────

@dataclass
class HLIResult:
    horse_name:   str   = ''
    horse_id:     str   = ''
    total:        int   = 0
    class_pts:    int   = 0
    speed_bonus:  int   = 0
    win_content:  int   = 0
    opponent_pts: float = 0.0
    growth_pts:   int   = 0
    age_pts:      int   = 0
    stagnation:   int   = 0
    fukusho_pts:  int   = 0   # 複勝安定ボーナス（追加）
    best_class:   str   = ''
    grade:        str   = ''
    comment:      str   = ''


def _age_pts(age: int) -> int:
    return {3: 5, 4: 3, 5: 0}.get(age, -5)


def _grade_label(total: int) -> str:
    if total >= 150: return '重賞級候補'
    if total >= 120: return 'OP級能力'
    if total >= 90:  return '条件戦上位'
    if total >= 60:  return '平均的'
    return '成長待ち'


def calculate_hli(horse_id: str, horse_name: str, current_age: int = 4,
                  cutoff_date: Optional[str] = None,
                  lookback_years: int = 2) -> HLIResult:
    """
    cutoff_date: 'YYYY/MM/DD' 形式。指定するとその日付より前のデータのみ使用。
                 バックテスト時は必ずレース日付を渡すこと（データリーク防止）。
    lookback_years: cutoff_date から遡る年数。デフォルト2年。
                    古すぎるキャリア実績を除外して直近の実力を優先する。
    """
    res = HLIResult(horse_name=horse_name, horse_id=horse_id)
    history = fetch_horse_history(horse_id)
    if not history:
        return res

    hist = sorted(history, key=lambda x: x['date'])
    if cutoff_date:
        hist = [h for h in hist if h['date'] < cutoff_date]
        if lookback_years > 0:
            y = int(cutoff_date[:4]) - lookback_years
            start = f"{y}{cutoff_date[4:]}"
            hist = [h for h in hist if h['date'] >= start]
    if not hist:
        return res
    for h in hist:
        h['class'] = _detect_class(h['race_name'])

    # 1. クラス到達点（3着以内に入ったことがある最高クラスを使用）
    # 「出走しただけ」でフル点が付かないよう、好走実績ベースに補正
    best_cls = max(hist, key=lambda x: CLASS_RANK.get(x['class'], 0))['class']
    res.best_class = best_cls
    placed = [h['class'] for h in hist if h['finish'] <= 3]
    effective_cls = max(placed, key=lambda c: CLASS_RANK.get(c, 0)) if placed else CLASS_ORDER[0]
    res.class_pts  = CLASS_POINTS.get(effective_cls, 0)

    # クラスごとにレースをグループ化
    from collections import defaultdict
    by_class: dict[str, list] = defaultdict(list)
    for h in hist:
        by_class[h['class']].append(h)

    # 2. 昇級速度ボーナス
    speed = 0
    for cls, table in SPEED_TABLE.items():
        runs = by_class.get(cls, [])
        if not runs:
            continue
        for i, r in enumerate(runs, start=1):
            if r['finish'] == 1:
                speed += table.get(i, 0)
                break
    res.speed_bonus = speed

    # 3. 停滞ペナルティ（そのクラスで一度も勝てていないクラスに適用）
    stag = 0
    for cls, runs in by_class.items():
        if any(r['finish'] == 1 for r in runs):
            continue  # 勝利あり → 停滞なし
        has_graded = any(r['class'] in GRADED for r in runs)
        # 複勝率50%以上ならペナルティ50%減（善戦している証拠）
        fukusho_rate = sum(1 for r in runs if r['finish'] <= 3) / len(runs)
        n = len(runs)
        for lo, hi, penalty in STAGNATION_TABLE:
            if lo <= n <= hi:
                base = penalty
                if has_graded or fukusho_rate >= 0.5:
                    base = base // 2
                stag += base
                break
    res.stagnation = stag

    # 4. 勝利内容補正（最良1勝の着差）
    wins = [h for h in hist if h['finish'] == 1 and h['class'] not in ('新馬',)]
    win_content = 0
    if wins:
        best_win = max(wins, key=lambda x: x['margin'])
        m = best_win['margin']
        if m >= 0.7:   win_content = 8
        elif m >= 0.5: win_content = 5
        elif m >= 0.3: win_content = 3
        # 上がり3F順位はV2で追加予定
    res.win_content = win_content

    # 5. 相手レベル補正（勝利クラス点を代理値として使用）
    if wins:
        avg_cls_pt = sum(CLASS_POINTS.get(w['class'], 0) for w in wins) / len(wins)
        res.opponent_pts = round(avg_cls_pt * 0.05, 1)

    # 6. 成長補正（3歳時に2クラス以上を短期突破）
    growth = 0
    if current_age <= 3:
        classes_won = [h for h in hist if h['finish'] == 1]
        if len(classes_won) >= 2:
            from datetime import datetime
            d1 = classes_won[0]['date']
            d2 = classes_won[1]['date']
            try:
                dt1 = datetime.strptime(d1, '%Y/%m/%d')
                dt2 = datetime.strptime(d2, '%Y/%m/%d')
                if (dt2 - dt1).days <= 120:
                    growth = 10
            except ValueError:
                pass
    res.growth_pts = growth

    # 7. 年齢補正
    res.age_pts = _age_pts(current_age)

    # 8. 複勝安定ボーナス（直近10走の3着以内率）
    recent = sorted(hist, key=lambda x: x['date'], reverse=True)[:10]
    if recent:
        fuku_rate = sum(1 for r in recent if r['finish'] <= 3) / len(recent)
        if fuku_rate >= 0.7:
            res.fukusho_pts = 10
        elif fuku_rate >= 0.5:
            res.fukusho_pts = 5

    # 合算
    raw = (res.class_pts + res.speed_bonus + res.win_content
           + res.opponent_pts + res.growth_pts + res.age_pts
           + res.stagnation + res.fukusho_pts)
    res.total  = min(int(raw), 200)
    res.grade  = _grade_label(res.total)
    res.comment = _make_comment(res)
    return res


def _make_comment(r: HLIResult) -> str:
    parts = []
    if r.speed_bonus >= 30:
        parts.append(f"{r.best_class}まで高速昇級")
    elif r.speed_bonus >= 15:
        parts.append("昇級速度は良好")
    if r.fukusho_pts >= 10:
        parts.append("複勝安定性が非常に高い")
    elif r.fukusho_pts >= 5:
        parts.append("複勝安定性は良好")
    if r.stagnation <= -15:
        parts.append("現クラスで長期停滞")
    elif r.stagnation <= -5:
        parts.append("現クラスでやや停滞")
    if r.growth_pts > 0:
        parts.append("3歳時に急成長")
    if r.win_content >= 5:
        parts.append("大差勝ち実績あり")

    desc = "。".join(parts)
    return f"{r.grade}。{desc}" if desc else r.grade


# ─── キャッシュから馬IDマップを構築 ──────────────────────────────────────────────

def build_horse_id_map(race_result_dir: Optional[Path] = None) -> dict[str, tuple[str, int]]:
    """
    cache/race_result/*.json から {馬名: (horse_id, age)} を構築。
    ファイル名昇順でソートして処理するため、最新レース（日付が大きいファイル）の
    age_sex が最終的に採用される。これにより「牝3（2025年）→ 牝4（2026年）」と
    正しく更新される。
    """
    import glob as _glob
    if race_result_dir is None:
        race_result_dir = BASE_DIR / 'cache' / 'race_result'
    id_map: dict[str, tuple[str, int]] = {}
    for fp in sorted(_glob.glob(str(race_result_dir / '*.json'))):
        try:
            d = json.loads(Path(fp).read_text(encoding='utf-8'))
            for e in d.get('entries', []):
                name    = e.get('horse_name', '')
                hid     = e.get('horse_id', '')
                age_sex = e.get('age_sex', '4')
                age     = int(age_sex[1]) if len(age_sex) >= 2 and age_sex[1].isdigit() else 4
                if name and hid:
                    id_map[name] = (hid, age)
        except Exception:
            pass
    return id_map


# ─── レース単位で全馬HLIを取得 ────────────────────────────────────────────────

def get_race_hli(entries: list[dict]) -> dict[str, HLIResult]:
    """
    entries: weekend_predict の sorted_results から渡す馬リスト
    各要素は {'horse_name': str, 'horse_id': str, 'age': int} を想定

    Returns: {horse_name: HLIResult}
    """
    result = {}
    for e in entries:
        hid  = e.get('horse_id', '')
        name = e.get('horse_name', '')
        age  = e.get('age', 4)
        if not hid:
            continue
        result[name] = calculate_hli(hid, name, age)
        time.sleep(0.3)
    return result


def format_hli_table(hli_map: dict[str, HLIResult]) -> str:
    """予想出力用テキストテーブル"""
    header = f'{"馬名":<16} {"HLI":>4}  クラス/速度/勝内/複勝/相手/成長/年齢/停滞'
    lines = ['─' * 68, header, '─' * 68]
    for name, r in sorted(hli_map.items(), key=lambda x: -x[1].total):
        breakdown = (f'{r.class_pts}/{r.speed_bonus}/{r.win_content}/'
                     f'{r.fukusho_pts}/{r.opponent_pts}/{r.growth_pts}/{r.age_pts}/{r.stagnation}')
        lines.append(f'{name:<16} {r.total:>4}  {breakdown}  {r.grade}')
    lines.append('─' * 68)
    return '\n'.join(lines)


# ─── 単体テスト ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    horse_id   = sys.argv[1] if len(sys.argv) > 1 else '2020101323'
    horse_name = sys.argv[2] if len(sys.argv) > 2 else 'テスト馬'
    age        = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    print(f'HLI計算: {horse_name} (id={horse_id}, {age}歳)')
    r = calculate_hli(horse_id, horse_name, age)
    print(f'\n  HLI合計:  {r.total}  （上限200）')
    print(f'  評価:     {r.grade}')
    print(f'  最高クラス: {r.best_class}')
    print(f'\n  内訳:')
    print(f'    クラス到達点:  {r.class_pts:+d}')
    print(f'    昇級速度:      {r.speed_bonus:+d}')
    print(f'    勝利内容:      {r.win_content:+d}')
    print(f'    相手レベル:    {r.opponent_pts:+.1f}')
    print(f'    成長補正:      {r.growth_pts:+d}')
    print(f'    年齢補正:      {r.age_pts:+d}')
    print(f'    複勝安定:      {r.fukusho_pts:+d}')
    print(f'    停滞ペナルティ: {r.stagnation:+d}')
    print(f'\n  コメント: {r.comment}')
