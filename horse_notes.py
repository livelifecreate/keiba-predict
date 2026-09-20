"""
出走馬ごとの「強み・弱み」コメント自動生成（2026-09-20）

予想の壁打ちで毎回確認していた観点をルール化して、予想CSV / Streamlit に出す。採点には使わない（表示のみ）。
  能力指数の位置づけ / 距離経験 / コース実績 / 道悪成績 / 重賞実績・格 / 前走 / 休み明け / 調教コメントの実績 /
  堅実さ / 人気と総合点のズレ / 斤量

データ: 通算成績は cache/horse_full_history/{馬ID}.json（fetch_full_career.py と同じ形式）。
  無い・古い（出馬表の直近走より前で止まっている）馬だけ netkeiba から1回取得して保存する。
  通信制限（空応答）が3頭続いたらその実行中は取得をやめ、手元にある情報だけでコメントを作る。
  環境変数 HORSE_NOTES=0 で無効化。
"""
import json, os, re, statistics
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
FULL_DIR = BASE / "cache" / "horse_full_history"
WET = ("稍", "重", "不", "稍重", "不良")
_fail_streak = 0
_fetch_disabled = False


def enabled() -> bool:
    return os.environ.get("HORSE_NOTES", "1") != "0"


# ------------------------------------------------------------------ 通算成績
def _d(s: str):
    m = re.search(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})", s or "")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def career(horse_id: str, latest_run) -> list[dict]:
    """通算成績（新しい順）。キャッシュが出馬表の直近走より古ければ取り直す"""
    global _fail_streak, _fetch_disabled
    if not horse_id:
        return []
    p = FULL_DIR / f"{horse_id}.json"
    recs = []
    if p.exists():
        try:
            recs = json.loads(p.read_text())
        except Exception:
            recs = []
    newest = _d(recs[0]["date_raw"]) if recs else None
    if recs and (latest_run is None or (newest and newest >= latest_run)):
        return recs
    if _fetch_disabled:
        return recs
    try:
        from fetch_missing_history import fetch_full_history
        new = fetch_full_history(horse_id)
    except Exception:
        new = []
    if not new:
        _fail_streak += 1
        if _fail_streak >= 3:
            _fetch_disabled = True
            print("  [強み弱み] 通算成績が3頭連続で取得できず（通信制限の可能性）→ この実行では取得を中止")
        return recs
    _fail_streak = 0
    FULL_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(new, ensure_ascii=False))
    return new


def _level(race_raw: str) -> int:
    s = race_raw or ""
    if re.search(r"\((GI|G1|JpnI)\)", s): return 7
    if re.search(r"\((GII|G2|JpnII)\)", s): return 6
    if re.search(r"\((GIII|G3|JpnIII)\)", s): return 5
    if re.search(r"\((L|OP)\)", s) or "オープン" in s: return 4
    if "3勝" in s or "1600万" in s: return 3
    if "2勝" in s or "1000万" in s: return 2
    if "1勝" in s or "500万" in s: return 1
    return 0


def _pos(r):
    return int(r["pos_raw"]) if str(r.get("pos_raw", "")).isdigit() else None


def _stat(rs):
    ps = [p for p in (_pos(r) for r in rs) if p]
    return len(ps), sum(p == 1 for p in ps), sum(p <= 3 for p in ps)


def _short(race_raw: str) -> str:
    return re.sub(r"^(関西TV|東海テレビ杯|日刊スポ賞|産経賞|農林水産省賞典|読売|KBS|HTB|TV|UHB|STV)", "", race_raw or "")


def running_style(recs: list[dict], surface: str) -> str:
    """近5走（同じ芝ダ・平地）の通過順から脚質を判定。最初のコーナーの位置÷頭数の平均で分類"""
    ratios, firsts = [], []
    for r in recs:
        if not r.get("dist_raw", "").startswith(surface):
            continue
        c = re.findall(r"\d+", r.get("corner", "") or "")
        f = str(r.get("field", ""))
        if not c or not f.isdigit() or int(f) < 5:
            continue
        ratios.append((int(c[0]) - 1) / (int(f) - 1))
        firsts.append(int(c[0]))
        if len(ratios) == 5:
            break
    if len(ratios) < 2:
        return ""
    m = sum(ratios) / len(ratios)
    lead = sum(1 for x in firsts if x == 1)
    if lead >= 2 or m <= 0.08:
        name = "逃げ"
    elif m <= 0.33:
        name = "先行"
    elif m <= 0.66:
        name = "差し"
    else:
        name = "追込"
    return f"{name}（近{len(ratios)}走の序盤 平均{sum(firsts) / len(firsts):.1f}番手）"


