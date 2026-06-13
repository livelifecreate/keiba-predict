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
from netkeiba_scraper import TrainingData as TD, fetch_training_data
from jra_scraper import build_jra_url, get_entry_list as get_entry_list_jra


def _fetch_training(race_id: str) -> dict:
    """netkeiba oikiri から全頭の調教評価を取得して {馬名: TrainingData} を返す。失敗時は {}。"""
    try:
        result = fetch_training_data(race_id)
        return result or {}
    except Exception:
        return {}


def _fetch_jra_odds(race_id: str, race_date: datetime.date, entries) -> dict:
    """JRA公式出馬表から単勝オッズを取得。{馬名: float} を返す。失敗時は {}。"""
    try:
        url = build_jra_url(race_id, race_date)
        _, jra_entries = get_entry_list_jra(url)
        if not jra_entries:
            return {}
        num_to_name = {str(e.horse_number): e.horse_name for e in entries}
        return {
            num_to_name[je.horse_number]: je.odds
            for je in jra_entries
            if je.odds > 0 and je.horse_number in num_to_name
        }
    except Exception:
        return {}

# ── サイン判定（scorer_turf.pyのprint_buy_signsと同ロジック）──────────

def gen_eval_comment(sorted_results, odds_map, n_horses, sign_level, sign_detail) -> list[str]:
    """買いサイン評価コメントを生成して list[str] で返す"""
    if len(sorted_results) < 2:
        return []

    top_entry, top_d = sorted_results[0]
    sec_entry, sec_d = sorted_results[1]
    gap   = top_d.total - sec_d.total
    odds1 = (odds_map or {}).get(top_entry.horse_name, 0)
    odds2 = (odds_map or {}).get(sec_entry.horse_name, 0)
    lines = []

    if sign_level == "skip":
        reasons = [r.strip() for r in sign_detail.split(" / ")]

        if any("乖離" in r and "3〜5pt" in r for r in reasons):
            lines.append(f"乖離{gap:.1f}ptは見送りゾーン（3〜5pt）。1位と2位の差が小さく軸信頼度が不足。")
        if any("18頭" in r for r in reasons):
            lines.append("18頭フルゲートは荒れやすく軸信頼度が低下。")
        if any("同コース実績" in r for r in reasons):
            lines.append("1位の主要加点が同コース実績（過去成績依存）。当日の状態変化に注意。")
        if any("8〜14倍" in r for r in reasons):
            lines.append(f"軸{odds1:.1f}倍は期待値が安定しない中穴ゾーン（8〜14倍）。")

        if odds1 and odds1 < 2:
            lines.append(f"1位{top_entry.horse_name}{odds1:.1f}倍：複勝命中率75%超も控除率約20%で単勝は期待値マイナス。")
        elif odds1 and odds1 < 4:
            lines.append(f"1位{top_entry.horse_name}{odds1:.1f}倍：人気集中で三連複の配当も低くなりやすい。")

        if odds2 and odds2 >= 20:
            lines.append(f"2位{sec_entry.horse_name}{odds2:.1f}倍：相手を絞り込みにくく三連複の期待値も低い。")
        elif odds2:
            lines.append(f"2位{sec_entry.horse_name}{odds2:.1f}倍（スコア差{gap:.1f}pt）。")

    elif sign_level == "7pt":
        lines.append(f"乖離{gap:.1f}ptで1位{top_entry.horse_name}の軸信頼度が高い（5pt以上推奨ゾーン）。")
        if odds1:
            lines.append(f"軸{odds1:.1f}倍は期待値プラスの推奨帯（2〜7倍）。三連複7点買いを推奨。")
        if odds2:
            lines.append(f"2位{sec_entry.horse_name}{odds2:.1f}倍との2頭軸も選択肢。")

    elif sign_level == "formb":
        specific = False
        if gap < 1:
            lines.append(f"上位横並び（乖離{gap:.1f}pt）。フォームBで広くカバー。ROI222%ゾーン。")
            specific = True
        elif 14 <= n_horses <= 17:
            lines.append(f"{n_horses}頭立てで頭数多め。フォームBでカバレッジを広げる。ROI164%ゾーン。")
            specific = True
        if odds1 and odds1 >= 15:
            lines.append(f"穴軸{top_entry.horse_name}{odds1:.1f}倍。システムスコア1位の市場過小評価馬。ROI393%ゾーン。")
        elif odds1 and odds1 < 2:
            lines.append(f"断然{odds1:.1f}倍。スコア1位かつ見送り条件なし。命中率重視の少額購入で対応。")
        elif not specific:
            lines.append(f"乖離{gap:.1f}pt・{n_horses}頭・軸{odds1:.1f}倍。標準フォームBゾーン。")

    return lines


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
    parser.add_argument("--track",     default="",
                        help="馬場状態（例: 良 / 稍重 / 重 / 不良 / 東京:良,阪神:稍重）")
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

    # 馬場状態の解析: "良" → 全会場良 / "東京:良,阪神:稍重" → 個別指定
    track_map: dict[str, str] = {}
    if args.track:
        if ":" in args.track:
            for part in args.track.split(","):
                part = part.strip()
                if ":" in part:
                    v, tc = part.split(":", 1)
                    track_map[v.strip()] = tc.strip()
        else:
            track_map["__all__"] = args.track.strip()
    else:
        # 当日実行時は馬場を対話で確認
        today = datetime.date.today()
        if today in dates:
            print("馬場状態を入力してください（例: 良 / 稍重 / 重 / 不良）")
            print("  全会場同じ場合: 良  ← そのまま入力")
            print("  会場別の場合  : 東京:良,阪神:稍重,函館:良")
            print("  スキップする場合: Enter キーのみ")
            user_input = input("馬場 > ").strip()
            if user_input:
                if ":" in user_input:
                    for part in user_input.split(","):
                        part = part.strip()
                        if ":" in part:
                            v, tc = part.split(":", 1)
                            track_map[v.strip()] = tc.strip()
                else:
                    track_map["__all__"] = user_input

    def get_track(venue: str) -> str:
        return track_map.get(venue) or track_map.get("__all__", "")

    print(f"\n{'='*65}")
    print(f"  週末レーススキャン  {' / '.join(str(d) for d in dates)}")
    print(f"  対象クラス: {'全クラス' if min_class == 0 else f'{min_class}勝クラス以上（OP・重賞含む）'}")
    if args.venue:
        print(f"  会場: {args.venue}")
    if track_map:
        tc_str = track_map.get("__all__") or ", ".join(f"{k}:{v}" for k, v in track_map.items())
        print(f"  馬場状態: {tc_str}")
    else:
        print(f"  馬場状態: 未指定（スコアに反映なし）")
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
        training = _fetch_training(race_id)
        if training:
            print(f"  [調教] {len(training)}頭取得")
        tc = get_track(race_info.venue)
        try:
            if race_info.surface == "ダ":
                results = score_dart(entries, race_info, training_data=training, track_condition=tc)
            else:
                results = score_turf(entries, race_info, training_data=training, track_condition=tc)
        except Exception as e:
            print(f"  → 採点失敗: {e}")
            errors.append(label)
            continue

        sorted_r = sorted(results, key=lambda x: x[1].total, reverse=True)

        # オッズ取得（JRA公式優先、失敗時はnetkeiba API）
        race_date = race.get("date")
        odds_map = {}
        if race_date:
            odds_map = _fetch_jra_odds(race_id, race_date, entries)
        if not odds_map:
            odds_raw = fetch_odds(race_id)
            num_to_name = {str(e.horse_number): e.horse_name for e in entries}
            odds_map = {num_to_name[k]: v for k, v in odds_raw.items() if k in num_to_name}

        # サイン判定
        sign_level, sign_text, sign_detail = calc_buy_sign(sorted_r, odds_map, n)

        # 評価コメント生成
        eval_comment = gen_eval_comment(sorted_r, odds_map, n, sign_level, sign_detail)

        # ファイル名タグ（買いサインのみ付与）
        if sign_level == "7pt":
            sign_tag = "★7pt推奨"
        elif sign_level == "formb":
            sign_tag = "★フォームB推奨" if "推奨" in sign_text else "★フォームB"
        else:
            sign_tag = None

        # CSV保存（サインタグ・調教コメント・評価コメント・買い目含む）
        try:
            _save = save_csv_dart if race_info.surface == "ダ" else save_csv_turf
            _save(results, race_info,
                  odds_map=odds_map if odds_map else None,
                  training_data=training,
                  sign_tag=sign_tag,
                  eval_comment=eval_comment)
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
