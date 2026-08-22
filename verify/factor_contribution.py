"""
ファクター寄与度分析スクリプト

各スコアファクターを1つずつ「0固定（無効化）」した状態で再採点し、
ベースライン（全ファクター有効）と比べて
 1. 予想1位が1着になった率（単勝命中率）の変化
 2. 予想上位3頭に実際の1着が入った率（TOP3カバー率）の変化
 3. 各ファクターの「平均絶対加点」（どれだけ多くの馬に効いているか）
を測定する。

「無効化したら成績が下がる＝効いている」
「変わらない or 上がる＝寄与度低い（or 有害）」

usage:
  python3 verify/factor_contribution.py
"""
import sys, re, json, dataclasses
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

from jra_scraper import HorseEntry, RaceInfo
from scorer_turf import score_all as score_turf
from scorer_turf import ScoreBreakdown as ScoreBreakdownTurf
from scorer_dart import score_all as score_dart
from scorer_dart import ScoreBreakdown as ScoreBreakdownDart
from cache_store import cache_get, cache_get_before

BASE = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE = BASE / 'cache' / 'race_result'
NETKEIBA_TRAINING_DIR = BASE / 'cache' / 'netkeiba_training'

TARGET_CLASSES = {"2勝クラス", "3勝クラス", "OP", "重賞"}

# ---- 両ScoreBreakdownの共通数値フィールド（manual_inner_post は bool なので除外）
def _numeric_fields(cls):
    return {
        f.name for f in dataclasses.fields(cls)
        if f.name != "manual_inner_post" and isinstance(f.default, float)
    }

TURF_FACTORS = _numeric_fields(ScoreBreakdownTurf)
DART_FACTORS = _numeric_fields(ScoreBreakdownDart)
# 全ファクターの和集合（芝専用・ダ専用含む）
ALL_FACTORS = sorted(TURF_FACTORS | DART_FACTORS)

# ---- 調教データ取得 -----------------------------------------------------------
def _fetch_training_cached(race_id: str) -> dict | None:
    p = NETKEIBA_TRAINING_DIR / f"{race_id}.json"
    if not p.exists():
        return None
    try:
        from netkeiba_scraper import TrainingData as TD
        raw = json.loads(p.read_text())
        if not raw:
            return None
        return {
            name: TD(horse_name=name, rank=v["rank"],
                     comment=v.get("comment", ""), score=v["score"])
            for name, v in raw.items()
        }
    except Exception:
        return None


# ---- レースデータ → entries + rank_map を構築 --------------------------------
def build_race(data: dict) -> tuple | None:
    """(race_info, entries, rank_map, training_data) or None"""
    if data.get("race_class") not in TARGET_CLASSES:
        return None
    if data.get("surface") not in ("芝", "ダ"):
        return None

    date_str = data["date"]
    dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if not dm:
        return None
    cutoff = f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}"

    race_info = RaceInfo(
        name=data["race_name"], date=date_str, venue=data["venue"],
        race_number=f"{data['race_num_int']}R", distance=data["distance"],
        surface=data["surface"], conditions=data.get("conditions", ""),
        start_time=data.get("start_time", ""), url="",
        race_num=data["race_num_int"],
    )

    entries, rank_map = [], {}
    horse_ids = {}
    for e in data["entries"]:
        hid = e.get("horse_id", "")
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
        rank_map[e["horse_name"]] = e.get("rank", 99)
        if hid:
            horse_ids[e["horse_name"]] = hid

    if len(entries) < 5:
        return None

    # 1着馬が特定できないレースはスキップ
    winner_names = [name for name, r in rank_map.items() if r == 1]
    if not winner_names:
        return None

    training_data = _fetch_training_cached(data.get("race_id", ""))
    # バックテスト時はネットワークアクセスを防ぐため track_condition を "" に固定
    # (track_condition ファクターは "良" 以外のレースのみ有効だが、
    #  外部アクセスなしにはキャッシュがないため採点対象外にする)
    tc = ""  # 外部アクセス禁止: data.get("track_condition", "")

    return race_info, entries, rank_map, training_data, tc, horse_ids


# ---- ベースライン採点 ----------------------------------------------------------
def score_baseline(race_info, entries, training_data, tc, horse_ids, data) -> list[tuple]:
    fn = score_dart if data["surface"] == "ダ" else score_turf
    scored = fn(entries, race_info,
                training_data=training_data,
                track_condition=tc,
                horse_ids=horse_ids)
    scored.sort(key=lambda x: x[1].total, reverse=True)
    return scored


