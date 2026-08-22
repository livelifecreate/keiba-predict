"""
三連複BOX N頭（N=3,4,5,6）の的中率・ROI比較
キャッシュ採点（rerun_all.py パターン）で全レースを in-memory 採点
払戻は cache/payouts/*.json から取得

使い方:
  python3 verify/trio_box_n.py
  python3 verify/trio_box_n.py --surface 芝
  python3 verify/trio_box_n.py --surface ダ
"""
import sys, re, json, argparse
from pathlib import Path
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from jra_scraper import HorseEntry, RaceInfo
from scorer_turf import score_all as score_turf
from scorer_dart import score_all as score_dart
from cache_store import cache_get, cache_get_before

BASE             = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE       = BASE / 'cache' / 'race_result'
NETKEIBA_TRAIN   = BASE / 'cache' / 'netkeiba_training'
TARGET_CLASSES   = {"2勝クラス", "3勝クラス", "OP", "重賞"}

# CLASS_RANK互換の分類
CLASS_LABEL = {
    "2勝クラス": "2勝", "1000万下": "2勝",
    "3勝クラス": "3勝", "1600万下": "3勝",
    "オープン":  "OP",  "リステッド": "OP",
    "OP":        "OP",
    "重賞":      "重賞",
    "G1": "重賞", "GI": "重賞",
    "G2": "重賞", "GII": "重賞",
    "G3": "重賞", "GIII": "重賞",
}


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
def _parse_nums(s: str) -> list[int]:
    """馬番連続文字列を正確にパース（最大18番前提）"""
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

def _parse_amounts(s: str) -> list[int]:
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
def process_race(data: dict, surface_filter=None):
    """1レースを採点し (race_id, class_label, surface, scored_nums, trio_win, trio_pay) を返す"""
    rc = data.get("race_class", "")
    if rc not in TARGET_CLASSES:
        return None
    surface = data.get("surface", "")
    if surface not in ("芝", "ダ"):
        return None
    if surface_filter and surface != surface_filter:
        return None

    date_str = data["date"]
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
    horse_ids = {}
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
        if hid:
            horse_ids[e["horse_name"]] = hid

    if len(entries) < 5:
        return None

    training_data = _fetch_training(data.get("race_id", ""))

    fn = score_dart if surface == "ダ" else score_turf
    tc = data.get("track_condition", "")
    try:
        # horse_ids を渡さない → 道悪時のネット取得を防止（バックテスト高速化）
        scored = fn(entries, race_info, training_data=training_data,
                    track_condition=tc)
    except Exception as ex:
        return None

    scored.sort(key=lambda x: x[1].total, reverse=True)
    # 予想順位順の馬番リスト
    scored_nums = []
    for entry, bd in scored:
        try:
            scored_nums.append(int(entry.horse_number))
        except Exception:
            pass

    race_id = data.get("race_id", "")
    trio_win, trio_pay = get_trio_payout(race_id)
    if trio_win is None:
        return None  # 払戻なし → スキップ

    cls_label = CLASS_LABEL.get(rc, rc)
    return {
        "race_id":     race_id,
        "race_name":   data["race_name"],
        "date":        date_str,
        "class":       rc,          # 元のクラス文字列
        "class_label": cls_label,
        "surface":     surface,
        "scored_nums": scored_nums,
        "trio_win":    trio_win,
        "trio_pay":    trio_pay,
    }