# ------------------------------------------------------------------ コメント生成
def build(sorted_results, race_info, race_class: int, track_condition: str, odds_map: dict,
          training_data: dict, plan_d_info: dict | None, race_date) -> list[dict]:
    """[{num, name, strengths:[...], weaknesses:[...]}, ...] を予想順位順で返す"""
    surface = "芝" if race_info.surface == "芝" else "ダ"
    m = re.search(r"(\d+)", str(race_info.distance))
    dist = int(m.group(1)) if m else 0
    venue = race_info.venue
    wet_today = bool(track_condition) and track_condition != "良"
    pops = {}
    if odds_map:
        for k, (nm, _) in enumerate(sorted(odds_map.items(), key=lambda x: x[1]), 1):
            pops[nm] = k
    n = len(sorted_results)
    dev_order = []
    if plan_d_info:
        dev_order = sorted([nm for nm, r in plan_d_info.items() if r["dev"] is not None], key=lambda nm: -plan_d_info[nm]["dev"])
    weights = []
    for e, _ in sorted_results:
        try:
            weights.append(float(e.weight_carried))
        except (TypeError, ValueError):
            weights.append(None)
    wmax = max([w for w in weights if w is not None], default=None)

    out = []
    for rank, ((e, d), w) in enumerate(zip(sorted_results, weights), 1):
        S, W = [], []
        latest = _d(e.recent_races[0]) if e.recent_races else None
        recs = [r for r in career(getattr(e, "horse_id", ""), latest) if (_d(r["date_raw"]) or date.min) < race_date]
        turf = [r for r in recs if r.get("dist_raw", "").startswith(surface)]

        # 1. 能力指数
        if plan_d_info:
            r = plan_d_info[e.horse_name]
            if r["dev"] is None:
                W.append("能力指数なし（対戦データ不足）")
            else:
                k = dev_order.index(e.horse_name) + 1
                if k == 1 and len(dev_order) > 1:
                    gap = r["dev"] - plan_d_info[dev_order[1]]["dev"]
                    S.append(f"能力指数{r['dev']:.0f}はメンバー1位（2位に{gap:.0f}差）")
                elif k <= 3:
                    S.append(f"能力指数{r['dev']:.0f}（メンバー{k}位）")
                elif k > len(dev_order) * 2 / 3:
                    W.append(f"能力指数{r['dev']:.0f}はメンバー下位（{k}位/{len(dev_order)}頭）")

        if recs:
            # 2. 距離
            ds = [int(x.group(1)) for x in (re.search(r"(\d+)", r["dist_raw"]) for r in turf) if x]
            same = [r for r in turf if abs(int(re.search(r"(\d+)", r["dist_raw"]).group(1)) - dist) <= 100]
            c, wn, t3 = _stat(same)
            if c == 0 and ds:
                if max(ds) < dist - 100:
                    W.append(f"{dist}mは未経験（最長{max(ds)}m）")
                elif min(ds) > dist + 100:
                    W.append(f"{dist}mは未経験（最短{min(ds)}m）")
            elif c >= 2 and t3 / c >= 0.5:
                S.append(f"{dist}m前後は{c}走{wn}勝・3着内{t3}回")
            elif c >= 3 and t3 == 0:
                W.append(f"{dist}m前後は{c}走して3着内なし")

            # 3. コース
            here = [r for r in turf if venue and venue in r.get("kaisan", "")]
            c, wn, t3 = _stat(here)
            same_course = [r for r in here if re.search(r"(\d+)", r["dist_raw"]) and int(re.search(r"(\d+)", r["dist_raw"]).group(1)) == dist]
            sc_best = min([p for p in (_pos(r) for r in same_course) if p], default=None)
            if sc_best and sc_best <= 3:
                best = min(same_course, key=lambda r: (_pos(r) or 99, -_level(r["race_raw"])))
                S.append(f"同コース（{venue}{surface}{dist}）で{_short(best['race_raw'])}{_pos(best)}着")
            elif c >= 2 and t3 / c >= 0.5:
                S.append(f"{venue}{surface}は{c}走{wn}勝・3着内{t3}回")
            if c == 0:
                W.append(f"{venue}{surface}は初めて")
            elif c >= 3 and t3 == 0:
                W.append(f"{venue}{surface}は{c}走して3着内なし")

            # 4. 道悪（当日が道悪のときだけ）
            if wet_today:
                wets = [r for r in turf if r.get("track") in WET]
                c, wn, t3 = _stat(wets)
                # 重賞の道悪で「3着内」または「人気より上の着順で5着内」だけを強みとして拾う
                graded = [r for r in wets if _level(r["race_raw"]) >= 5 and (_pos(r) or 99) <= 5
                          and ((_pos(r) or 99) <= 3 or (str(r.get("pop", "")).isdigit() and _pos(r) < int(r["pop"])))]
                if c == 0:
                    W.append("道悪は未経験")
                else:
                    if t3 / c >= 0.4:
                        S.append(f"道悪{c}走{wn}勝・3着内{t3}回")
                    elif t3 == 0 and c >= 2:
                        worst = max(wets, key=lambda r: _pos(r) or 0)
                        W.append(f"道悪{c}走で3着内なし（{_short(worst['race_raw'])}{_pos(worst)}着など）")
                    elif c == 1 and t3 == 0:
                        W.append(f"道悪は1走のみで{_pos(wets[0])}着")
                    elif t3 / c < 0.25:
                        W.append(f"道悪は{c}走で3着内{t3}回")
                    if graded:
                        g = max(graded, key=lambda r: (_level(r["race_raw"]), -(_pos(r) or 99)))
                        S.append(f"{g['track']}の{_short(g['race_raw'])}で{_pos(g)}着（{g.get('pop', '?')}番人気）")

            # 5. 格（OP以上のレース）
            if race_class >= 4:
                gr = [r for r in recs if _level(r["race_raw"]) >= 5]
                gt3 = [r for r in gr if (_pos(r) or 99) <= 3]
                if gt3:
                    b = max(gt3, key=lambda r: (_level(r["race_raw"]), -(_pos(r) or 99)))
                    S.append(f"重賞3着内{len(gt3)}回（{_short(b['race_raw'])}{_pos(b)}着など）")
                elif not gr and race_class >= 5:
                    W.append(f"重賞初挑戦（前走 {_short(recs[0]['race_raw'])}）")
                elif len(gr) >= 3:
                    W.append(f"重賞は{len(gr)}走して3着内なし")

            # 6. 前走
            last, lp = recs[0], _pos(recs[0])
            jumps = sum(1 for r in recs[:3] if r.get("dist_raw", "").startswith("障"))
            if jumps:
                W.append(f"近3走のうち{jumps}走が障害戦（平地は{next((r['date_raw'][:7] for r in recs if not r.get('dist_raw', '').startswith('障')), '?')}以来）")
            elif lp == 1:
                S.append(f"前走{_short(last['race_raw'])}1着")
            elif lp and lp <= 5 and _level(last["race_raw"]) >= 5:
                S.append(f"前走{_short(last['race_raw'])}{lp}着")
            elif lp and lp >= 10:
                W.append(f"前走{_short(last['race_raw'])}{lp}着（{last.get('margin', '')}秒差）")

            # 7. 休み明け（2勝クラス以上・芝14,736頭の集計: 4〜6か月は複勝率が人気比-1.6pt、半年以上は-3.9pt）
            ld = _d(last["date_raw"])
            if ld:
                days = (race_date - ld).days
                if days >= 180:
                    W.append(f"約{days // 30}か月ぶり（半年以上の休み明けは人気以下に走りやすい）")
                elif days >= 120:
                    W.append(f"約{days // 30}か月の休み明け")

            # 9. 堅実さ
            r8 = [p for p in (_pos(r) for r in recs[:8]) if p]
            if len(r8) >= 6 and 1 not in r8 and sum(p <= 5 for p in r8) >= 4:
                S.append(f"近{len(r8)}走で掲示板{sum(p <= 5 for p in r8)}回と堅実（ただし勝ち星なし）")
        else:
            W.append("通算成績を取得できず（距離・コース・道悪の評価なし）")

        # 8. 調教コメントの実績
        td = (training_data or {}).get(e.horse_name)
        if td and getattr(td, "comment", ""):
            try:
                from training_form import comment_stats_as_of
                h, c = comment_stats_as_of(td.comment, race_date.strftime("%Y/%m/%d"))
                if c >= 30:
                    rate = h / c * 100
                    if rate >= 30:
                        S.append(f"調教「{td.comment}」（同コメントの複勝率{rate:.0f}%）")
                    elif rate <= 16:
                        W.append(f"調教「{td.comment}」（同コメントの複勝率{rate:.0f}%）")
            except Exception:
                pass

        # 10. 人気とのズレ
        pop = pops.get(e.horse_name)
        if pop:
            if rank <= 3 and pop >= rank + 4:
                S.append(f"{pop}番人気だが総合点は{rank}位（人気より高評価）")
            elif pop <= 3 and rank >= pop + 4:
                W.append(f"{pop}番人気だが総合点は{rank}位")

        # 11. 斤量
        if w is not None and wmax is not None and w == wmax and sum(1 for x in weights if x == wmax) == 1:
            others = statistics.median([x for x in weights if x is not None])
            if w - others >= 1:
                W.append(f"斤量{w:g}kgは単独で最も重い")

        out.append({"num": e.horse_number, "name": e.horse_name, "strengths": S, "weaknesses": W,
                    "style": running_style(recs, surface) if recs else ""})
    return out


def csv_section(notes: list[dict]) -> list[list]:
    rows = [[], ["■強み弱み", "馬番", "馬名", "強み", "弱み", "脚質"]]
    for x in notes:
        rows.append(["", x["num"], x["name"], " ／ ".join(x["strengths"]) or "—", " ／ ".join(x["weaknesses"]) or "—",
                     x.get("style", "")])
    return rows
