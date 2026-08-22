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
from jra_scraper import build_jra_url, get_entry_list as get_entry_list_jra, fetch_track_condition, JraParamError
from hli_calculator import calculate_hli
import trio_formation


def _fetch_training(race_id: str) -> dict:
    """netkeiba oikiri から全頭の調教評価を取得して {馬名: TrainingData} を返す。失敗時は {}。"""
    try:
        result = fetch_training_data(race_id)
        return result or {}
    except Exception:
        return {}


def _cached_odds_map(race_id: str) -> dict:
    """race_resultキャッシュの終値オッズを {馬名: odds} で返す（過去日の再現予想用フォールバック）。
    終値は発走前の市場評価そのもので、バックテストのオッズ利用と同一。着順は参照しない。"""
    from cache_store import cache_get
    d = cache_get("race_result", race_id)
    if not d:
        return {}
    return {e.get("horse_name"): e.get("odds", 0)
            for e in d.get("entries", []) if e.get("horse_name") and e.get("odds")}


_jra_param_error_warned = False  # 同一実行中に何度も警告しない


def _fetch_jra_odds(race_id: str, race_date: datetime.date, entries) -> tuple[dict, str]:
    """JRA公式出馬表から単勝オッズと馬場状態を取得。({馬名: float}, 馬場状態) を返す。失敗時は ({}, "")。"""
    global _jra_param_error_warned
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
        # 馬場状態: 出馬表ページに当日の最新値が含まれる（優先）
        # /keiba/baba/ は「前日正午現在」の古い情報のため使わない
        track_condition = jra_race_info.track_condition if jra_race_info else ""
        if track_condition:
            surf_label = "芝" if (jra_race_info and jra_race_info.surface in ("芝", "障")) else "ダート"
            print(f"  [馬場] {jra_race_info.venue} {surf_label}: {track_condition}（JRA 出馬表）")
        return odds_map, track_condition
    except JraParamError:
        if not _jra_param_error_warned:
            _jra_param_error_warned = True
            print(f"  ⚠ [JRA] パラメータエラー検出 — チェックサム式が変更された可能性があります")
            print(f"         今すぐ修正: python3 tools/jra_checksum_diag.py --fix")
        return {}, ""
    except Exception as e:
        print(f"  [_fetch_jra_odds エラー] {e}")
        return {}, ""

# ── 事前確認チェック ──────────────────────────────────────────────────────