# ---------------------------------------------------------------------------
# BOX シミュレーション
# ---------------------------------------------------------------------------
def sim_box(races, n_top: int) -> dict:
    """上位 n_top 頭 BOX"""
    pts = n_top * (n_top - 1) * (n_top - 2) // 6
    invest = collect = hits = 0
    for r in races:
        invest += pts * 100
        top_set = frozenset(r["scored_nums"][:n_top])
        if r["trio_win"].issubset(top_set):
            collect += r["trio_pay"]
            hits   += 1
    n = len(races)
    return {
        "n_top": n_top, "pts": pts, "n": n,
        "invest": invest, "collect": collect, "hits": hits,
    }


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------
def print_section(label: str, races: list, ns=(3,4,5,6)):
    if not races:
        print(f"\n[{label}] データなし")
        return
    n = len(races)
    print(f"\n[{label}]  n={n}レース")
    hdr = f"  {'N頭BOX':>8}  {'点数':>4}  {'的中':>5}  {'的中率':>7}  {'ROI':>7}  {'平均払戻':>8}  {'収支/R':>8}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for n_top in ns:
        s = sim_box(races, n_top)
        if s["invest"] == 0:
            continue
        roi      = s["collect"] / s["invest"] * 100
        hit_pct  = s["hits"] / s["n"] * 100
        avg_pay  = s["collect"] / s["hits"] if s["hits"] > 0 else 0
        per_r    = (s["collect"] - s["invest"]) / s["n"]
        marker   = " ◀" if roi >= 120 else (" △" if roi >= 100 else "")
        print(f"  {n_top}頭BOX({s['pts']:>2}点)  "
              f"{s['pts']:>4}点  "
              f"{s['hits']:>5}/{s['n']}  "
              f"{hit_pct:>6.1f}%  "
              f"{roi:>6.0f}%  "
              f"{avg_pay:>8,.0f}円  "
              f"{per_r:>+8,.0f}円{marker}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", choices=["芝", "ダ"], default=None)
    args = parser.parse_args()

    all_files = sorted(CACHE_RACE.glob("*.json"))
    print(f"キャッシュ: {len(all_files)}件読み込み開始...")

    races_all = []
    errors = skipped = 0
    for i, fp in enumerate(all_files):
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(all_files)} 処理中... (取得: {len(races_all)}, スキップ: {skipped}, エラー: {errors})")
        try:
            data = json.loads(fp.read_text())
            r = process_race(data, surface_filter=args.surface)
            if r is None:
                skipped += 1
            else:
                races_all.append(r)
        except Exception as ex:
            errors += 1

    surf_label = args.surface or "全体（芝+ダ）"
    print(f"\n完了: 対象レース={len(races_all)}, スキップ={skipped}, エラー={errors}")

    print(f"\n{'='*72}")
    print(f"  三連複BOX N頭 的中率・ROI比較 [{surf_label}]")
    print(f"  期間: 2025/12〜2026/06  対象: 2勝クラス以上")
    print(f"  ※ ROI = 総回収 / 総投資 × 100  点数=C(N,3)")
    print(f"{'='*72}")

    print_section("全体", races_all)

    print(f"\n── クラス別 ──")
    # 元のクラス文字列でグループ化
    classes_order = ["2勝クラス", "3勝クラス", "OP", "重賞"]
    for cls in classes_order:
        sub = [r for r in races_all if r["class"] == cls]
        if sub:
            print_section(cls, sub)

    print(f"\n── 芝/ダート別 ──")
    for surf in ["芝", "ダ"]:
        sub = [r for r in races_all if r["surface"] == surf]
        if sub:
            print_section(surf, sub)

    print(f"\n── クラス×コース ──")
    for cls in classes_order:
        for surf in ["芝", "ダ"]:
            sub = [r for r in races_all if r["class"] == cls and r["surface"] == surf]
            if sub:
                print_section(f"{cls} {surf}", sub)

    # ROI最大の N を各クラスで表示
    print(f"\n{'='*72}")
    print(f"  最適 N 値まとめ（ROI最大）")
    print(f"{'='*72}")
    print(f"  {'区分':<20}  {'最適N':>5}  {'点数':>4}  {'ROI':>7}  {'的中率':>7}")
    print(f"  {'-'*55}")
    segments = [("全体", races_all)]
    for cls in classes_order:
        sub = [r for r in races_all if r["class"] == cls]
        if sub:
            segments.append((cls, sub))
    for surf in ["芝", "ダ"]:
        sub = [r for r in races_all if r["surface"] == surf]
        if sub:
            segments.append((surf, sub))

    for label, races in segments:
        if not races:
            continue
        best = None
        best_roi = -999
        for n_top in (3, 4, 5, 6):
            s = sim_box(races, n_top)
            if s["invest"] == 0:
                continue
            roi = s["collect"] / s["invest"] * 100
            if roi > best_roi:
                best_roi = roi
                best = s
        if best:
            pts = best["pts"]
            hit_pct = best["hits"] / best["n"] * 100
            print(f"  {label:<20}  {best['n_top']:>5}頭  {pts:>3}点  {best_roi:>6.0f}%  {hit_pct:>6.1f}%")
