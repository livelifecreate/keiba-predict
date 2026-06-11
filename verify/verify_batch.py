"""
芝レース一括検証スクリプト
指定期間のレースをクラス別に採点して的中率を集計する。

使い方:
  python3 verify_batch.py                      # 5月全土日・OP+2勝クラス
  python3 verify_batch.py --classes OP 2勝クラス 3勝クラス
  python3 verify_batch.py --dates 20260502 20260503
  python3 verify_batch.py --surface 芝        # 芝のみ（デフォルト）
  python3 verify_batch.py --surface ダ        # ダートのみ
"""

import re
import sys
import time
import random
import datetime
import csv
from collections import defaultdict

def _sleep():
    time.sleep(random.uniform(1.5, 2.5))

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

import requests
from bs4 import BeautifulSoup
from scorer_turf import score_all as score_all_turf, SCORE_LABELS as SCORE_LABELS_TURF
from scorer_dart import score_all as score_all_dart, SCORE_LABELS as SCORE_LABELS_DART
from jra_scraper import HorseEntry, RaceInfo
from netkeiba_race_scraper import (
    HEADERS, VENUE_CODE, get_race_list, fetch_race_result
)
from cache_store import cache_get, cache_set

# ── デフォルト設定 ──
DEFAULT_CLASSES = ["OP", "2勝クラス"]
DEFAULT_SURFACE = "芝"

# 5月の土日（2026年）
MAY_DATES = [
    datetime.date(2026, 5,  2), datetime.date(2026, 5,  3),
    datetime.date(2026, 5,  9), datetime.date(2026, 5, 10),
    datetime.date(2026, 5, 16), datetime.date(2026, 5, 17),
    datetime.date(2026, 5, 23), datetime.date(2026, 5, 24),
    datetime.date(2026, 5, 30), datetime.date(2026, 5, 31),
]


# ────────────────────────────────────────────────────────────
# 近走・父取得（verify_*.py と共通ロジック）
# ────────────────────────────────────────────────────────────
def fetch_past_races(horse_id: str, cutoff: str, max_races: int = 5) -> list[str]:
    cache_key = f"{horse_id}_{cutoff}"
    cached = cache_get("horse_history", cache_key)
    if cached is not None:
        return cached
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    _sleep()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception as e:
        return []
    table = soup.find("table")
    if not table:
        return []
    rows = table.find_all("tr")
    if not rows:
        return []
    hdrs = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    def gi(n):
        try: return hdrs.index(n)
        except: return -1
    di  = gi("日付");  vi = gi("開催");  ri = gi("レース名")
    ni  = gi("頭数");  pi = gi("着順");  dsti = gi("距離")
    mi  = gi("着差");  ci = gi("通過");  l3i  = gi("上り")
    hwi = gi("馬体重")
    recent = []
    for row in rows[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 10:
            continue
        def cell(i): return cells[i] if 0 <= i < len(cells) else ""
        date_raw = cell(di)
        dm = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_raw)
        if not dm:
            continue
        if cutoff and date_raw >= cutoff:
            continue
        if len(recent) >= max_races:
            break
        date_jp = f"{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日"
        vm = re.search(r"(東京|中山|阪神|京都|中京|新潟|福島|小倉|札幌|函館)", cell(vi))
        venue = vm.group(1) if vm else ""
        rname_raw = cell(ri)
        race_name = re.sub(r'\([^)]*\)', '', rname_raw).strip()
        gm = re.search(r'\((GI+|GII+|GIII+)\)', rname_raw)
        grade_str = gm.group(1) if gm else ""
        try: pos = int(cell(pi))
        except ValueError: continue
        try: nheads = int(cell(ni))
        except ValueError: nheads = 0
        dsm = re.match(r"(芝|ダ)(\d+)", cell(dsti))
        surface = dsm.group(1) if dsm else ""
        dist_m  = dsm.group(2) if dsm else ""
        hwm = re.match(r"(\d{3,4})", cell(hwi))
        hw_str = f"{hwm.group(1)}kg" if hwm else ""
        try: l3f_str = f"3F {float(cell(l3i))}"
        except ValueError: l3f_str = ""
        try: mg_str = f"({abs(float(cell(mi)))})"
        except ValueError: mg_str = "(0)"
        corner_parts = re.findall(r"\d+", cell(ci))
        corner_str = (
            f"1角:{corner_parts[0]} 4角:{corner_parts[-1]}"
            if len(corner_parts) >= 2
            else (f"1角:{corner_parts[0]}" if corner_parts else "")
        )
        recent.append(
            f"{date_jp}{venue}{race_name}{grade_str}"
            f"{pos}着{nheads}頭5番人気"
            f"{dist_m}{surface}{hw_str}{l3f_str}"
            f"{mg_str}{corner_str}"
        )
    # 馬場歴も同時にキャッシュ（baba_history）
    bi = gi("馬場")
    baba_recent = []
    if bi >= 0:
        baba_all_rows = rows[1:]
        cnt = 0
        for row in baba_all_rows:
            cells2 = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells2) <= max(bi, pi): continue
            date_raw2 = cells2[di] if di >= 0 and di < len(cells2) else ""
            if not re.match(r"\d{4}/\d{2}/\d{2}", date_raw2): continue
            if cutoff and date_raw2 >= cutoff: continue
            if cnt >= 10: break
            cond = cells2[bi]
            try:
                pos2 = int(cells2[pi])
            except ValueError:
                continue
            if cond in ("良", "稍重", "重", "不良"):
                baba_recent.append([cond, pos2])
            cnt += 1
    cache_set("baba_history", cache_key, baba_recent)

    cache_set("horse_history", cache_key, recent)
    return recent


