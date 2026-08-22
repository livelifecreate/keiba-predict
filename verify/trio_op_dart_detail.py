"""
OP × ダート 三連複BOX N頭 詳細分析
- N=3,4,5頭それぞれについて：
  1. 総レース数(n)
  2. 的中件数と的中率
  3. 全的中レースの払戻額リスト（昇順）
  4. 最低配当・中央値配当・最高配当
  5. 最高配当を除いたROI
  6. 配当分布（〜1000 / 1001〜3000 / 3001〜10000 / 10001〜30000 / 30001〜）

OP判定: race_class == "OP" のみ（重賞は含まない）
ダート: surface == "ダ"
"""
import sys, re, json, statistics
from pathlib import Path
from itertools import combinations

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from jra_scraper import HorseEntry, RaceInfo
from scorer_dart import score_all as score_dart
from cache_store import cache_get, cache_get_before

BASE           = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE     = BASE / 'cache' / 'race_result'
NETKEIBA_TRAIN = BASE / 'cache' / 'netkeiba_training'


# ---------------------------------------------------------------------------
# 調教キャッシュ
# ---------------------------------------------------------------------------
def _fetch_training(race_id: str):
    p = NETKEIBA_TRAIN / f"{race_id}.json"
    if not p.exists():
        return None
    try:
        from netkeiba_scraper import TrainingData as TD
        raw = json.loads(p.read_text())
        if not raw:
            return None
        return {name: TD(horse_name=name, rank=v["rank"],
                         comment=v.get("comment", ""), score=v["score"])
                for name, v in raw.items()}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 払戻パーサー
# ---------------------------------------------------------------------------
def _parse_nums(s: str) -> list:
    nums, i = [], 0
    while i < len(s):
        if i + 2 <= len(s):
            two = int(s[i:i+2])
            if 1 <= two <= 18:
                nums.append(two)
                i += 2
                continue
        one = int(s[i])
        nums.append(one)
        i += 1
    return nums

def _parse_amounts(s: str) -> list:
    return [int(m.replace(',', '')) for m in re.findall(r'[\d,]+(?=円)', s)]

def get_trio_payout(race_id: str):
    """(frozenset[3馬番], 払戻額) or (None, 0)"""
    p = cache_get('payouts', race_id)
    if not p:
        return None, 0
    v = p.get('3連複', {})
    raw = v.get('raw', [])
    if len(raw) < 3:
        return None, 0
    try:
        hnums   = _parse_nums(raw[1]) if raw[1] else []
        amounts = _parse_amounts(raw[2]) if raw[2] else []
    except Exception:
        return None, 0
    if len(hnums) < 3 or not amounts:
        return None, 0
    return frozenset(hnums[:3]), amounts[0]


# ---------------------------------------------------------------------------
# レース採点
# ---------------------------------------------------------------------------
def process_race(data: dict):
    """OP×ダートのみ対象。採点し結果dictを返す"""
    rc      = data.get("race_class", "")
    surface = data.get("surface", "")

    # OP のみ（重賞は除外）
    if rc != "OP":
        return None
    if surface != "ダ":
        return None

    date_str = data.get("date", "")
    dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not dm:
        return None
    cutoff = f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}"

    race_info = RaceInfo(
        name=data["race_name"], date=date_str, venue=data["venue"],
        race_number=f"{data['race_num_int']}R",
        distance=data["distance"], surface=surface,
        conditions=data.get("conditions", ""),
        start_time=data.get("start_time", ""), url="",
        race_num=data["race_num_int"],
    )

    entries = []
    for e in data["entries"]:
        hid    = e.get("horse_id", "")
        recent = cache_get_before("horse_history", hid, cutoff) or []
        sire   = cache_get("sire", hid) or ""
        he = HorseEntry(
            frame_number=e["frame"], horse_number=e["horse_num"],
            horse_name=e["horse_name"], record="", prize_money="",
            owner="", trainer="", age_sex=e.get("age_sex", ""),
            weight_carried=e.get("weight_carried", ""), jockey=e.get("jockey", ""),
            recent_races=recent, sire=sire,
        )
        entries.append(he)

    if len(entries) < 5:
        return None

    training_data = _fetch_training(data.get("race_id", ""))
    tc = data.get("track_condition", "")
    try:
        scored = score_dart(entries, race_info, training_data=training_data,
                            track_condition=tc)
    except Exception:
        return None

    scored.sort(key=lambda x: x[1].total, reverse=True)
    scored_nums = []
    for entry, bd in scored:
        try:
            scored_nums.append(int(entry.horse_number))
        except Exception:
            pass

    race_id = data.get("race_id", "")
    trio_win, trio_pay = get_trio_payout(race_id)
    if trio_win is None:
        return None

    return {
        "race_id":     race_id,
        "race_name":   data["race_name"],
        "date":        date_str,
        "venue":       data.get("venue", ""),
        "distance":    data.get("distance", ""),
        "scored_nums": scored_nums,
        "trio_win":    trio_win,
        "trio_pay":    trio_pay,
    }


