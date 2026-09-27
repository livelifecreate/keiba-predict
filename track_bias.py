"""
当日の馬場傾向（2026-09-27・表示のみ）

その日に終わったレースの「3着以内に来た馬が4角でどこにいたか」「内枠か外枠か」を
場×芝ダ別に集計し、平常時（通算成績から算出した基準）と比べて
「前残り / 差しが届く / 内有利 / 外有利」を表示する。順位づけには使わない。

  python3 track_bias.py --date 2026-09-27     # 終わったレースを取得して results/<日付>/track_bias.json を更新
  python3 track_bias.py --baseline            # 基準値（data/track_bias_baseline.json）を作り直す

- 4角の位置は結果ページの「コーナー通過順位」表の最終コーナー（netkeibaの無料部分）から取る。
- 取得済みの確定レースは cache/track_bias/ に保存し、再取得しない。
- 各場とも1Rから順に取得し、未確定のレースに当たったらその場は打ち切る（無駄なアクセスをしない）。
"""
import argparse, glob, json, re, sys, time
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
CACHE = BASE / "cache" / "track_bias"
BASELINE = BASE / "data" / "track_bias_baseline.json"

MIN_RACES = 3        # これ未満のレース数では傾向を判定しない
DIFF_PT = 15         # 基準からこのpt以上ずれたら傾向ありと表示


# ── 4角位置 ─────────────────────────────────────────────────────────────────

def parse_corner(s: str) -> dict:
    """'7-11(8,9)6=3-4-12(10,1)=5=2' → {馬番: 順位}。括弧内は併走で同順位。"""
    pos, rank = {}, 0
    for m in re.finditer(r"\(([\d,]+)\)|(\d+)", s):
        nums = m.group(1).split(",") if m.group(1) else [m.group(2)]
        start = rank + 1
        for n in nums:
            pos[int(n)] = start
        rank += len(nums)
    return pos


def zone(rank: int, n: int) -> str:
    """4角の順位を 前/中/後 に3分割。"""
    r = rank / n
    return "前" if r <= 1 / 3 else ("中" if r <= 2 / 3 else "後")


# ── 取得 ───────────────────────────────────────────────────────────────────

def fetch_race(rid: str):
    """確定済みなら {race_id, venue, R, surface, distance, n, track, top3:[...]}。未確定・障害は None。"""
    f = CACHE / f"{rid}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    import requests
    from bs4 import BeautifulSoup
    from netkeiba_race_scraper import HEADERS, VENUE_CODE
    time.sleep(1.5)
    try:
        r = requests.get(f"https://race.netkeiba.com/race/result.html?race_id={rid}",
                         headers=HEADERS, timeout=20)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.content, "lxml")
    rd1 = soup.find(class_="RaceData01")
    rd1 = rd1.get_text(" ", strip=True) if rd1 else ""
    m = re.search(r"(芝|ダ)(\d+)m", rd1)
    tbl = soup.find("table", class_="RaceTable01")
    corner = soup.find("table", class_="Corner_Num")
    if not tbl or not corner:
        return None                                   # 未確定
    rows = [[c.get_text(strip=True) for c in tr.find_all(["th", "td"])] for tr in tbl.find_all("tr")]
    head = rows[0]
    res = [r for r in rows[1:] if r and r[0].isdigit()]
    if not res:
        return None
    corners = [[c.get_text(strip=True) for c in tr.find_all(["th", "td"])] for tr in corner.find_all("tr")]
    corners = [c for c in corners if len(c) >= 2 and c[1]]
    out = {"race_id": rid, "venue": VENUE_CODE.get(rid[4:6], ""), "R": int(rid[10:12]),
           "surface": m.group(1) if m else "障", "distance": int(m.group(2)) if m else 0,
           "track": (re.search(r"馬場:(\S+)", rd1) or [None, ""])[1],
           "n": len(res), "top3": []}
    if m and corners:
        last = parse_corner(corners[-1][1])
        iu, ib = head.index("馬番"), head.index("枠")
        for r in res[:3]:
            num = int(r[iu])
            if num in last:
                out["top3"].append({"rank": int(r[0]), "num": num, "frame": int(r[ib]),
                                    "c4": last[num], "zone": zone(last[num], len(res))})
    if m and len(out["top3"]) < 3:
        return None                                   # コーナー表が未掲載。保存せず次回取り直す
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def day_prefixes(day: str) -> list:
    """予想CSVの race_id から、その日の開催（race_id 先頭10桁）を集める。"""
    pre = set()
    for p in glob.glob(str(BASE / "results" / day / "*" / "*.csv")):
        for line in open(p, encoding="utf-8-sig"):
            if line.startswith("■レース情報"):
                rid = line.split(",")[2]
                if re.fullmatch(r"\d{12}", rid):
                    pre.add(rid[:10])
                break
    return sorted(pre)


def fetch_day(day: str) -> list:
    races = []
    for pre in day_prefixes(day):
        for r in range(1, 13):
            x = fetch_race(f"{pre}{r:02d}")
            if x is None:
                break                                 # 以降は未確定
            races.append(x)
    return races


