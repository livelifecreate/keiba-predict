#!/usr/bin/env python3
"""
夏サブセット(6-9月)のバックテストを会場別・クラス別に集計する。
現行ロジックで再採点済みの data/検証_新ロジック_調教あり.csv を入力に使う
（事前に verify/rerun_all.py で再生成しておくこと）。

会場は race_id の5-6桁目（場コード）から導出、季節は日付から判定。

使い方:
  python3 analyze/summer_venue_backtest.py                 # 夏6場（デフォルト）
  python3 analyze/summer_venue_backtest.py --surface 芝
"""
import sys, re, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verify.bet_metrics_standard import print_metrics_table, CLASSES
from verify.bet_analysis2 import load_races

PLACE = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
         "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
SUMMER_MONTHS = {6, 7, 8, 9}


def venue_of(r):
    rid = r.get("race_id", "")
    return PLACE.get(rid[4:6], "?") if len(rid) >= 6 else "?"


def month_of(r):
    m = re.search(r"年(\d{1,2})月", r.get("date", ""))
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--surface", choices=["芝", "ダ"], default="")
    args = ap.parse_args()

    races = load_races(surface_filter=args.surface or None)
    summer = [r for r in races if month_of(r) in SUMMER_MONTHS and venue_of(r) != "?"]

    surf = f" [{args.surface}]" if args.surface else ""
    print("=" * 66)
    print(f"  夏(6-9月)バックテスト 会場別・クラス別{surf}  n={len(summer)}")
    print("=" * 66)

    print("\n########## 夏 総合 ##########")
    print_metrics_table("夏 総合", summer)
    print("  ── 夏 クラス別 ──")
    for cls in CLASSES:
        sub = [r for r in summer if r.get("class") == cls]
        if sub:
            print_metrics_table(cls, sub, prefix="  ")

    print("\n########## 夏 会場別 ##########")
    venues = ["札幌", "函館", "福島", "新潟", "中京", "小倉"]
    for v in venues:
        vsub = [r for r in summer if venue_of(r) == v]
        if not vsub:
            continue
        print_metrics_table(f"夏 {v}", vsub)

    print("\n########## 夏 会場×クラス（2勝/3勝/OP のみ）##########")
    for v in venues:
        for cls in ["2勝クラス", "3勝クラス", "OP"]:
            sub = [r for r in summer if venue_of(r) == v and r.get("class") == cls]
            if len(sub) >= 5:
                print_metrics_table(f"夏 {v}×{cls}", sub, prefix="  ")


if __name__ == "__main__":
    main()