# ---------------------------------------------------------------------------
# BOX 詳細シミュレーション
# ---------------------------------------------------------------------------
def sim_box_detail(races: list, n_top: int) -> dict:
    pts = n_top * (n_top - 1) * (n_top - 2) // 6
    invest = collect = hits = 0
    hit_pays = []          # 的中レースの払戻額リスト
    hit_races = []         # 的中レース情報

    for r in races:
        invest += pts * 100
        top_set = frozenset(r["scored_nums"][:n_top])
        if r["trio_win"].issubset(top_set):
            collect += r["trio_pay"]
            hits += 1
            hit_pays.append(r["trio_pay"])
            hit_races.append(r)

    n = len(races)
    roi = collect / invest * 100 if invest > 0 else 0.0

    # 最高配当除外ROI
    roi_ex_top = 0.0
    if hit_pays:
        max_pay = max(hit_pays)
        collect_ex = collect - max_pay
        invest_ex  = invest   # 投資は変わらない（レース数が減るわけではないため全体据え置き）
        roi_ex_top = collect_ex / invest_ex * 100 if invest_ex > 0 else 0.0
    else:
        max_pay = 0

    # 配当分布
    buckets = {
        "〜1000円": 0,
        "1001〜3000円": 0,
        "3001〜10000円": 0,
        "10001〜30000円": 0,
        "30001円〜": 0,
    }
    for pay in hit_pays:
        if pay <= 1000:
            buckets["〜1000円"] += 1
        elif pay <= 3000:
            buckets["1001〜3000円"] += 1
        elif pay <= 10000:
            buckets["3001〜10000円"] += 1
        elif pay <= 30000:
            buckets["10001〜30000円"] += 1
        else:
            buckets["30001円〜"] += 1

    return {
        "n_top":      n_top,
        "pts":        pts,
        "n":          n,
        "invest":     invest,
        "collect":    collect,
        "hits":       hits,
        "roi":        roi,
        "roi_ex_top": roi_ex_top,
        "hit_pays":   sorted(hit_pays),
        "hit_races":  hit_races,
        "max_pay":    max_pay,
        "buckets":    buckets,
    }


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def print_detail(s: dict):
    n_top = s["n_top"]
    pts   = s["pts"]
    n     = s["n"]
    hits  = s["hits"]
    hit_rate = hits / n * 100 if n > 0 else 0.0

    pays = s["hit_pays"]
    med  = statistics.median(pays) if pays else 0
    mn   = min(pays) if pays else 0
    mx   = max(pays) if pays else 0

    print(f"\n{'='*68}")
    print(f"  {n_top}頭BOX ({pts}点/R)  OP×ダート  n={n}レース")
    print(f"{'='*68}")
    print(f"  総レース数  : {n}")
    print(f"  的中件数    : {hits}件 ({hit_rate:.1f}%)")
    print(f"  総投資      : {s['invest']:,}円")
    print(f"  総回収      : {s['collect']:,}円")
    print(f"  ROI         : {s['roi']:.0f}%")
    print(f"  ROI(最高除外): {s['roi_ex_top']:.0f}%  (最高配当 {s['max_pay']:,}円 を除外)")

    if pays:
        print(f"\n  配当統計:")
        print(f"    最低配当  : {mn:>10,}円")
        print(f"    中央値配当: {med:>10,.0f}円")
        print(f"    最高配当  : {mx:>10,}円")

        print(f"\n  配当分布:")
        total_hits = len(pays)
        for label, cnt in s["buckets"].items():
            bar = "█" * cnt
            pct = cnt / total_hits * 100 if total_hits > 0 else 0
            print(f"    {label:<16}: {cnt:>3}件 ({pct:5.1f}%)  {bar}")

        print(f"\n  全的中払戻リスト（昇順）:")
        for i, (pay, r) in enumerate(zip(pays, sorted(s["hit_races"], key=lambda x: x["trio_pay"]))):
            marker = " ← 最高配当" if pay == mx and i == len(pays) - 1 else ""
            print(f"    [{i+1:>2}] {pay:>10,}円  {r['date']}  {r['venue']}  {r['race_name']}{marker}")
    else:
        print("  的中なし")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    all_files = sorted(CACHE_RACE.glob("*.json"))
    print(f"キャッシュ: {len(all_files)}件読み込み開始...")

    races = []
    errors = skipped = 0
    for i, fp in enumerate(all_files):
        if (i + 1) % 300 == 0:
            print(f"  {i+1}/{len(all_files)} 処理中... (OP×ダート: {len(races)}, スキップ: {skipped})")
        try:
            data = json.loads(fp.read_text())
            r = process_race(data)
            if r is None:
                skipped += 1
            else:
                races.append(r)
        except Exception:
            errors += 1

    print(f"\n完了: OP×ダート対象レース={len(races)}, スキップ={skipped}, エラー={errors}")

    if not races:
        print("対象レースがありません。")
        sys.exit(1)

    print(f"\n{'='*68}")
    print(f"  OP × ダート 三連複BOX 詳細分析")
    print(f"  対象レース: {len(races)}R")
    print(f"  期間: 2025/12〜2026/06")
    print(f"{'='*68}")

    # サマリーテーブル
    print(f"\n  【サマリー】")
    print(f"  {'N頭BOX':<10}  {'点数':>4}  {'的中':>8}  {'的中率':>7}  {'ROI':>7}  {'ROI(最高除外)':>14}")
    print(f"  {'-'*62}")
    for n_top in (3, 4, 5):
        s = sim_box_detail(races, n_top)
        print(f"  {n_top}頭BOX      {s['pts']:>4}点  "
              f"{s['hits']:>4}/{s['n']}  "
              f"{s['hits']/s['n']*100:>6.1f}%  "
              f"{s['roi']:>6.0f}%  "
              f"{s['roi_ex_top']:>13.0f}%")

    # 詳細
    for n_top in (3, 4, 5):
        s = sim_box_detail(races, n_top)
        print_detail(s)

    print(f"\n{'='*68}")
    print(f"  分析完了")
    print(f"{'='*68}")