def fetch_baba_history(horse_id: str, cutoff: str) -> list:
    """馬場状態ごとの着順リスト [(cond, pos), ...] を返す。キャッシュ優先。"""
    cache_key = f"{horse_id}_{cutoff}"
    cached = cache_get("baba_history", cache_key)
    if cached is not None:
        return [tuple(x) for x in cached]
    # horse_historyキャッシュがあれば再取得は不要だが馬場歴がない → 専用フェッチ
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    _sleep()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception:
        return []
    table = soup.find("table")
    if not table:
        return []
    rows = table.find_all("tr")
    if not rows:
        return []
    hdrs = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    def gi2(n):
        try: return hdrs.index(n)
        except: return -1
    bi = gi2("馬場"); pi2 = gi2("着順"); di2 = gi2("日付")
    if bi < 0 or pi2 < 0:
        return []
    result = []
    for row in rows[1:11]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) <= max(bi, pi2): continue
        date_raw = cells[di2] if di2 >= 0 and di2 < len(cells) else ""
        if not re.match(r"\d{4}/\d{2}/\d{2}", date_raw): continue
        if cutoff and date_raw >= cutoff: continue
        cond = cells[bi]
        try:
            pos = int(cells[pi2])
        except ValueError:
            continue
        if cond in ("良", "稍重", "重", "不良"):
            result.append((cond, pos))
    cache_set("baba_history", cache_key, result)
    return result


def fetch_sire(horse_id: str) -> str:
    cached = cache_get("sire", horse_id)
    if cached is not None:
        return cached
    url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
    _sleep()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except:
        return ""
    tbl = soup.find("table")
    if not tbl:
        return ""
    tds = tbl.find_all("td")
    if not tds:
        return ""
    m = re.match(r"([^\d\[\(]+)", tds[0].get_text(strip=True))
    result = m.group(1).strip() if m else ""
    cache_set("sire", horse_id, result)
    return result


