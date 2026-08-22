"""
条件適性指数のablation用再採点ランナー

対象期間: 2025/07/01〜31 + 2025/10/01〜2026/06/30（2勝クラス以上・芝ダ）
※ 2024/7 は horse_history スナップショット未取得のため対象外（2026-07-18確認）

使い方:
  python3 verify/rerun_with_flags.py --label baseline
  python3 verify/rerun_with_flags.py --flag venue_aptitude --label venue_on

出力: data/検証_条件適性_{label}.csv（bet_metrics_standard.py --csv に渡せる形式）
"""
import sys, re, json, csv, argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

import aptitude_index
from rerun_all import process_race  # noqa: E402  (verify/ から実行時)

BASE = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE = BASE / 'cache' / 'race_result'


def in_scope(date_str: str) -> bool:
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not m:
        return False
    dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (datetime(2025, 7, 1) <= dt <= datetime(2025, 7, 31)) or \
           (datetime(2025, 10, 1) <= dt <= datetime(2026, 6, 30))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--flag", action="append", default=[],
                        help="ONにする指数名（例: venue_aptitude）複数指定可")
    parser.add_argument("--label", required=True, help="出力CSVのラベル")
    args = parser.parse_args()

    for f in args.flag:
        if f not in aptitude_index.FEATURE_FLAGS:
            sys.exit(f"未知のフラグ: {f}")
        aptitude_index.FEATURE_FLAGS[f] = True

    print(f"フラグ状態: {aptitude_index.FEATURE_FLAGS}")
    print("対象期間: 2025/07 + 2025/10〜2026/06（2勝クラス以上）")

    all_rows, races, skipped = [], 0, 0
    files = sorted(CACHE_RACE.glob("*.json"))
    for i, f in enumerate(files):
        if i % 200 == 0:
            print(f"  {i}/{len(files)}件走査中... (採点済み {races}R)", flush=True)
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if not in_scope(data.get("date", "")):
            continue
        rows = process_race(data, use_training=True)
        if rows:
            all_rows.extend(rows)
            races += 1
        else:
            skipped += 1

    print(f"採点完了: {races}R / {len(all_rows)}行 (対象外スキップ: {skipped})")

    # 芝とダートで採点項目の列が異なるため、全行のunionをfieldnamesにする
    fieldnames = list(all_rows[0].keys())
    seen = set(fieldnames)
    for r in all_rows:
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)

    out = BASE / "data" / f"検証_条件適性_{args.label}.csv"
    with open(out, "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"CSV保存: {out}")


if __name__ == "__main__":
    main()
