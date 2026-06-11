"""
土日全レーススキャン → 買いサイン一覧

使い方:
  python3 weekend_predict.py              # 今週土日（2勝クラス以上）
  python3 weekend_predict.py --sat        # 土曜のみ
  python3 weekend_predict.py --sun        # 日曜のみ
  python3 weekend_predict.py --all-class  # 全クラス（未勝利〜重賞）
  python3 weekend_predict.py --venue 東京  # 特定会場のみ

フロー:
  1. get_race_list() で土日の全レース一覧取得
  2. クラスフィルタ（2勝クラス以上が検証済みのため）
  3. 各レースを採点（調教データは省略してスピード優先）
  4. オッズ自動取得
  5. 買いサインを判定して表示
  6. 買いサインありレースを末尾にまとめて表示
"""
import sys, re, time, datetime, argparse
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0] or ".")

from netkeiba_race_scraper import get_race_list, get_entry_list_netkeiba, fetch_odds
from scorer_turf import score_all as score_turf, parse_race_class, save_csv as save_csv_turf
from scorer_dart import score_all as score_dart, save_csv as save_csv_dart
from keibabook_scraper import find_kb_race_id, scrape as scrape_kb
from netkeiba_scraper import TrainingData as TD


def _fetch_training(race_info) -> dict:
    """競馬ブックから調教データを取得して {馬名: TrainingData} を返す。失敗時は {}。"""
    dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", race_info.date)
    if not dm or not race_info.race_num:
        return {}
    date_str = f"{dm.group(1)}{int(dm.group(2)):02d}{int(dm.group(3)):02d}"
    kb_id = find_kb_race_id(date_str, race_info.race_num, race_info.venue)
    if not kb_id:
        return {}
    try:
        kb_data = scrape_kb(f"https://p.keibabook.co.jp/cyuou/cyokyo/0/0/{kb_id}")
    except Exception:
        return {}
    result = {
        r["馬名"]: TD(horse_name=r["馬名"], rank="KB", comment=r.get("メモ", ""),
                      score=r["時計スコア(1-5)"] + r["状態スコア(1-5)"])
        for r in kb_data
    }
    for td_obj in result.values():
        t = td_obj.score
        td_obj.score = 3 if t >= 9 else 2 if t >= 7 else 1 if t >= 5 else 0 if t >= 3 else -1
    return result

# ── サイン判定（scorer_turf.pyのprint_buy_signsと同ロジック）──────────

def calc_buy_sign(sorted_results, odds_map, n_horses):
    """
    Returns: (sign_level, sign_text, detail_text)
      sign_level: "7pt" / "formb" / "skip" / "neutral"
    """
    if len(sorted_results) < 2:
        return "neutral", "", ""

    top_entry, top_d = sorted_results[0]
    sec_entry, sec_d = sorted_results[1]
    score1 = top_d.total
    score2 = sec_d.total
    gap    = score1 - score2
    odds1  = odds_map.get(top_entry.horse_name, 0)
    n      = n_horses
    has_sc = top_d.same_course >= 4

    skips = []
    if n == 18:
        skips.append("18頭フルゲート")
    if 3 <= gap < 5:
        skips.append(f"乖離{gap:.1f}pt（3〜5pt）")
    if has_sc:
        skips.append("同コース実績主因")
    if odds1 and 8 <= odds1 < 15:
        skips.append(f"軸{odds1:.1f}倍（8〜14倍）")

    if skips:
        return "skip", "⚠ 見送り", " / ".join(skips)

    if odds1:
        is_7pt = gap >= 5 and n <= 13 and 2 <= odds1 < 8
    else:
        is_7pt = gap >= 5 and n <= 13

    if is_7pt:
        detail = f"乖離{gap:.1f}pt + {n}頭" + (f" + 軸{odds1:.1f}倍" if odds1 else "")
        return "7pt", "🎯 7点推奨", detail

    notes = []
    if gap < 1:
        notes.append(f"乖離{gap:.1f}pt横並び→ROI222%")
    if 14 <= n <= 17:
        notes.append(f"{n}頭立て→ROI164%")
    if odds1 and odds1 >= 15:
        notes.append(f"穴軸{odds1:.1f}倍→ROI393%")
    if odds1 and odds1 < 2:
        notes.append(f"断然{odds1:.1f}倍→命中75%")

    if notes:
        return "formb", "📋 フォームB推奨", " / ".join(notes)

    return "formb", "📋 フォームB（標準）", f"乖離{gap:.1f}pt {n}頭"


# ── クラス判定 ─────────────────────────────────────────────────────────

def race_class_from_conditions(conditions: str, race_name: str) -> int:
    return parse_race_class(conditions + " " + race_name)


