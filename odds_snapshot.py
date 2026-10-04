"""
オッズの記録（2026-10-04・記録のみ。ODDS_SNAPSHOT=0 で無効）

予想の実行ごとに、単勝・複勝 / 馬連 / ワイド / 三連複 の全組み合わせのオッズを保存する。
目的: 過去の組み合わせオッズは手元に無いため、今から集めておき、数か月後に
  - 案G＋市場で出した組み合わせ確率と実際のオッズを比べ、割安な組み合わせがあるか（三連系の値付けの偏り）
  - 朝のオッズと最終オッズの差（締め切り前の動き）に情報があるか
を検証できるようにする。

保存先: cache/odds_snapshots/{race_id}/{YYYYmmdd_HHMM}.json
  {"race_id", "fetched_at", "status"(middle=発売中/result=確定), "official_datetime", "odds": {type: {組番: [オッズ, 上限, 人気]}}}
  type: 1=単勝 2=複勝（1と同時に返る） 4=馬連 5=ワイド 7=三連複

  python3 odds_snapshot.py --date 2026-10-04   # その日の予想CSVにある全レースを今のオッズで記録（発走前の取り直し用）
"""
import argparse, glob, json, os, re, time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "cache" / "odds_snapshots"
TYPES = (1, 4, 5, 7)
URL = "https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={rid}&type={t}&action=update"


def enabled() -> bool:
    return os.environ.get("ODDS_SNAPSHOT", "1") != "0"


def save(race_id: str) -> int:
    """1レース分を保存。保存できた券種の数を返す（失敗しても予想は止めない）"""
    import requests
    from netkeiba_race_scraper import HEADERS
    snap = {"race_id": race_id, "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "odds": {}}
    for t in TYPES:
        try:
            time.sleep(1.0)
            r = requests.get(URL.format(rid=race_id, t=t), headers=HEADERS, timeout=15)
            d = r.json()
        except Exception:
            continue
        data = d.get("data")
        if not isinstance(data, dict) or not data.get("odds"):
            continue
        snap["status"] = d.get("status", "")
        snap["official_datetime"] = data.get("official_datetime", "")
        snap["odds"].update(data["odds"])
    if not snap["odds"]:
        return 0
    d = OUT / race_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{datetime.now():%Y%m%d_%H%M}.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return len(snap["odds"])


def race_ids(day: str) -> list:
    out = []
    for p in sorted(glob.glob(str(BASE / "results" / day / "*" / "score_*.csv"))):
        for line in open(p, encoding="utf-8-sig"):
            if line.startswith("■レース情報"):
                rid = line.split(",")[2]
                if re.fullmatch(r"\d{12}", rid):
                    out.append(rid)
                break
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    a = ap.parse_args()
    for rid in race_ids(a.date):
        print(rid, "保存した券種:", save(rid))