# ────────────────────────────────────────────────────────────
# 1レース処理
# ────────────────────────────────────────────────────────────
def process_race(result: dict) -> dict | None:
    """
    fetch_race_result の返り値を受け取り、採点して
    {"race_id", "race_name", "race_class", "surface", "distance",
     "scored": [(entry, score_total, actual_rank), ...]}
    を返す。
    """
    race_id    = result["race_id"]
    race_class = result["race_class"]
    date_str   = result["date"]

    # 日付をcutoff文字列に変換（2026年5月3日 → 2026/05/03）
    dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not dm:
        return None
    cutoff = f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}"

    race_info = RaceInfo(
        name       = result["race_name"],
        date       = date_str,
        venue      = result["venue"],
        race_number= f"{result['race_num_int']}R",
        distance   = result["distance"],
        surface    = result["surface"],
        conditions = result["conditions"],
        start_time = result["start_time"],
        url        = "",
        race_num   = result["race_num_int"],
    )

    entries_raw = result["entries"]
    horse_entries = []
    rank_map = {}
    odds_map = {}
    pop_map  = {}

    print(f"  {result['race_name']} ({race_class}) {result['surface']}{result['distance']} {len(entries_raw)}頭")
    for e in entries_raw:
        hid = e["horse_id"]
        if not hid:
            continue
        recent = fetch_past_races(hid, cutoff)
        sire   = fetch_sire(hid)
        he = HorseEntry(
            frame_number   = e["frame"],
            horse_number   = e["horse_num"],
            horse_name     = e["horse_name"],
            record         = "",
            prize_money    = "",
            owner          = "",
            trainer        = "",
            age_sex        = e["age_sex"],
            weight_carried = e["weight_carried"],
            jockey         = e["jockey"],
            recent_races   = recent,
            sire           = sire,
        )
        horse_entries.append(he)
        rank_map[e["horse_name"]] = e["rank"]
        odds_map[e["horse_name"]] = e.get("odds")
        pop_map[e["horse_name"]]  = e.get("popularity")

    if len(horse_entries) < 5:
        return None

    # 競馬ブックから調教データ自動取得（失敗しても続行）
    training_data = None
    try:
        from keibabook_scraper import find_kb_race_id, scrape as scrape_kb
        from netkeiba_scraper import TrainingData as TD
        dm2 = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
        if dm2:
            date8 = f"{dm2.group(1)}{int(dm2.group(2)):02d}{int(dm2.group(3)):02d}"
            kb_id = find_kb_race_id(date8, result["race_num_int"], result["venue"])
            if kb_id:
                kb_url = f"https://p.keibabook.co.jp/cyuou/cyokyo/0/0/{kb_id}"
                kb_rows = scrape_kb(kb_url)
                training_data = {}
                for row in kb_rows:
                    t = row["時計スコア(1-5)"] + row["状態スコア(1-5)"]
                    sc = 3 if t >= 9 else 2 if t >= 7 else 1 if t >= 5 else 0 if t >= 3 else -1
                    training_data[row["馬名"]] = TD(
                        horse_name=row["馬名"], rank="KB",
                        comment=row.get("メモ", ""), score=sc,
                    )
                matched = sum(1 for e in horse_entries if e.horse_name in training_data)
                print(f"    [調教] {matched}/{len(horse_entries)}頭マッチ (競馬ブック)")
    except Exception:
        pass

    # 馬場状態 & 馬場歴（非良馬場のみフェッチ）
    track_condition = result.get("track_condition", "")
    horse_baba_history = {}
    if track_condition and track_condition != "良":
        print(f"    [馬場] {track_condition} — 道悪実績取得中...")
        for e in entries_raw:
            hid = e["horse_id"]
            if hid:
                horse_baba_history[e["horse_name"]] = fetch_baba_history(hid, cutoff)

    _score_all = score_all_dart if result["surface"] == "ダ" else score_all_turf
    scored = _score_all(
        horse_entries, race_info,
        training_data=training_data,
        track_condition=track_condition,
        horse_baba_history=horse_baba_history,
    )
    scored.sort(key=lambda x: x[1].total, reverse=True)

    return {
        "race_id":    race_id,
        "race_name":  result["race_name"],
        "race_class": race_class,
        "surface":    result["surface"],
        "distance":   result["distance"],
        "date":       date_str,
        "venue":      result["venue"],
        "scored":     [(entry, bd, rank_map.get(entry.horse_name, 99),
                        odds_map.get(entry.horse_name), pop_map.get(entry.horse_name))
                       for entry, bd in scored],
    }


# ────────────────────────────────────────────────────────────
# 的中判定
# ────────────────────────────────────────────────────────────
def check_hit(scored_entries: list) -> dict:
    """
    scored_entries: [(entry, score, actual_rank), ...]  スコア降順
    """
    top1_rank  = scored_entries[0][2]  if scored_entries      else 99
    top2_ranks = [s[2] for s in scored_entries[:2]]
    top3_ranks = [s[2] for s in scored_entries[:3]]

    return {
        "tan":    top1_rank == 1,                       # 単勝（予想1位が1着）
        "fuku":   top1_rank <= 3,                       # 複勝
        "wide13": sorted(top3_ranks[:1] + [top2_ranks[-1]]) if len(top2_ranks) >= 2 else [],  # 不要、削除
        "umaren": 1 in top2_ranks and 2 in top2_ranks,  # 馬連（1・2着を予想上位2頭に含む）
        "wide":   any(r <= 3 for r in top2_ranks),      # ワイド（上位2頭のどちらかが3着以内）
        "3fuku":  sum(1 for r in top3_ranks if r <= 3) >= 2,  # 3連複（上位3頭に2頭以上馬券圏内）
        "3tan":   top3_ranks[:3] == [1, 2, 3] if len(top3_ranks) >= 3 else False,  # 3連単（完全一致）
    }