def pre_output_check(sorted_results, odds_map, race_class, n_horses, race_name) -> list[str]:
    """出力前の品質チェック。問題があれば警告メッセージリストを返す"""
    warnings = []
    if not odds_map:
        warnings.append(f"⚠ オッズ未取得: {race_name} — 買いサイン判定でオッズを使用できません")
    else:
        missing = [e.horse_name for e, _ in sorted_results if e.horse_name not in odds_map]
        if missing:
            warnings.append(f"⚠ オッズ欠損馬: {', '.join(missing[:5])}")
    if race_class == 0:
        warnings.append(f"⚠ クラス判定不明: {race_name} — race_class=0")
    if n_horses == 0:
        warnings.append(f"⚠ 頭数0: {race_name}")
    return warnings


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
            lines.append(f"乖離{gap:.1f}pt：このゾーン（3〜5pt）はバックテストROI69%のため見送り。")
        if any("18頭" in r for r in reasons):
            lines.append("18頭フルゲートは荒れやすく軸信頼度が低下。")
        if any("ROI47%" in r for r in reasons):
            lines.append(f"2勝クラス以下：全オッズ帯でROI47%以下。3勝クラス以上のみ買い。")
        elif any("ROI6%" in r for r in reasons):
            lines.append(f"重賞クラス：三連複ROI6%以下（n=92）。買い条件を満たさない。")

        if odds2 and odds2 >= 20:
            lines.append(f"2位{sec_entry.horse_name}{odds2:.1f}倍：相手を絞り込みにくく三連複の期待値も低い。")
        elif odds2:
            lines.append(f"2位{sec_entry.horse_name}{odds2:.1f}倍（スコア差{gap:.1f}pt）。")

    elif sign_level == "tierce":
        lines.append(f"3勝クラス×{odds1:.1f}倍：三連単A+Bフォーメーション推奨（ROI241%・ヒット率24%）。")
        lines.append(f"[A] {top_entry.horse_name}（1着固定）× 紐4頭（2-3着）12点")
        lines.append(f"[B] 紐4頭（1着）× {top_entry.horse_name}（2着固定）× 紐4頭（3着）12点")

    elif sign_level == "trio_axis":
        # 全クラス共通: 1軸(予想1位)-相手 の三連複（相手幅は trio_formation で管理）
        start, end = trio_formation.relay_range(race_class)
        pts = trio_formation.point_count(race_class)
        form = f"三連複1軸-相手{end - start + 1}頭({pts}点)"
        if odds1 and odds1 < 2:
            lines.append(f"断然人気{odds1:.1f}倍：予想1位の複勝率が高く軸信頼度大。{form}で相手を広くカバー。")
        if gap < 1:
            lines.append(f"上位横並び（乖離{gap:.1f}pt）。1位を軸に固定し{form}で相手をカバー。")
        elif 14 <= n_horses <= 17:
            lines.append(f"{n_horses}頭立て。{form}でカバレッジを確保。")
        if odds1 and odds1 >= 10 and race_class >= 3:
            lines.append(f"軸{odds1:.1f}倍(高配当帯)：当たれば妙味大だが軸が飛ぶと全外れのため妙味重視の一番。")
        if not lines:
            lines.append(f"乖離{gap:.1f}pt・{n_horses}頭。予想1位を軸に{form}推奨（5頭BOXを的中率・ROIとも上回る型）。")

    return lines


