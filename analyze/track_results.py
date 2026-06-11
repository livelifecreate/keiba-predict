"""
投票記録・収支管理

使い方:
  python3 track_results.py add                  # 対話形式で記録追加
  python3 track_results.py summary              # 収支サマリー
  python3 track_results.py list                 # 記録一覧
  python3 track_results.py list --month 2026-06 # 月別絞り込み

データ保存先: betting_log.json
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json, datetime, argparse
from collections import defaultdict

LOG_PATH = os.path.join(os.path.dirname(__file__), "betting_log.json")

# ── データ読み書き ─────────────────────────────────────────────────────

def load_log() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        return json.load(f)

def save_log(log: list):
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

# ── 入力ヘルパー ─────────────────────────────────────────────────────

def ask(prompt, default="", choices=None):
    if choices:
        prompt += f" [{'/'.join(choices)}]"
    if default:
        prompt += f" (省略={default})"
    prompt += ": "
    while True:
        val = input(prompt).strip() or default
        if not choices or val in choices:
            return val
        print(f"  入力値が不正です。{choices} のいずれかを入力してください。")

def ask_int(prompt, default=0):
    val = input(f"{prompt} (省略={default}): ").strip()
    try:
        return int(val) if val else default
    except ValueError:
        return default

# ── サブコマンド ─────────────────────────────────────────────────────

def cmd_add(args):
    log = load_log()
    today = datetime.date.today().isoformat()

    # 引数が揃っていればそのまま記録（チャットからの自動実行用）
    if args.date and args.venue and args.race and args.horses:
        date     = args.date
        parts    = args.race.split(" ", 1)
        race_num = parts[0]
        name     = parts[1] if len(parts) > 1 else ""
        venue    = args.venue
        surface  = args.surface
        sign     = args.sign
        horses   = args.horses
        amount   = args.amount
        result   = args.result
        payout   = args.payout
        race_id  = args.race_id
    else:
        # 対話形式（ターミナルから直接使う場合）
        print("\n── 投票記録追加 ──")
        date     = ask("日付 (例: 2026-06-14)",  default=today)
        venue    = ask("競馬場 (例: 東京)")
        race_num = ask("レース番号 (例: 11R)")
        name     = ask("レース名 (例: 安田記念)")
        surface  = ask("芝/ダート", default="芝", choices=["芝", "ダート"])
        sign     = ask("買いサイン", default="フォームB",
                       choices=["7点推奨", "フォームB", "フォームB穴軸", "フォームB横並び", "フォームB多頭"])
        horses   = ask("買い目 (例: 3-7-12)")
        amount   = ask_int("賭け金（円）", default=100)
        result   = ask("結果", default="外れ", choices=["当たり", "外れ"])
        payout   = ask_int("払戻金（円・外れは0）", default=0)
        race_id  = ask("race_id (省略可)", default="")

    profit = payout - amount

    entry = {
        "date":     date,
        "venue":    venue,
        "race":     f"{race_num} {name}",
        "surface":  surface,
        "sign":     sign,
        "horses":   horses,
        "amount":   amount,
        "result":   result,
        "payout":   payout,
        "profit":   profit,
        "race_id":  race_id,
    }

    log.append(entry)
    save_log(log)

    mark = "✅" if result == "当たり" else "❌"
    print(f"\n{mark} 記録しました: {date} {venue}{race_num} {name}  "
          f"賭:{amount:,}円 → 払:{payout:,}円  損益:{profit:+,}円")


def cmd_list(args):
    log = load_log()
    if not log:
        print("記録なし")
        return

    if args.month:
        log = [e for e in log if e["date"].startswith(args.month)]

    if not log:
        print(f"{args.month} の記録なし")
        return

    print(f"\n{'日付':<12} {'会場':>4} {'レース':<16} {'サイン':<12} "
          f"{'買い目':<12} {'賭け':>6} {'払戻':>8} {'損益':>8}")
    print("─" * 90)
    for e in sorted(log, key=lambda x: x["date"]):
        mark = "◎" if e["result"] == "当たり" else "×"
        print(f"{e['date']:<12} {e['venue']:>4} {e['race']:<16} "
              f"{e['sign']:<12} {e['horses']:<12} "
              f"{e['amount']:>6,} {e['payout']:>8,} {e['profit']:>+8,}  {mark}")


def cmd_summary(args):
    log = load_log()
    if not log:
        print("記録なし")
        return

    if args.month:
        log = [e for e in log if e["date"].startswith(args.month)]
        title = f"{args.month} の収支"
    else:
        title = "全期間の収支"

    total_bet    = sum(e["amount"] for e in log)
    total_pay    = sum(e["payout"] for e in log)
    total_profit = total_pay - total_bet
    hits         = sum(1 for e in log if e["result"] == "当たり")
    roi          = total_pay / total_bet * 100 if total_bet else 0

    print(f"\n{'='*50}")
    print(f"  {title}  ({len(log)}レース)")
    print(f"{'='*50}")
    print(f"  総賭け金:  {total_bet:>10,} 円")
    print(f"  総払戻:    {total_pay:>10,} 円")
    print(f"  損益:      {total_profit:>+10,} 円  ({'黒字' if total_profit >= 0 else '赤字'})")
    print(f"  命中率:    {hits}/{len(log)} = {hits/len(log)*100:.1f}%")
    print(f"  ROI:       {roi:.1f}%")

    # サイン別集計
    by_sign = defaultdict(lambda: {"n":0,"bet":0,"pay":0,"hit":0})
    for e in log:
        s = by_sign[e["sign"]]
        s["n"]   += 1
        s["bet"] += e["amount"]
        s["pay"] += e["payout"]
        s["hit"] += 1 if e["result"] == "当たり" else 0

    print(f"\n  サイン別:")
    print(f"  {'サイン':<16} {'N':>4}  {'命中率':>6}  {'ROI':>7}  {'損益':>10}")
    print(f"  {'─'*16} {'─'*4}  {'─'*6}  {'─'*7}  {'─'*10}")
    for sign, s in sorted(by_sign.items(), key=lambda x: x[1]["pay"]/max(x[1]["bet"],1), reverse=True):
        roi_s = s["pay"] / s["bet"] * 100 if s["bet"] else 0
        prf   = s["pay"] - s["bet"]
        print(f"  {sign:<16} {s['n']:>4}  {s['hit']/s['n']*100:>5.1f}%  "
              f"{roi_s:>6.1f}%  {prf:>+10,}")

    # 月別推移
    by_month = defaultdict(lambda: {"bet":0,"pay":0})
    for e in log:
        ym = e["date"][:7]
        by_month[ym]["bet"] += e["amount"]
        by_month[ym]["pay"] += e["payout"]

    if len(by_month) > 1:
        print(f"\n  月別推移:")
        for ym in sorted(by_month.keys()):
            m = by_month[ym]
            prf = m["pay"] - m["bet"]
            roi_m = m["pay"] / m["bet"] * 100 if m["bet"] else 0
            print(f"  {ym}  賭:{m['bet']:>8,}  払:{m['pay']:>8,}  "
                  f"損益:{prf:>+8,}  ROI:{roi_m:.1f}%")


# ── エントリポイント ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="投票記録・収支管理")
    sub = parser.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="記録追加")
    p_add.add_argument("--date",    default="", help="日付 (例: 2026-06-14)")
    p_add.add_argument("--venue",   default="", help="競馬場 (例: 東京)")
    p_add.add_argument("--race",    default="", help="レース (例: '11R 安田記念')")
    p_add.add_argument("--surface", default="芝", choices=["芝", "ダート"])
    p_add.add_argument("--sign",    default="フォームB",
                       help="買いサイン (7点推奨/フォームB/フォームB穴軸/フォームB横並び/フォームB多頭)")
    p_add.add_argument("--horses",  default="", help="買い目 (例: 3-7-12)")
    p_add.add_argument("--amount",  type=int, default=100, help="賭け金（円）")
    p_add.add_argument("--result",  default="外れ", choices=["当たり", "外れ"])
    p_add.add_argument("--payout",  type=int, default=0, help="払戻金（円）")
    p_add.add_argument("--race-id", dest="race_id", default="")

    p_list = sub.add_parser("list",    help="記録一覧")
    p_list.add_argument("--month", default="", help="月絞り込み (例: 2026-06)")

    p_sum = sub.add_parser("summary", help="収支サマリー")
    p_sum.add_argument("--month",  default="", help="月絞り込み (例: 2026-06)")

    args = parser.parse_args()

    if args.cmd == "add":
        cmd_add(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "summary":
        cmd_summary(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