# ────────────────────────────────────────────────────────────
# メイン
# ────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]

    # --classes でフィルタするクラスを指定
    target_classes = DEFAULT_CLASSES
    if "--classes" in args:
        idx = args.index("--classes")
        target_classes = []
        for a in args[idx + 1:]:
            if a.startswith("--"):
                break
            target_classes.append(a)

    # --surface で芝/ダを指定
    target_surface = DEFAULT_SURFACE
    if "--surface" in args:
        idx = args.index("--surface")
        if idx + 1 < len(args):
            target_surface = args[idx + 1]

    # --dates で日付を指定（YYYYMMDD形式）
    dates = MAY_DATES
    if "--dates" in args:
        idx = args.index("--dates")
        dates = []
        for a in args[idx + 1:]:
            if a.startswith("--"):
                break
            try:
                d = datetime.datetime.strptime(a, "%Y%m%d").date()
                dates.append(d)
            except ValueError:
                pass

    print(f"対象クラス: {target_classes}")
    print(f"対象コース: {target_surface}")
    print(f"対象日: {[d.strftime('%m/%d') for d in dates]}")
    print()

    # レース一覧取得
    all_races = get_race_list(dates)
    print(f"レース一覧: {len(all_races)}件取得")

    # race_idからレース結果を取得してフィルタリング
    results_by_class = defaultdict(list)
    rows_csv = []

    for race_meta in all_races:
        rid = race_meta["race_id"]
        result = cache_get("race_result", rid)
        if result is None:
            result = fetch_race_result(rid)
            if result:
                cache_set("race_result", rid, result)
        if not result:
            continue
        if result["surface"] != target_surface:
            continue
        if result["race_class"] not in target_classes:
            continue

        proc = process_race(result)
        if not proc:
            continue

        se = proc["scored"]
        hit = check_hit(se)
        top5_ranks = [s[2] for s in se[:5]]
        top5_odds  = [s[3] for s in se[:5]]

        results_by_class[proc["race_class"]].append({
            "hit": hit,
            "top5": top5_ranks,
        })

        mark = "★" if hit["tan"] else ("○" if hit["fuku"] else "  ")
        print(f"{mark} {proc['date']} {proc['venue']} {proc['race_name']} "
              f"予想1位→実{top5_ranks[0]}着  "
              f"単{'◎' if hit['tan'] else '×'} "
              f"複{'◎' if hit['fuku'] else '×'} "
              f"馬連{'◎' if hit['umaren'] else '×'} "
              f"3複{'◎' if hit['3fuku'] else '×'}")

        # 全頭1行ずつ保存
        n_horses = len(se)
        for pred_rank, (entry, bd, actual_rank, odds, popularity) in enumerate(se, start=1):
            row = {
                "日付":     proc["date"],
                "競馬場":   proc["venue"],
                "レース名": proc["race_name"],
                "クラス":   proc["race_class"],
                "距離":     proc["distance"],
                "出走頭数": n_horses,
                "馬名":     entry.horse_name,
                "馬番":     entry.horse_number,
                "予想順位": pred_rank,
                "予想スコア": round(bd.total, 2),
                "単勝オッズ": odds,
                "市場人気":  popularity,
                "実着順":   actual_rank,
            }
            _labels = SCORE_LABELS_DART if proc["surface"] == "ダ" else SCORE_LABELS_TURF
            for k, label in _labels.items():
                row[label] = round(getattr(bd, k, 0.0), 1)
            rows_csv.append(row)

    # クラス別集計
    print("\n" + "=" * 60)
    print("クラス別的中率")
    print("=" * 60)
    for cls, records in sorted(results_by_class.items()):
        n = len(records)
        if n == 0:
            continue
        tan   = sum(1 for r in records if r["hit"]["tan"])
        fuku  = sum(1 for r in records if r["hit"]["fuku"])
        umaren = sum(1 for r in records if r["hit"]["umaren"])
        _3fuku = sum(1 for r in records if r["hit"]["3fuku"])
        print(f"{cls:10s}  {n}レース  "
              f"単:{tan}/{n}({tan/n*100:.0f}%)  "
              f"複:{fuku}/{n}({fuku/n*100:.0f}%)  "
              f"馬連:{umaren}/{n}({umaren/n*100:.0f}%)  "
              f"3複:{_3fuku}/{n}({_3fuku/n*100:.0f}%)")

    # CSV保存（全頭ロング形式）
    if rows_csv:
        out = "/Users/du/Documents/競馬予想システム/data/検証_最新結果.csv"
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows_csv[0].keys()))
            writer.writeheader()
            writer.writerows(rows_csv)
        print(f"\nCSV保存: {out}  ({len(rows_csv)}行)")
        print(f"\nCSV保存: {out}")


if __name__ == "__main__":
    main()
