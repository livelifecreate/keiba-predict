"""
RACE_LOG.md に当日のレースを追記する（2026-09-26）

  --predict <日付>  予想CSVから「判定・上位5頭・ペース想定」を書き込む（結果欄は空で作る）
  --results <日付>  netkeiba から1〜3着を取得して結果欄と的中欄を埋める

日付は YYYY-MM-DD。省略時は今日。
見送ったレースも必ず記録する（フィルタの妥当性を後から実データで検証するため）。
"""
import argparse, csv, glob, re, sys, time
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOG = BASE / "RACE_LOG.md"


def load_races(day: str):
    out = []
    for p in sorted(glob.glob(str(BASE / "results" / day / "*" / "*.csv"))):
        rows = [r for r in csv.reader(open(p, encoding="utf-8-sig"))]
        if not rows:
            continue
        ix = {c: i for i, c in enumerate(rows[0])}
        horses = [r for r in rows[1:] if r and r[0].isdigit()]
        if not horses:
            continue
        m = re.search(r"_(\d+)R_(芝|ダート)(\d+)m_([^_.]+)", Path(p).name)
        sign = next((r[1] for r in rows if r and r[0] == "■買いサイン"), "")
        detail = next((r[2] for r in rows if r and r[0] == "■買いサイン" and len(r) > 2), "")
        pace = next((r[1] for r in rows if r and r[0] == "" and len(r) > 1 and "ペース想定" in r[1]), "")
        rid = next((r[2] for r in rows if r and r[0] == "■レース情報" and len(r) > 2), "")
        out.append({
            "venue": Path(p).parent.name, "r": int(m.group(1)) if m else 0,
            "name": m.group(4) if m else Path(p).stem, "n": len(horses), "rid": rid,
            "buy": "見送り" not in sign, "detail": detail,
            "pace": re.sub(r"【ペース想定】|\s*※.*", "", pace).strip(),
            "top5": [(r[ix["馬番"]], r[ix["馬名"]]) for r in horses[:5]],
        })
    return sorted(out, key=lambda x: (x["venue"], x["r"]))


def fetch_top3(rid: str):
    import requests
    from bs4 import BeautifulSoup
    try:
        time.sleep(1.5)
        r = requests.get(f"https://race.netkeiba.com/race/result.html?race_id={rid}",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "lxml")
        for tb in soup.find_all("table"):
            h = tb.get_text(" ", strip=True)[:40]
            if "着" in h and ("馬名" in h or "馬番" in h):
                res = []
                for tr in tb.find_all("tr")[1:4]:
                    c = [x.get_text(strip=True) for x in tr.find_all(["td", "th"])]
                    if len(c) > 3:
                        res.append((c[0], c[2], c[3]))
                return res if len(res) == 3 else []
    except Exception:
        pass
    return []


def section(day: str, races: list, results: dict) -> str:
    wd = "月火水木金土日"[date.fromisoformat(day).weekday()]
    venues = " ・ ".join(sorted({r["venue"] for r in races}))
    n_buy = sum(1 for r in races if r["buy"])
    lines = [f"## {day}（{wd}）{venues}", "",
             "| 場 | R | レース名 | 頭数 | 判定 | 予想上位5頭 | ペース想定 | 結果（1-2-3着） | 三連複 | 馬連5頭BOX |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for x in races:
        top5 = ",".join(n for n, _ in x["top5"])
        res = results.get(x["rid"])
        if res:
            rtxt = " - ".join(f"{b}番" for _, b, _ in res)
            nums = {b for _, b, _ in res}
            t5 = {n for n, _ in x["top5"]}
            trio = "◎的中" if len(nums & t5) == 3 and x["top5"][0][0] in nums else "✗"
            quin = "◎的中" if len([1 for _, b, _ in res[:2] if b in t5]) == 2 else "✗"
        else:
            rtxt, trio, quin = "（レース後に追記）", "—", "—"
        mark = "**★買い**" if x["buy"] else f"見送り"
        nm = f"**{x['name']}**" if x["buy"] else x["name"]
        lines.append(f"| {x['venue']} | {x['r']} | {nm} | {x['n']} | {mark} | {top5} | {x['pace']} | {rtxt} | {trio} | {quin} |")
    lines += ["", f"- 買いサイン **{n_buy}件** / 対象{len(races)}レース。三連複＝1軸(予想1位)-相手2〜5位の6点、馬連＝上位5頭BOX 10点。",
              "- 的中欄は「買っていたら」を含め全レース記録（見送りレースのフィルタ検証のため）。", ""]
    return "\n".join(lines)


def write(day: str, races: list, results: dict):
    text = LOG.read_text() if LOG.exists() else "# 実戦記録\n\n"
    new = section(day, races, results)
    head = f"## {day}（"
    if head in text:                       # 既存の同じ日付の節を置き換える
        start = text.index(head)
        nxt = text.find("\n## ", start + 1)
        text = text[:start] + new + ("\n" + text[nxt + 1:] if nxt > 0 else "")
    else:                                   # 新しい日付は「---」直後（新しい順）に差し込む
        anchor = text.find("\n---\n")
        pos = anchor + 5 if anchor > 0 else len(text)
        text = text[:pos] + "\n" + new + "\n---\n" + text[pos:]
    LOG.write_text(text)
    print(f"RACE_LOG.md を更新: {day} / {len(races)}レース / 結果あり{len(results)}件")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predict", action="store_true", help="予想を記録（結果欄は空）")
    ap.add_argument("--results", action="store_true", help="結果を取得して埋める")
    ap.add_argument("--date", default=str(date.today()))
    a = ap.parse_args()
    races = load_races(a.date)
    if not races:
        print(f"{a.date} の予想CSVが見つかりません")
        return 1
    results = {}
    if a.results:
        for x in races:
            if x["rid"]:
                res = fetch_top3(x["rid"])
                if res:
                    results[x["rid"]] = res
        print(f"結果を取得: {len(results)}/{len(races)}レース")
    write(a.date, races, results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