def calc_buy_sign(sorted_results, odds_map, n_horses, race_class=0, surface=""):
    """
    Returns: (sign_level, sign_text, detail_text)
      sign_level: "tierce" / "trio_axis" / "skip" / "neutral"
      race_class: 0=未勝利 1=1勝 2=2勝 3=3勝 4=OP 5=GIII 6=GII 7=GI
      surface: "芝" / "ダ"（3勝クラスの買い目分岐に使用。2026-07-12〜）
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
        skips.append(f"{cls_name}（三連複ROI6%以下・n=92）")

    if skips:
        return "skip", "⚠ 見送り", " / ".join(skips)

    # 三連単 A+B フォーメーション: 3勝クラス × 2〜4.9倍（ROI241%・ヒット率24%）
    if race_class == 3 and odds1 and 2 <= odds1 < 5:
        detail = f"3勝クラス×{odds1:.1f}倍 / 乖離{gap:.1f}pt {n}頭 / A+B 24点"
        return "tierce", "🏇 三連単A+B推奨", detail

    # 買い目: 全クラス「1軸(予想1位)-相手」の三連複フォーメーションに一本化（2026-08-02）。
    # 相手幅は trio_formation.TRIO_RELAY で一元管理（デフォルト相手2〜6位=10点）。
    # 経緯: クラス別に box4/box4axis/box5 と分岐していたが、予想順位別複勝率が
    #   1位49%>2位42%>3位35%… と単調で1位が最も信頼できる軸と判明。2軸型は不安定な
    #   予想2位を必須にするため夏に弱く、1軸-相手2〜6位(10点)が5頭BOXを的中率・ROI
    #   両面で上回った（全期間n=688: 18.5%/115.4% vs 17.9%/108.8%）。
    # ※ 乖離≥5ptの高信頼7点推奨は廃止（バックテスト: 単勝ROI50%・5BOX ROI40%）
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

    return "trio_axis", f"三連複{trio_formation.label(race_class)}", detail


# ── クラス判定 ─────────────────────────────────────────────────────────

def race_class_from_conditions(conditions: str, race_name: str) -> int:
    return parse_race_class(conditions + " " + race_name)


# ── メイン ─────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sat",       action="store_true", help="土曜のみ")
    parser.add_argument("--sun",       action="store_true", help="日曜のみ")
    parser.add_argument("--all-class", action="store_true", help="全クラス（デフォルト: 2勝以上）")
    parser.add_argument("--venue",     default="",          help="会場絞り込み（例: 東京）")
    parser.add_argument("--min-class", type=int, default=2, help="最低クラス（0=未勝利 2=2勝 4=OP）")
    parser.add_argument("--dates",     default="",
                        help="対象日を明示指定（YYYY-MM-DD,...）。過去日の再現予想用。指定時は当日オッズ取得失敗時にrace_resultキャッシュの終値へフォールバック")
    parser.add_argument("--track",     default="",
                        help="馬場状態（例: 良 / 稍重 / 重 / 不良 / 東京:良,阪神:稍重）")
    args = parser.parse_args(argv)

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

    if args.dates:
        dates = [datetime.date.fromisoformat(d.strip()) for d in args.dates.split(",") if d.strip()]
    elif args.sat:
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

        # 障害戦スキップ（フラット用採点ロジックの対象外。surfaceが空で道悪/コース補正も効かない）
        if "障害" in (race_info.conditions or "") or "障害" in race_info.name \
                or race_info.name.endswith("JS") or race_info.surface not in ("芝", "ダ"):
            print(f"  → スキップ（障害戦）")
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

        # オッズ取得: JRA公式出馬表（第1優先）→ netkeiba API（フォールバック）
        race_date = race.get("date")
        odds_map = {}
        jra_track = ""
        if race_date:
            jra_odds_map, jra_track = _fetch_jra_odds(race_id, race_date, entries)
            if jra_odds_map:
                odds_map = jra_odds_map
                print(f"  [オッズ] JRA公式から{len(odds_map)}頭取得")
        if not odds_map:
            odds_raw = fetch_odds(race_id)
            if odds_raw:
                num_to_name = {str(e.horse_number): e.horse_name for e in entries}
                odds_map = {num_to_name[k]: v for k, v in odds_raw.items() if k in num_to_name}
                if odds_map:
                    print(f"  [オッズ] netkeiba APIから{len(odds_map)}頭取得")
        if not odds_map and args.dates:
            # 過去日の再現予想: 当日オッズが取れないためrace_resultキャッシュの終値を使う
            odds_map = _cached_odds_map(race_id)
            if odds_map:
                print(f"  [オッズ] race_resultキャッシュ終値から{len(odds_map)}頭取得（再現予想）")
        if not odds_map:
            print(f"  [オッズ] 取得失敗（発走後またはAPI不応答）")

        # 馬場状態: --track引数 > JRA公式 > netkeiba shutuba > (再現予想時)race_resultキャッシュ
        auto_tc = jra_track or race_info.track_condition
        if not auto_tc and args.dates:
            from cache_store import cache_get
            _d = cache_get("race_result", race_id)
            if _d:
                auto_tc = _d.get("track_condition", "")
        tc = get_track(race_info.venue, auto_tc)
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

        # HLI B案補正（2年制限・クラス別係数）
        # 3勝クラス=補正なし / OP=0.10 / G3=0.05 / G2=0.05 / G1=補正なし
        _HLI_K = {4: 0.10, 5: 0.05, 6: 0.05}
        _k = _HLI_K.get(race_class, 0.0)
        if _k > 0 and horse_ids and race_date:
            _cutoff = race_date.strftime('%Y/%m/%d')
            _hli = {}
            for _e in entries:
                if _e.horse_id:
                    _age = int(_e.age_sex[1]) if len(_e.age_sex) >= 2 and _e.age_sex[1].isdigit() else 4
                    _hli[_e.horse_name] = calculate_hli(
                        _e.horse_id, _e.horse_name, _age,
                        cutoff_date=_cutoff, lookback_years=2
                    ).total
            if _hli:
                _avg = sum(_hli.values()) / len(_hli)
                sorted_r = sorted(results,
                    key=lambda x: x[1].total + (_hli.get(x[0].horse_name, _avg) - _avg) * _k,
                    reverse=True)
            else:
                sorted_r = sorted(results, key=lambda x: x[1].total, reverse=True)
        else:
            sorted_r = sorted(results, key=lambda x: x[1].total, reverse=True)

        # サイン判定
        sign_level, sign_text, sign_detail = calc_buy_sign(sorted_r, odds_map, n, race_class, race_info.surface)

        # 事前確認チェック
        check_warns = pre_output_check(sorted_r, odds_map, race_class, n, race_info.name)
        for w in check_warns:
            print(f"  {w}")

        # 評価コメント生成
        eval_comment = gen_eval_comment(sorted_r, odds_map, n, sign_level, sign_detail, race_class)

        # ファイル名タグ（買いサインのみ付与）
        if sign_level == "tierce":
            sign_tag = "★三連単A+B"
        elif sign_level == "trio_axis":
            sign_tag = "★三連複1軸相手"
        else:
            sign_tag = None

        # CSV出力
        try:
            if race_info.surface == "ダ":
                save_csv_dart(sorted_r, race_info, odds_map=odds_map, training_data=training,
                              sign_tag=sign_tag, eval_comment=eval_comment, race_id=race_id,
                              sign_level=sign_text, sign_detail_text=sign_detail, race_class=race_class,
                              track_condition=tc)
            else:
                save_csv_turf(sorted_r, race_info, odds_map=odds_map, training_data=training,
                              sign_tag=sign_tag, eval_comment=eval_comment, race_id=race_id,
                              sign_level=sign_text, sign_detail_text=sign_detail, race_class=race_class,
                              track_condition=tc)
        except Exception as e:
            print(f"  [CSV] 保存失敗: {e}")

        # 上位3頭を表示
        top3 = sorted_r[:3]
        for rank, (entry, d) in enumerate(top3, 1):
            o = odds_map.get(entry.horse_name)
            odds_str = f" {o:.1f}倍" if o else ""
            print(f"  {rank}位 {entry.horse_number}番 {entry.horse_name:<12} {d.total:+.1f}pt{odds_str}")

        print(f"  → {sign_text}  {sign_detail}")

        if sign_level in ("tierce", "trio_axis"):
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
                "surface":    race_info.surface,
                "n":          n,
                "sign":       sign_text,
                "detail":     sign_detail,
                "top1":       horse_label(0),
                "top2":       horse_label(1),
                "top3":       horse_label(2),
                "top4":       horse_label(3),
                "top5":       horse_label(4),
                "top6":       horse_label(5),
                "top7":       horse_label(6),
                "top8":       horse_label(7),
                "level":      sign_level,
                "race_class": race_class,
            })

    # ── 買いサインまとめ ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  買いサインまとめ  ({len(sign_summary)}件)")
    print(f"{'='*65}")

    tierces    = [s for s in sign_summary if s["level"] == "tierce"]
    trios      = [s for s in sign_summary if s["level"] == "trio_axis"]

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

    if trios:
        # 相手幅は trio_formation.TRIO_RELAY で決まる（クラス別に変わりうるので各行で算出）
        print("\n三連複 1軸-相手 フォーメーション ── 全クラス共通")
        for s in trios:
            rc = s.get("race_class", 0)
            start, end = trio_formation.relay_range(rc)
            axis = s["top1"]
            himo = "・".join(h for h in [s.get(f"top{i}","") for i in range(2, end + 1)] if h)
            print(f"  {s['date']} {s['venue']} {s['name']}  {s['dist']}  {s['n']}頭")
            print(f"  軸: {axis} → 相手(予想{start}〜{end}位): {himo}  {trio_formation.point_count(rc)}点")
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