# ---- ファクター無効化して再採点 -----------------------------------------------
def score_with_factor_zeroed(scored_baseline: list[tuple], factor: str) -> list[tuple]:
    """
    ベースラインの ScoreBreakdown からファクターを0にして
    total を再計算した新しいリストを返す。
    actual score_all() を再実行せずに済むよう、既存の breakdown を改変する。
    当該 ScoreBreakdown クラスがそのフィールドを持たない場合はそのまま通す。
    """
    new_results = []
    for entry, bd in scored_baseline:
        # そのクラスにこのファクターが存在するか確認
        if hasattr(bd, factor):
            bd_copy = dataclasses.replace(bd, **{factor: 0.0})
        else:
            bd_copy = bd  # フィールドなし = 変更なし
        new_results.append((entry, bd_copy))

    # total で再ソート
    new_results.sort(key=lambda x: x[1].total, reverse=True)
    return new_results


# ---- 指標計算 -----------------------------------------------------------------
def calc_metrics(scored: list[tuple], rank_map: dict) -> dict:
    """
    scored: [(entry, ScoreBreakdown), ...] ソート済み（高スコア順）
    rank_map: {馬名: 実着順}
    """
    if not scored:
        return {"win1": 0, "top3_cover": 0}

    winner_names = {n for n, r in rank_map.items() if r == 1}
    top1_name = scored[0][0].horse_name
    top3_names = {scored[i][0].horse_name for i in range(min(3, len(scored)))}

    win1     = 1 if top1_name in winner_names else 0
    top3cov  = 1 if winner_names & top3_names else 0

    return {"win1": win1, "top3_cover": top3cov}


