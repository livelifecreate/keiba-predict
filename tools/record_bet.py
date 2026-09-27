"""
実際に買った買い目を登録する（2026-09-27）

  python3 tools/record_bet.py --date 2026-09-27 --race 阪神10 --kind 馬連BOX --nums 1,10,2,6,5 --note "7→6（5か月休み明け）"
  python3 tools/record_bet.py --date 2026-09-27 --list          # 登録内容を表示
  python3 tools/record_bet.py --date 2026-09-27 --race 阪神10 --clear   # そのレースの登録を消す

- 券種: 単勝 / 複勝 / 馬連BOX / 馬連流し / ワイドBOX / ワイド流し / 三連複BOX / 三連複1軸流し
  （流しは --nums の先頭が軸）
- --unit は1点あたりの金額（既定100円）。--note にはシステムの予想から自分で変えた点を書く。
- 保存先は data/actual_bets.json。RACE_LOG.md の「実際の買い目」「実際の結果」列はここから作られる
  （update_race_log.py を実行し直しても消えない）。登録後は RACE_LOG を作り直す。
"""
import argparse, json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_race_log import BETS, BET_KIND, BASE, bet_text, load_bets, load_races


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--race", help="場名+R番号（例: 阪神10）")
    ap.add_argument("--kind", choices=list(BET_KIND))
    ap.add_argument("--nums", help="馬番をカンマ区切り（流しは先頭が軸）")
    ap.add_argument("--unit", type=int, default=100)
    ap.add_argument("--note", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--no-refresh", action="store_true", help="RACE_LOG を作り直さない")
    a = ap.parse_args()

    races = load_races(a.date)
    name = {x["rid"]: f"{x['venue']}{x['r']}R {x['name']}" for x in races}
    data = load_bets()
    day = data.setdefault(a.date, {})

    if a.list:
        for rid, bs in day.items():
            for b in bs:
                print(f"{name.get(rid, rid)}: {bet_text(b)}")
        return 0

    rid = next((x["rid"] for x in races if f"{x['venue']}{x['r']}" == a.race), None)
    if not rid:
        print(f"{a.date} の予想CSVに {a.race} が見つかりません（例: 阪神10）")
        return 1
    if a.clear:
        day.pop(rid, None)
    else:
        if not (a.kind and a.nums):
            print("--kind と --nums が必要です")
            return 1
        b = {"kind": a.kind, "nums": [int(n) for n in a.nums.split(",")], "unit": a.unit}
        if a.note:
            b["note"] = a.note
        day.setdefault(rid, []).append(b)
        print(f"登録: {name[rid]} {bet_text(b)}")
    BETS.parent.mkdir(parents=True, exist_ok=True)
    BETS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    if not a.no_refresh:   # 結果の出ているレースは的中・払戻まで入れて作り直す
        subprocess.run([sys.executable, str(BASE / "tools" / "update_race_log.py"), "--results", "--date", a.date])
    return 0


if __name__ == "__main__":
    sys.exit(main())
