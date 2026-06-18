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


def _fetch_jra_odds(race_id: str, race_date: datetime.date, entries) -> tuple[dict, str]:
    """JRA公式出馬表から単勝オッズと馬場状態を取得。({馬名: float}, 馬場状態) を返す。失敗時は ({}, "")。"""
    try:
        url = build_jra_url(race_id, race_date)
        jra_race_info, jra_entries = get_entry_list_jra(url)
        if not jra_entries:
            return {}, ""
        num_to_name = {str(e.horse_number): e.horse_name for e in entries}
        odds_map = {
            num_to_name[je.horse_number]: je.odds
            for je in jra_entries
            if je.odds > 0 and je.horse_number in num_to_name
        }
        track_condition = jra_race_info.track_condition if jra_race_info else ""
        return odds_map, track_condition
    except Exception:
        return {}, ""

# ── サイン判定（scorer_turf.pyのprint_buy_signsと同ロジック）──────────

def gen_eval_comment(sorted_results, odds_map, n_horses, sign_level, sign_detail, race_class=0) -> list[str]:
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
        if any("ROI47%" in r for r in reasons):
            lines.append(f"2勝クラス以下：全オッズ帯でROI47%以下。3勝クラス以上のみ買い。")
        elif any("ROI17%" in r for r in reasons):
            lines.append(f"重賞クラス：ROI17%（n=49）。買い条件を満たさない。")

        if odds2 and odds2 >= 20:
            lines.append(f"2位{sec_entry.horse_name}{odds2:.1f}倍：相手を絞り込みにくく三連複の期待値も低い。")
        elif odds2:
            lines.append(f"2位{sec_entry.horse_name}{odds2:.1f}倍（スコア差{gap:.1f}pt）。")

    elif sign_level == "tierce":
        lines.append(f"3勝クラス×{odds1:.1f}倍：三連単A+Bフォーメーション推奨（ROI241%・ヒット率24%）。")
        lines.append(f"[A] {top_entry.horse_name}（1着固定）× 紐4頭（2-3着）12点")
        lines.append(f"[B] 紐4頭（1着）× {top_entry.horse_name}（2着固定）× 紐4頭（3着）12点")

    elif sign_level in ("box4", "box5"):
        buy_n = 4 if sign_level == "box4" else 5
        buy_pts = 4 if buy_n == 4 else 10
        if odds1 and odds1 < 2:
            lines.append(f"断然人気{odds1:.1f}倍：複勝率87.9%・三連複{buy_n}頭BOX回収率141%（バックテスト33R）。")
        if gap < 1:
            lines.append(f"上位横並び（乖離{gap:.1f}pt）。三連複{buy_n}頭BOX({buy_pts}点)で広くカバー。")
        elif 14 <= n_horses <= 17:
            lines.append(f"{n_horses}頭立て。三連複{buy_n}頭BOX({buy_pts}点)でカバレッジを確保。")
        if odds1 and 5 <= odds1 < 10 and race_class >= 4:
            lines.append(f"OP以上×{odds1:.1f}倍帯。三連複{buy_n}頭BOX推奨。")
        if not lines:
            lines.append(f"乖離{gap:.1f}pt・{n_horses}頭。三連複{buy_n}頭BOX({buy_pts}点)推奨。")

    return lines