# ---- メイン -------------------------------------------------------------------
def main():
    target_files = sorted(CACHE_RACE.glob("*.json"))
    total = len(target_files)
    print(f"対象ファイル: {total}件")

    # キャッシュ済みレースを読み込んで採点
    race_data_list = []  # (race_info, entries, rank_map, training_data, tc, horse_ids, data)
    skipped = 0
    for i, f in enumerate(target_files):
        if i % 200 == 0:
            print(f"  ロード中: {i}/{total}...", flush=True)
        try:
            data = json.loads(f.read_text())
        except Exception:
            skipped += 1
            continue
        result = build_race(data)
        if result is None:
            skipped += 1
            continue
        race_data_list.append((*result, data))

    n_races = len(race_data_list)
    print(f"有効レース: {n_races}件 (スキップ: {skipped}件)\n")

    # ---- ベースライン採点 --------------------------------------------------------
    print("ベースライン採点中...", flush=True)
    baseline_scored_list = []  # list of (scored, rank_map)
    for i, (race_info, entries, rank_map, training_data, tc, horse_ids, data) in enumerate(race_data_list):
        if i % 200 == 0:
            print(f"  {i}/{n_races}...", flush=True)
        scored = score_baseline(race_info, entries, training_data, tc, horse_ids, data)
        baseline_scored_list.append((scored, rank_map))

    # ベースライン指標
    base_win1    = sum(calc_metrics(sc, rm)["win1"]     for sc, rm in baseline_scored_list)
    base_top3cov = sum(calc_metrics(sc, rm)["top3_cover"] for sc, rm in baseline_scored_list)
    base_win1_rate    = base_win1    / n_races
    base_top3cov_rate = base_top3cov / n_races
    print(f"\nベースライン:")
    print(f"  単勝命中率 (予想1位=1着):     {base_win1}/{n_races} = {100*base_win1_rate:.2f}%")
    print(f"  TOP3カバー率(1着馬がTOP3内): {base_top3cov}/{n_races} = {100*base_top3cov_rate:.2f}%")

    # ---- 各ファクターの平均絶対加点を計算（ベースラインのスコア使用）--------------
    factor_abs_mean = {}  # factor -> mean absolute value across all horses
    factor_nonzero_rate = {}  # factor -> 非ゼロだった馬の割合
    horse_count = 0
    factor_abs_sum = defaultdict(float)
    factor_nonzero = defaultdict(int)

    for scored, rank_map in baseline_scored_list:
        for entry, bd in scored:
            horse_count += 1
            for factor in ALL_FACTORS:
                val = abs(getattr(bd, factor, 0.0))
                factor_abs_sum[factor] += val
                if val > 0:
                    factor_nonzero[factor] += 1

    for factor in ALL_FACTORS:
        factor_abs_mean[factor]     = factor_abs_sum[factor] / horse_count if horse_count > 0 else 0
        factor_nonzero_rate[factor] = factor_nonzero[factor] / horse_count if horse_count > 0 else 0

    # ---- 各ファクターを無効化して再採点 ------------------------------------------
    print(f"\nファクター別無効化テスト ({len(ALL_FACTORS)}ファクター)...", flush=True)

    results = []
    for factor in ALL_FACTORS:
        win1_sum = 0
        top3_sum = 0
        for scored, rank_map in baseline_scored_list:
            zeroed = score_with_factor_zeroed(scored, factor)
            m = calc_metrics(zeroed, rank_map)
            win1_sum  += m["win1"]
            top3_sum  += m["top3_cover"]

        win1_rate    = win1_sum    / n_races
        top3cov_rate = top3_sum    / n_races
        delta_win1    = win1_rate    - base_win1_rate
        delta_top3cov = top3cov_rate - base_top3cov_rate

        results.append({
            "factor":          factor,
            "win1_rate":       win1_rate,
            "top3cov_rate":    top3cov_rate,
            "delta_win1":      delta_win1,
            "delta_top3cov":   delta_top3cov,
            "abs_mean":        factor_abs_mean[factor],
            "nonzero_rate":    factor_nonzero_rate[factor],
        })

    # ---- 結果表示 ---------------------------------------------------------------
    # delta_win1 で昇順ソート（無効化して下がるほど寄与度高い → 負の値が重要）
    results.sort(key=lambda x: x["delta_win1"])

    print(f"\n{'='*100}")
    print(f"ファクター寄与度ランキング（ベースライン: 単勝{100*base_win1_rate:.1f}% / TOP3カバー{100*base_top3cov_rate:.1f}%）")
    print(f"{'='*100}")
    print(f"{'ファクター':<26}  {'単勝Δ':>8}  {'TOP3Δ':>8}  {'平均|加点|':>10}  {'非ゼロ馬率':>10}  {'判定'}")
    print("-" * 100)

    for r in results:
        d_win  = r["delta_win1"]
        d_top3 = r["delta_top3cov"]
        # 判定
        if d_win <= -0.015:
            verdict = "★★★ 高寄与"
        elif d_win <= -0.005:
            verdict = "★★  中寄与"
        elif d_win <= 0.005:
            verdict = "★   低寄与"
        elif d_win <= 0.02:
            verdict = "    微有害?"
        else:
            verdict = "    有害候補"
        print(
            f"{r['factor']:<26}  "
            f"{100*r['delta_win1']:>+7.2f}%  "
            f"{100*r['delta_top3cov']:>+7.2f}%  "
            f"{r['abs_mean']:>10.3f}  "
            f"{100*r['nonzero_rate']:>9.1f}%  "
            f"{verdict}"
        )

    # ---- 高寄与 / 低寄与 / 有害 のグループ分け出力 ----------------------------
    print(f"\n{'='*100}")
    print("【高寄与ファクター】（無効化すると単勝命中率が-1.5%以上低下）")
    for r in results:
        if r["delta_win1"] <= -0.015:
            print(f"  {r['factor']:<26}  単勝Δ={100*r['delta_win1']:+.2f}%  "
                  f"TOP3Δ={100*r['delta_top3cov']:+.2f}%  "
                  f"平均加点={r['abs_mean']:.3f}  "
                  f"適用率={100*r['nonzero_rate']:.1f}%")

    print("\n【有害候補ファクター】（無効化すると成績が+1%以上改善）")
    for r in sorted(results, key=lambda x: x["delta_win1"], reverse=True):
        if r["delta_win1"] >= 0.01:
            print(f"  {r['factor']:<26}  単勝Δ={100*r['delta_win1']:+.2f}%  "
                  f"TOP3Δ={100*r['delta_top3cov']:+.2f}%  "
                  f"平均加点={r['abs_mean']:.3f}  "
                  f"適用率={100*r['nonzero_rate']:.1f}%")

    print("\n【非効果ファクター】（絶対値Δ<0.5% かつ 平均加点<0.05）")
    for r in results:
        if abs(r["delta_win1"]) < 0.005 and r["abs_mean"] < 0.05:
            print(f"  {r['factor']:<26}  単勝Δ={100*r['delta_win1']:+.2f}%  "
                  f"平均加点={r['abs_mean']:.3f}  適用率={100*r['nonzero_rate']:.1f}%")

    # ---- CSV保存 ---------------------------------------------------------------
    import csv
    out_path = BASE / "data" / "factor_contribution.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "factor", "win1_rate", "top3cov_rate",
            "delta_win1", "delta_top3cov", "abs_mean", "nonzero_rate"
        ])
        writer.writeheader()
        for r in results:
            writer.writerow({k: round(v, 6) if isinstance(v, float) else v
                             for k, v in r.items()})
    print(f"\nCSV保存: {out_path}")


if __name__ == "__main__":
    main()
