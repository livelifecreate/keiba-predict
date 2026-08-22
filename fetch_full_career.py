"""
バックテスト対象馬の「通算全成績」を取得して cache/horse_full_history/ に保存する。

背景（2026-07-19・条件適性4指数プロジェクトの結論）:
  horse_history スナップショットは直近5走のみのため、場別・条件別の通算適性が
  「近走の好調さ」と区別できず、条件適性系の新指数が全て検証不合格になった。
  競馬新聞には通算場別成績が掲載されており市場は織り込み済み。
  → 馬ページの全成績を1回取得し、レース日でフィルタすれば
    リークなしの as-of-date 通算成績を任意のカットオフで再構成できる。

保存形式: cache/horse_full_history/{horse_id}.json
  fetch_missing_history.fetch_full_history() の生レコードのリスト（全走・日付降順）。
  レース日以前のみに絞る処理は分析側で行う（1馬1ファイル・再取得不要）。

使い方:
  python3 fetch_full_career.py --test        # 3頭のみ（動作確認）
  python3 fetch_full_career.py --run         # 本番（対象全馬・中断後は再開可能）
  python3 fetch_full_career.py --run --limit 500   # 件数を区切って実行

⚠️ 開催日（土日）の日中は実行しないこと。netkeiba のピーク負荷を避け、
   当日予想のオッズ取得が巻き添えでブロックされるリスクを避けるため。
   推奨: 平日または開催日の深夜。リクエスト間隔は2.0〜3.0秒。
"""
import sys, json, re, time, random, argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from fetch_missing_history import fetch_full_history

BASE = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE = BASE / 'cache' / 'race_result'
OUT_DIR = BASE / 'cache' / 'horse_full_history'
TARGET_CLASSES = {"2勝クラス", "3勝クラス", "OP", "重賞"}


def is_weekend_daytime() -> bool:
    now = datetime.now()
    return now.weekday() in (5, 6) and 8 <= now.hour < 18


def target_horse_ids() -> list[str]:
    """バックテスト対象期間（2025/07 + 2025/10〜2026/06・2勝以上）のユニーク馬ID"""
    ids = set()
    for f in sorted(CACHE_RACE.glob('*.json')):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get('race_class') not in TARGET_CLASSES or d.get('surface') not in ('芝', 'ダ'):
            continue
        m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", d.get('date', ''))
        if not m:
            continue
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        in_scope = (datetime(2025, 7, 1) <= dt <= datetime(2025, 7, 31)) or \
                   (datetime(2025, 10, 1) <= dt <= datetime(2026, 6, 30))
        if not in_scope:
            continue
        for e in d['entries']:
            if e.get('horse_id'):
                ids.add(e['horse_id'])
    return sorted(ids)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='3頭のみテスト')
    parser.add_argument('--run', action='store_true', help='本番実行')
    parser.add_argument('--limit', type=int, default=0, help='今回の最大取得数（分割実行用）')
    parser.add_argument('--force-weekend', action='store_true',
                        help='開催日日中ガードを無視（通常は使わない）')
    args = parser.parse_args()

    if not (args.test or args.run):
        parser.print_help()
        return

    if is_weekend_daytime() and not args.force_weekend:
        sys.exit("⚠️ 開催日（土日）の日中です。netkeiba負荷と当日予想への影響を避けるため中止。\n"
                 "   深夜または平日に実行してください（--force-weekend で強制可能）。")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ids = target_horse_ids()
    pending = [h for h in ids if not (OUT_DIR / f'{h}.json').exists()]
    print(f"対象: {len(ids)}頭 / 取得済み: {len(ids) - len(pending)}頭 / 残り: {len(pending)}頭")

    if args.test:
        pending = pending[:3]
        print("テストモード: 3頭のみ")
    elif args.limit:
        pending = pending[:args.limit]
        print(f"分割実行: 今回 {len(pending)}頭")

    fetched = errors = empty = 0
    start = time.time()
    for i, hid in enumerate(pending):
        if i % 50 == 0 and i > 0:
            elapsed = time.time() - start
            eta = elapsed / i * (len(pending) - i) / 60
            print(f"  {i}/{len(pending)}頭 (取得{fetched}/空{empty}/エラー{errors}) 残り約{eta:.0f}分", flush=True)

        time.sleep(random.uniform(2.0, 3.0))
        try:
            records = fetch_full_history(hid)  # fetch側にも0.8s sleepあり
        except Exception as e:
            errors += 1
            print(f"  エラー {hid}: {e}")
            continue

        if not records:
            empty += 1
            # 空でもファイルを書く（再実行時のスキップ用・後で見直せるよう空リスト）
            (OUT_DIR / f'{hid}.json').write_text('[]')
            continue

        (OUT_DIR / f'{hid}.json').write_text(
            json.dumps(records, ensure_ascii=False))
        fetched += 1

        if args.test:
            print(f"\n--- {hid}: 全{len(records)}走 ---")
            for rec in records[:3]:
                print(f"  {rec['date_raw']} {rec['kaisan']} {rec['race_raw']} {rec['pos_raw']}着")

    print(f"\n完了: 取得={fetched} / 空={empty} / エラー={errors} / 経過{(time.time()-start)/60:.1f}分")
    remaining = len([h for h in ids if not (OUT_DIR / f'{h}.json').exists()])
    print(f"残り未取得: {remaining}頭")


if __name__ == '__main__':
    main()