# ── 基準値（平常時の3着内馬の位置） ──────────────────────────────────────────

def build_baseline() -> dict:
    """通算成績（cache/horse_full_history）の3着以内の馬について、4角位置と内外の割合を場×芝ダ別に出す。"""
    agg = {}
    for p in glob.glob(str(BASE / "cache" / "horse_full_history" / "*.json")):
        try:
            recs = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            continue
        for x in recs:
            try:
                pos, n = int(x["pos_raw"]), int(x["field"])
                c4 = int(str(x["corner"]).split("-")[-1])
                num = int(x["num"])
            except (KeyError, ValueError, TypeError):
                continue
            if pos > 3 or n < 5 or not x.get("dist_raw", "")[:1] in ("芝", "ダ"):
                continue
            venue = re.sub(r"\d", "", x.get("kaisan", ""))
            for key in (f"{venue}{x['dist_raw'][0]}", f"全{x['dist_raw'][0]}"):
                a = agg.setdefault(key, {"n": 0, "前": 0, "中": 0, "後": 0, "内": 0})
                a["n"] += 1
                a[zone(min(c4, n), n)] += 1
                a["内"] += num <= n / 2
    out = {k: {"n": v["n"], **{z: round(100 * v[z] / v["n"], 1) for z in ("前", "中", "後", "内")}}
           for k, v in agg.items() if v["n"] >= 300}
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load_baseline() -> dict:
    if BASELINE.exists():
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    return build_baseline()


# ── 集計 ───────────────────────────────────────────────────────────────────

def summarize(races: list, base: dict) -> dict:
    """場×芝ダ別の集計と判定文。キーは '阪神ダ' など。"""
    out = {}
    for x in races:
        if x["surface"] not in ("芝", "ダ") or not x["top3"]:
            continue
        key = f"{x['venue']}{x['surface']}"
        s = out.setdefault(key, {"venue": x["venue"], "surface": x["surface"], "races": [],
                                 "n": 0, "前": 0, "中": 0, "後": 0, "内": 0, "track": x.get("track", "")})
        s["races"].append(x["R"])
        s["track"] = x.get("track", "") or s["track"]
        for h in x["top3"]:
            s["n"] += 1
            s[h["zone"]] += 1
            s["内"] += h["num"] <= x["n"] / 2
    for key, s in out.items():
        b = base.get(key) or base.get(f"全{s['surface']}") or {}
        pct = {z: round(100 * s[z] / s["n"], 1) if s["n"] else 0 for z in ("前", "中", "後", "内")}
        s["pct"], s["base"] = pct, {z: b.get(z) for z in ("前", "中", "後", "内")}
        notes = []
        if len(s["races"]) < MIN_RACES:
            notes.append(f"まだ{len(s['races'])}レースのみで判断材料不足")
        elif b:
            d_front = pct["前"] - b["前"]
            d_back = pct["後"] - b["後"]
            if d_front >= DIFF_PT:
                notes.append("前残り傾向")
            elif d_back >= DIFF_PT or d_front <= -DIFF_PT:
                notes.append("差し・追込が届く傾向")
            d_in = pct["内"] - b["内"]
            if d_in >= DIFF_PT:
                notes.append("内枠有利")
            elif d_in <= -DIFF_PT:
                notes.append("外枠有利")
            if not notes:
                notes.append("平常どおり（目立った偏りなし）")
        s["verdict"] = " / ".join(notes)
    return out


def text_line(s: dict) -> str:
    """画面・ログ用の1行。"""
    surf = "芝" if s["surface"] == "芝" else "ダート"
    p, b = s["pct"], s["base"]
    rs = ",".join(str(r) for r in sorted(s["races"]))
    base_txt = (f"（平常時 前{b['前']:.0f}/中{b['中']:.0f}/後{b['後']:.0f}%・内{b['内']:.0f}%）"
                if b.get("前") is not None else "")
    track = f"・{s['track']}" if s.get("track") else ""
    return (f"{s['venue']}{surf}{track}【{s['verdict']}】 {len(s['races'])}R終了（{rs}R）"
            f" 3着内{s['n']}頭の4角位置 前{p['前']:.0f}/中{p['中']:.0f}/後{p['後']:.0f}%・内枠{p['内']:.0f}%{base_txt}")


def update(day: str) -> dict:
    races = fetch_day(day)
    summ = summarize(races, load_baseline())
    out = {"date": day, "updated": time.strftime("%H:%M"), "summary": summ,
           "lines": [text_line(s) for s in summ.values()]}
    d = BASE / "results" / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "track_bias.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--baseline", action="store_true")
    a = ap.parse_args()
    if a.baseline:
        for k, v in sorted(build_baseline().items()):
            print(k, v)
        sys.exit()
    o = update(a.date)
    print(f"[馬場傾向] {a.date} {o['updated']}時点")
    for line in o["lines"] or ["確定したレースなし"]:
        print("  " + line)