def calc_buy_sign(sorted_results, odds_map, n_horses, race_class=0):
    """
    Returns: (sign_level, sign_text, detail_text)
      sign_level: "tierce" / "box4" / "box5" / "skip" / "neutral"
      race_class: 0=未勝利 1=1勝 2=2勝 3=3勝 4=OP 5=GIII 6=GII 7=GI
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
    skips = []
    if n == 18:
        skips.append("18頭フルゲート")
    if 3 <= gap < 5:
        skips.append(f"乖離{gap:.1f}pt（3〜5pt）")
    if race_class < 3:
        cls_name = {0: "未勝利", 1: "1勝", 2: "2勝"}.get(race_class, f"class{race_class}")
        skips.append(f"{cls_name}クラス（ROI47%）")
    if race_class >= 5:
        cls_name = {5: "GIII", 6: "GII", 7: "GI"}.get(race_class, "重賞")
        skips.append(f"{cls_name}（ROI17%）")

    if skips:
        return "skip", "⚠ 見送り", " / ".join(skips)

    # 三連単 A+B フォーメーション: 3勝クラス × 2〜4.9倍（ROI241%・ヒット率24%）
    if race_class == 3 and odds1 and 2 <= odds1 < 5:
        detail = f"3勝クラス×{odds1:.1f}倍 / 乖離{gap:.1f}pt {n}頭 / A+B 24点"
        return "tierce", "🏇 三連単A+B推奨", detail

    # 買い目: 3勝クラス→4頭BOX(4点)、OP以上→5頭BOX(10点)
    # ※ 乖離≥5ptの高信頼7点推奨は廃止（バックテスト: 単勝ROI50%・5BOX ROI40%）
    is_box4 = (race_class == 3)

    ctx = []
    if odds1 and odds1 < 2:
        ctx.append(f"断然人気{odds1:.1f}倍(複勝87.9%/5BOX回収141%)")
    if gap < 1:
        ctx.append(f"横並び乖離{gap:.1f}pt")
    if 14 <= n <= 17:
        ctx.append(f"{n}頭立て")
    if odds1 and odds1 >= 10 and race_class >= 3:
        ctx.append(f"軸{odds1:.1f}倍(高配当帯)")
    elif odds1 and 5 <= odds1 < 10 and race_class >= 4:
        ctx.append(f"OP×{odds1:.1f}倍")
    ctx.append(f"乖離{gap:.1f}pt/{n}頭")
    detail = " / ".join(ctx)

    if is_box4:
        return "box4", "三連複4頭BOX (4点)", detail
    return "box5", "三連複5頭BOX (10点)", detail


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

    # 日付設定（今日が土曜→sat=今日、今日が日曜→sun=今日）
    today = datetime.date.today()
    weekday = today.weekday()
    if weekday == 6:          # 今日が日曜
        sun = today
        sat = today - datetime.timedelta(days=1)
    elif weekday == 5:        # 今日が土曜
        sat = today
        sun = today + datetime.timedelta(days=1)
    else:                     # 平日→次の土日
        days_to_sat = (5 - weekday) % 7
        sat = today + datetime.timedelta(days=days_to_sat)
        sun = sat + datetime.timedelta(days=1)

    if args.sat:
        dates = [sat]
    elif args.sun:
        dates = [sun]
    else:
        dates = [sat, sun]

    min_class = 0 if args.all_class else args.min_class

    # 馬場状態の解析: "良" → 全会場良 / "東京:良,阪神:稍重" → 個別指定
    # --track 未指定時はレース取得後に race_info.track_condition を自動使用
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

    def get_track(venue: str, auto_tc: str = "") -> str:
        return track_map.get(venue) or track_map.get("__all__", "") or auto_tc

    print(f"\n{'='*65}")
    print(f"  週末レーススキャン  {' / '.join(str(d) for d in dates)}")
    print(f"  対象クラス: {'全クラス' if min_class == 0 else f'{min_class}勝クラス以上（OP・重賞含む）'}")
    if args.venue:
        print(f"  会場: {args.venue}")
    if track_map:
        tc_str = track_map.get("__all__") or ", ".join(f"{k}:{v}" for k, v in track_map.items())
        print(f"  馬場状態: {tc_str}（手動指定）")
    else:
        print(f"  馬場状態: レース毎に自動取得")
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

        # 調教データ取得
        training = _fetch_training(race_id)
        if training:
            print(f"  [調教] {len(training)}頭取得")

        # オッズ・馬場状態取得（JRA公式優先、失敗時はnetkeiba API）
        race_date = race.get("date")
        odds_map = {}
        jra_track = ""
        if race_date:
            odds_map, jra_track = _fetch_jra_odds(race_id, race_date, entries)
        if not odds_map:
            odds_raw = fetch_odds(race_id)
            num_to_name = {str(e.horse_number): e.horse_name for e in entries}
            odds_map = {num_to_name[k]: v for k, v in odds_raw.items() if k in num_to_name}

        # 馬場状態: --track引数 > JRA公式 > netkeiba shutuba
        tc = get_track(race_info.venue, jra_track or race_info.track_condition)
        tc_src = "手動指定" if track_map else ("JRA公式" if jra_track else ("netkeiba" if race_info.track_condition else "未取得"))
        print(f"  [馬場] {tc or '未取得'}（{tc_src}）")

        # 採点
        horse_ids = {e.horse_name: e.horse_id for e in entries if getattr(e, "horse_id", "")}
        try:
            if race_info.surface == "ダ":
                results = score_dart(entries, race_info, training_data=training, track_condition=tc, horse_ids=horse_ids)
            else:
                results = score_turf(entries, race_info, training_data=training, track_condition=tc, horse_ids=horse_ids)
        except Exception as e:
            print(f"  → 採点失敗: {e}")
            errors.append(label)
            continue

        sorted_r = sorted(results, key=lambda x: x[1].total, reverse=True)

        # サイン判定
        sign_level, sign_text, sign_detail = calc_buy_sign(sorted_r, odds_map, n, race_class)

        # 評価コメント生成
        eval_comment = gen_eval_comment(sorted_r, odds_map, n, sign_level, sign_detail, race_class)

        # ファイル名タグ（買いサインのみ付与）
        if sign_level == "tierce":
            sign_tag = "★三連単A+B"
        elif sign_level == "box4":
            sign_tag = "★三連複4頭BOX"
        elif sign_level == "box5":
            sign_tag = "★三連複5頭BOX"
        else:
            sign_tag = None

        # CSV出力
        try:
            if race_info.surface == "ダ":
                save_csv_dart(sorted_r, race_info, odds_map=odds_map, training_data=training,
                              sign_tag=sign_tag, eval_comment=eval_comment, race_id=race_id,
                              sign_level=sign_text, sign_detail_text=sign_detail, race_class=race_class)
            else:
                save_csv_turf(sorted_r, race_info, odds_map=odds_map, training_data=training,
                              sign_tag=sign_tag, eval_comment=eval_comment, race_id=race_id,
                              sign_level=sign_text, sign_detail_text=sign_detail, race_class=race_class)
        except Exception as e:
            print(f"  [CSV] 保存失敗: {e}")

        # 上位3頭を表示
        top3 = sorted_r[:3]
        for rank, (entry, d) in enumerate(top3, 1):
            o = odds_map.get(entry.horse_name)
            odds_str = f" {o:.1f}倍" if o else ""
            print(f"  {rank}位 {entry.horse_number}番 {entry.horse_name:<12} {d.total:+.1f}pt{odds_str}")

        print(f"  → {sign_text}  {sign_detail}")

        if sign_level in ("tierce", "box4", "box5"):
            def horse_label(i):
                if len(sorted_r) > i:
                    e = sorted_r[i][0]
                    return f"{e.horse_number}番{e.horse_name}"
                return ""
            sign_summary.append({
                "label":      label,
                "race_id":    race_id,
                "name":       race_info.name,
                "date":       race["date"],
                "venue":      race_info.venue,
                "dist":       f"{race_info.distance}({race_info.surface})",
                "n":          n,
                "sign":       sign_text,
                "detail":     sign_detail,
                "top1":       horse_label(0),
                "top2":       horse_label(1),
                "top3":       horse_label(2),
                "top4":       horse_label(3),
                "top5":       horse_label(4),
                "level":      sign_level,
                "race_class": race_class,
            })

    # ── 買いサインまとめ ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  買いサインまとめ  ({len(sign_summary)}件)")
    print(f"{'='*65}")

    tierces = [s for s in sign_summary if s["level"] == "tierce"]
    box4s   = [s for s in sign_summary if s["level"] == "box4"]
    box5s   = [s for s in sign_summary if s["level"] == "box5"]

    if tierces:
        print("\n🏇 三連単A+Bフォーメーション（24点）")
        for s in tierces:
            axis = s["top1"]
            himo = "・".join(h for h in [s.get("top2",""), s.get("top3",""), s.get("top4",""), s.get("top5","")] if h)
            print(f"  {s['date']} {s['venue']} {s['name']}  {s['dist']}  {s['n']}頭")
            print(f"  [A] 1着固定: {axis} → 2-3着: {himo}  12点")
            print(f"  [B] 1着: {himo} → 2着固定: {axis} → 3着: {himo}  12点")
            print(f"  ({s['detail']})")
            print(f"  race_id: {s['race_id']}")

    if box4s:
        print("\n三連複4頭BOX (4点) ── 3勝クラス")
        for s in box4s:
            horses = "・".join(h for h in [s.get(f"top{i}","") for i in range(1, 5)] if h)
            print(f"  {s['date']} {s['venue']} {s['name']}  {s['dist']}  {s['n']}頭")
            print(f"  BOX: {horses}")
            print(f"  馬連: {s['top1']} × {s['top2']}")
            print(f"  ({s['detail']})")
            print(f"  race_id: {s['race_id']}")

    if box5s:
        print("\n三連複5頭BOX (10点) ── OP以上")
        for s in box5s:
            horses = "・".join(h for h in [s.get(f"top{i}","") for i in range(1, 6)] if h)
            print(f"  {s['date']} {s['venue']} {s['name']}  {s['dist']}  {s['n']}頭")
            print(f"  BOX: {horses}")
            print(f"  馬連: {s['top1']} × {s['top2']}")
            print(f"  ({s['detail']})")
            print(f"  race_id: {s['race_id']}")

    if not sign_summary:
        print("  今週は買いサインなし（全レース見送りまたは標準）")

    if errors:
        print(f"\n  ※ 取得エラー: {len(errors)}件")

    print()


if __name__ == "__main__":
    main()
