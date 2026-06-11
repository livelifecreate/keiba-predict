"""
採点結果をCSVファイルに出力する。
Google Sheetsに「ファイル → インポート」で取り込める。

使い方:
  python3 export_to_csv.py --training-url https://umasiru.com/archives/XXXXX
  python3 export_to_csv.py   # CSVモード（調教CSV入力済みの場合）
"""

import csv
import os
import re
import sys

from jra_scraper import get_thisweek_g1_urls, get_entry_list
from scorer import score_all, SCORE_LABELS, parse_past_race, _dist_comment, _record_comment
from netkeiba_scraper import TrainingData as TD


def export(race_info, entries, results, output_path: str, actual_rank_map: dict = None):
    sorted_results = sorted(results, key=lambda x: x[1].total, reverse=True)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)

        # ヘッダー行1: レース情報
        writer.writerow([
            f"{race_info.name}",
            race_info.date,
            race_info.venue,
            f"{race_info.distance}({race_info.surface})",
        ])
        writer.writerow([])  # 空行

        # ヘッダー行2: カラム名
        extra_cols = ["実結果"] if actual_rank_map else []
        writer.writerow(
            extra_cols + [
                "予想順位", "枠番", "馬番", "馬名",
                "合計スコア",
                # 加点項目
                "前走重賞近差", "前走3F最速", "同コース実績", "調教評価", "叩き2戦目", "前走好走", "血統距離適性",
                # 減点項目
                "初馬場種別", "距離延長", "昇級初戦", "特殊条件", "前走ローカル",
                "長期休養明け", "枠×馬場不利", "トップハンデ", "急坂好走なし",
                "馬体重変動", "回り不適", "季節×性別",
                # コメント
                "距離適性", "実績",
                # 手動確認
                "内枠先行確認",
            ]
        )

        for rank, (entry, d) in enumerate(sorted_results, 1):
            dist_c = _dist_comment(entry, race_info.distance, race_info.surface, race_info.venue)
            rec_c  = _record_comment(entry)
            manual = "要確認" if d.manual_inner_post else ""
            extra_vals = [actual_rank_map.get(entry.horse_name, "")] if actual_rank_map else []

            writer.writerow(
                extra_vals + [
                    rank,
                    entry.frame_number,
                    entry.horse_number,
                    entry.horse_name,
                    d.total,
                    # 加点
                    d.prev_high_grade_close,
                    d.fastest_3f,
                    d.same_course,
                    d.training_rank,
                    d.second_start,
                    d.prev_run_bonus,
                    d.bloodline_distance,
                    # 減点
                    d.first_surface,
                    d.distance_up,
                    d.promotion,
                    d.special_condition,
                    d.local_prev,
                    d.long_rest,
                    d.post_surface,
                    d.top_weight,
                    d.no_steep_win,
                    d.weight_change,
                    d.wrong_direction,
                    d.seasonal_sex,
                    # コメント
                    dist_c,
                    rec_c,
                    manual,
                ]
            )

    print(f"  [CSV出力] {output_path}")
    return output_path


def _csv_filename(race_info) -> str:
    import re as _re
    from pathlib import Path
    date = _re.sub(r"[年月]", "", race_info.date).replace("日", "")
    name = _re.sub(r'[\s　/\\:*?"<>|]', "_", race_info.name)
    venue = getattr(race_info, "venue", "") or "不明"
    dm = _re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', race_info.date)
    date_dir = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else "不明"
    save_dir = Path(__file__).parent / "results" / date_dir / venue
    save_dir.mkdir(parents=True, exist_ok=True)
    return str(save_dir / f"score_{date}_{name}.csv")


if __name__ == "__main__":
    training_url = None
    race_keyword = None
    args = sys.argv[1:]

    if "--training-url" in args:
        idx = args.index("--training-url")
        if idx + 1 < len(args):
            training_url = args[idx + 1]

    if "--race" in args:
        idx = args.index("--race")
        if idx + 1 < len(args):
            race_keyword = args[idx + 1]

    if race_keyword:
        from netkeiba_race_scraper import search_race, get_entry_list_netkeiba
        race_id = search_race(race_keyword)
        if not race_id:
            sys.exit(1)
        race_list = [("netkeiba", race_id)]
    else:
        from jra_scraper import get_thisweek_g1_urls, get_entry_list
        urls = get_thisweek_g1_urls()
        if not urls:
            print("今週のG1出馬表が見つかりませんでした。")
            sys.exit(1)
        race_list = [("jra", url) for url in urls]

    for source, key in race_list:
        if source == "netkeiba":
            race_info, entries = get_entry_list_netkeiba(key)
        else:
            race_info, entries = get_entry_list(key)

        if training_url:
            from umasiru_scraper import scrape as scrape_umasiru
            print(f"  [調教] {training_url} からデータ取得中...")
            umasiru_data = scrape_umasiru(training_url)
            training = {
                name: TD(horse_name=name, rank=e.rank, comment="", score=e.converted_score)
                for name, e in umasiru_data.items()
            }
            matched = sum(1 for e in entries if e.horse_name in training)
            print(f"  [調教] {matched}/{len(entries)}頭マッチ")
        else:
            from training_input import load_training_input
            manual = load_training_input(race_info)
            training = {
                name: TD(horse_name=name, rank="手動", comment=ti.memo, score=ti.converted_score)
                for name, ti in manual.items()
            }

        results = score_all(entries, race_info, training_data=training)
        out = _csv_filename(race_info)
        export(race_info, entries, results, out)
        print(f"  → Googleスプレッドシートへ: ファイル → インポート → アップロード")