# ── メイン ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sat",       action="store_true", help="土曜のみ")
    parser.add_argument("--sun",       action="store_true", help="日曜のみ")
    parser.add_argument("--all-class", action="store_true", help="全クラス（デフォルト: 2勝以上）")
    parser.add_argument("--venue",     default="",          help="会場絞り込み（例: 東京）")
    parser.add_argument("--min-class", type=int, default=2, help="最低クラス（0=未勝利 2=2勝 4=OP）")
    args = parser.parse_args()

    # 日付設定
    today = datetime.date.today()
    weekday = today.weekday()
    days_to_sat = (5 - weekday) % 7
    sat = today if weekday == 5 else today + datetime.timedelta(days=days_to_sat)
    sun = sat + datetime.timedelta(days=1)

    if args.sat:
        dates = [sat]
    elif args.sun:
        dates = [sun]
    else:
        dates = [sat, sun]

    min_class = 0 if args.all_class else args.min_class

    print(f"\n{'='*65}")
    print(f"  週末レーススキャン  {' / '.join(str(d) for d in dates)}")
    print(f"  対象クラス: {'全クラス' if min_class == 0 else f'{min_class}勝クラス以上（OP・重賞含む）'}")
    if args.venue:
        print(f"  会場: {args.venue}")
    print(f"{'='*65}\n")

    print("レース一覧取得中...")
    races = get_race_list(dates)
    if args.venue:
        races = [r for r in races if args.venue in r["venue"]]

    print(f"  取得: {len(races)}レース")

    # ── 各レースを処理 ────────────────────────────────────────────────
    sign_summary = []   # 買いサインありレースをまとめる
    errors       = []

    for i, race in enumerate(races):
        race_id   = race["race_id"]
        label     = race["label"]
        print(f"\n[{i+1}/{len(races)}] {label}")

        try:
            race_info, entries = get_entry_list_netkeiba(race_id)
        except Exception as e:
            print(f"  → 取得失敗: {e}")
            errors.append(label)
            continue

        if not entries:
            print("  → 出走なし")
            continue

        # 新馬戦スキップ
        if "新馬" in race_info.name:
            print(f"  → スキップ（新馬戦）")
            continue

        # クラスフィルタ
        race_class = race_class_from_conditions(race_info.conditions, race_info.name)
        if race_class < min_class:
            cls_name = {0:"未勝利",1:"1勝",2:"2勝",3:"3勝",4:"OP",5:"GIII",6:"GII",7:"GI"}.get(race_class, "?")
            print(f"  → スキップ（{cls_name}クラス）")
            continue

        n = len(entries)
        print(f"  {race_info.name}  {race_info.distance}({race_info.surface})  {n}頭")

        # 採点（競馬ブックから調教データ自動取得）
        training = _fetch_training(race_info)
        if training:
            print(f"  [調教] {len(training)}頭取得")
        try:
            if race_info.surface == "ダ":
                results = score_dart(entries, race_info, training_data=training)
            else:
                results = score_turf(entries, race_info, training_data=training)
        except Exception as e:
            print(f"  → 採点失敗: {e}")
            errors.append(label)
            continue

        sorted_r = sorted(results, key=lambda x: x[1].total, reverse=True)

        # オッズ取得
        odds_raw = fetch_odds(race_id)  # {馬番: float}
        num_to_name = {str(e.horse_number): e.horse_name for e in entries}
        odds_map = {num_to_name[k]: v for k, v in odds_raw.items() if k in num_to_name}

        # サイン判定
        sign_level, sign_text, sign_detail = calc_buy_sign(sorted_r, odds_map, n)

        # ファイル名タグ（買いサインのみ付与）
        if sign_level == "7pt":
            sign_tag = "★7pt推奨"
        elif sign_level == "formb":
            sign_tag = "★フォームB推奨" if "推奨" in sign_text else "★フォームB"
        else:
            sign_tag = None

        # CSV保存（サインタグ・調教コメント・買い目含む）
        try:
            _save = save_csv_dart if race_info.surface == "ダ" else save_csv_turf
            _save(results, race_info,
                  odds_map=odds_map if odds_map else None,
                  training_data=training,
                  sign_tag=sign_tag)
        except Exception as e:
            print(f"  [CSV保存失敗] {e}")

        # 上位3頭を表示
        top3 = sorted_r[:3]
        for rank, (entry, d) in enumerate(top3, 1):
            o = odds_map.get(entry.horse_name)
            odds_str = f" {o:.1f}倍" if o else ""
            print(f"  {rank}位 {entry.horse_number}番 {entry.horse_name:<12} {d.total:+.1f}pt{odds_str}")

        print(f"  → {sign_text}  {sign_detail}")

        if sign_level in ("7pt", "formb"):
            sign_summary.append({
                "label":    label,
                "race_id":  race_id,
                "name":     race_info.name,
                "date":     race["date"],
                "venue":    race_info.venue,
                "dist":     f"{race_info.distance}({race_info.surface})",
                "n":        n,
                "sign":     sign_text,
                "detail":   sign_detail,
                "top1":     f"{sorted_r[0][0].horse_number}番{sorted_r[0][0].horse_name}",
                "top2":     f"{sorted_r[1][0].horse_number}番{sorted_r[1][0].horse_name}" if len(sorted_r)>1 else "",
                "level":    sign_level,
            })

    # ── 買いサインまとめ ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  買いサインまとめ  ({len(sign_summary)}件)")
    print(f"{'='*65}")

    sevens  = [s for s in sign_summary if s["level"] == "7pt"]
    formbs  = [s for s in sign_summary if s["level"] == "formb"]

    if sevens:
        print("\n🎯 7点推奨（ROI193%ゾーン）")
        for s in sevens:
            print(f"  {s['date']} {s['venue']} {s['name']}  {s['dist']}  {s['n']}頭")
            print(f"  軸: {s['top1']} / {s['top2']}  ({s['detail']})")
            print(f"  race_id: {s['race_id']}")

    if formbs:
        print("\n📋 フォームB推奨（ROI82%〜）")
        for s in formbs:
            print(f"  {s['date']} {s['venue']} {s['name']}  {s['dist']}  {s['n']}頭")
            print(f"  軸: {s['top1']}  ({s['detail']})")
            print(f"  race_id: {s['race_id']}")

    if not sign_summary:
        print("  今週は買いサインなし（全レース見送りまたは標準）")

    if errors:
        print(f"\n  ※ 取得エラー: {len(errors)}件")

    print()


if __name__ == "__main__":
    main()
