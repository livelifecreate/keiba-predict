"""
全出走馬の走破タイム・勝ち馬との秒差・上がり3Fを取得する（2026-10-04）

目的: 能力指数に「着差」を全走で入れる検証（改善案⑤）。cache/race_result には着順しか無く、
着差は2勝以上の馬の通算成績（全出走馬の約4割）からしか取れなかった。
結果ページ（race.netkeiba.com/race/result.html）の「タイム」「後3F」列から全馬分を取り直す。

保存先: cache/race_margin/{race_id}.json  {"race_id", "entries": [{horse_id, horse_num, rank, time, margin, last3f}]}
  time: 走破タイム（秒） / margin: 勝ち馬との差（秒・1着は0） / last3f: 上がり3F（秒）

  python3 tools/fetch_race_margin.py --test          # 2レースだけ取得して表示
  python3 tools/fetch_race_margin.py --run --limit 1500

netkeibaの一括取得は平日のみ（CLAUDE.md 運用ルール）。取得済みは飛ばす。空応答は保存しない。
5レース連続で取得できなければ通信制限とみなして中断する。
"""
import argparse, json, re, sys, time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
OUT = BASE / "cache" / "race_margin"


def _sec(t: str):
    m = re.match(r"^(?:(\d+):)?(\d+(?:\.\d+)?)$", t or "")
    return (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else None


def fetch(rid: str):
    import requests
    from bs4 import BeautifulSoup
    from netkeiba_race_scraper import HEADERS
    r = requests.get(f"https://race.netkeiba.com/race/result.html?race_id={rid}", headers=HEADERS, timeout=20)
    if r.status_code != 200 or not r.content:
        return None
    soup = BeautifulSoup(r.content, "lxml")
    tbl = soup.find("table", class_="RaceTable01")
    if not tbl:
        return None
    rows = [tr for tr in tbl.find_all("tr")]
    head = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    need = ("着順", "馬番", "タイム")
    if not all(h in head for h in need):
        return None
    ents = []
    for tr in rows[1:]:
        c = [x.get_text(strip=True) for x in tr.find_all(["th", "td"])]
        if len(c) < len(head) or not c[head.index("着順")].isdigit():
            continue
        hid = next((m.group(1) for a in tr.find_all("a", href=True) for m in [re.search(r"/horse/(\d+)", a["href"])] if m), "")
        ents.append({"horse_id": hid, "horse_num": c[head.index("馬番")], "rank": int(c[head.index("着順")]),
                     "time": _sec(c[head.index("タイム")]),
                     "last3f": _sec(c[head.index("後3F")]) if "後3F" in head else None})
    if not ents or ents[0]["time"] is None:
        return None
    win = min(e["time"] for e in ents if e["time"] is not None)
    for e in ents:
        e["margin"] = round(e["time"] - win, 1) if e["time"] is not None else None
    return {"race_id": rid, "entries": ents}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=1500)
    a = ap.parse_args()
    rids = sorted(p.stem for p in (BASE / "cache" / "race_result").glob("*.json"))
    todo = [r for r in rids if not (OUT / f"{r}.json").exists()]
    print(f"対象 {len(rids)}R / 取得済み {len(rids) - len(todo)}R / 残り {len(todo)}R")
    if a.test:
        todo = todo[:2]
    elif not a.run:
        return
    else:
        todo = todo[:a.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    fails = ok = 0
    for i, rid in enumerate(todo, 1):
        time.sleep(1.5)
        try:
            d = fetch(rid)
        except Exception:
            d = None
        if d is None:
            fails += 1
            print(f"  {rid}: 取得できず（連続{fails}回）")
            if fails >= 5:
                print("5レース連続で取得できないため中断（通信制限の可能性）")
                break
            continue
        fails = 0; ok += 1
        (OUT / f"{rid}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        if a.test:
            print(rid, d["entries"][:3])
        elif i % 100 == 0:
            print(f"  {i}/{len(todo)} 取得 {ok}")
    print(f"完了: 取得 {ok}R")


if __name__ == "__main__":
    main()
