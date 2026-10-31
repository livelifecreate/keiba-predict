"""
買い目の想定オッズ（2026-10-31・表示専用）

予想CSVの買い目と、odds_snapshot が保存した最新のオッズを突き合わせ、
Web画面（app.py）用に results/{日付}/{場}/odds_{race_id}.json を書き出す。
cache/ は git に載らないため、画面に出す分だけ results/ に置く。

  馬連5頭BOX（予想1〜5位・10点）… 全レースで常に出す
  三連複1軸-相手（CSVの買い目6点。無ければ予想1位軸-2〜5位）

  python3 bet_odds.py --date 2026-10-31   # その日の全レースを書き出し（odds_snapshot.py の後に実行）
"""
import argparse, csv, glob, json, re
from datetime import datetime
from itertools import combinations
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAP = BASE / "cache" / "odds_snapshots"


def latest_snapshot(race_id: str):
    files = sorted((SNAP / race_id).glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def read_csv(path: str):
    """(race_id, 予想順の馬番リスト, 三連複買い目[(a,b,c)...]) を返す"""
    race_id, ranked, trio = "", [], []
    section = "horses"
    with open(path, encoding="utf-8-sig", newline="") as f:
        for parts in csv.reader(f):
            if not parts:
                continue
            head = parts[0]
            if head == "■レース情報" and len(parts) > 2:
                race_id = parts[2]
            elif head == "■三連複1軸-相手":
                section = "trio"
            elif head.startswith("■"):
                section = "other"
            elif section == "horses" and head.isdigit() and len(parts) > 2 and parts[2].isdigit():
                ranked.append((int(head), int(parts[2])))
            elif section == "trio" and head == "" and len(parts) > 1:
                nums = [int(x) for x in re.findall(r"\d+", parts[1])]
                if len(nums) == 3:
                    trio.append(tuple(sorted(nums)))
    ranked = [n for _, n in sorted(ranked)]
    return race_id, ranked, trio


def _odds(table: dict, nums) -> float | None:
    key = "".join(f"{n:02d}" for n in sorted(nums))
    v = (table or {}).get(key)
    try:
        return float(v[0])
    except (TypeError, ValueError, IndexError):
        return None          # 取消・発売前など


def _block(table: dict, combos: list) -> dict:
    rows = [{"組": "-".join(str(n) for n in sorted(c)), "倍率": _odds(table, c)} for c in combos]
    vals = [r["倍率"] for r in rows if r["倍率"]]
    n = len(combos)
    return {
        "点数": n,
        "組み合わせ": rows,
        "最低": min(vals) if vals else None,
        "最高": max(vals) if vals else None,
        # 当たっても投資額（点数×100円）を下回る組み合わせの数
        "トリガミ": sum(1 for v in vals if v < n),
    }


def build(path: str) -> dict | None:
    race_id, ranked, trio = read_csv(path)
    if not re.fullmatch(r"\d{12}", race_id or "") or len(ranked) < 2:
        return None
    snap = latest_snapshot(race_id)
    if not snap:
        return None
    odds = snap.get("odds", {})
    top5 = ranked[:5]
    if not trio and len(ranked) >= 5:
        trio = [tuple(sorted((ranked[0], a, b))) for a, b in combinations(ranked[1:5], 2)]
    return {
        "race_id": race_id,
        "取得時刻": snap.get("fetched_at", ""),
        "馬連1-2": _odds(odds.get("4"), ranked[:2]),
        "馬連5頭BOX": {"馬番": top5, **_block(odds.get("4"), list(combinations(top5, 2)))},
        "三連複1軸": {"馬番": ranked[:5], **_block(odds.get("7"), trio)} if trio else None,
    }


def write_day(day: str) -> int:
    n = 0
    for p in sorted(glob.glob(str(BASE / "results" / day / "*" / "score_*.csv"))):
        try:
            d = build(p)
        except Exception as e:
            print(f"  [想定オッズ] 失敗 {Path(p).name}: {e}")
            continue
        if not d:
            continue
        out = Path(p).parent / f"odds_{d['race_id']}.json"
        out.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    a = ap.parse_args()
    print(f"想定オッズを書き出し: {write_day(a.date)}レース")
