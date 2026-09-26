"""
当日レースのペース予測（2026-09-26・表示専用）

`analyze/pace_model.py` の検証結果をそのまま実運用に移したもの。
  ペース = 前半3F − 後半3F（マイナスほど前傾＝前半が速い）
  出走各馬の「前に行く度合い」（過去5走の1角位置÷頭数）を集計し、頭数・距離・芝ダから予測する。
  学習期間（〜2025/06）で決めた係数を固定で使う。テスト期間の相関 r=0.605／誤差1.66秒。

注意: 順位づけには使わない。検証（analyze/pace_fit_test.py）で、
  予測ペースと脚質の相性は着順の残差を説明しなかった（係数 -0.014±0.013・符号も仮説と逆）。
  「どのペースでも先行有利、後傾だとさらに前が止まらない」が実態で、前傾でも差しは届きにくい。
  そのため表示のみに留める。
"""
import json, os, re
from collections import defaultdict
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
FULL = BASE / "cache" / "horse_full_history"
VENUES = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]

# analyze/pace_model.py が学習期間で推定した係数（2026-09-26時点）
COEF = {"n_front": -0.034, "front_min": 0.517, "front_top2": -0.975, "front_mean": 2.629,
        "field": -0.165, "dist_z": -0.002, "is_turf": 2.949, "const": -1.585}
_STYLE_CACHE = {}


def enabled() -> bool:
    return os.environ.get("PACE_FORECAST", "1") != "0"


def style_of(horse_id: str, as_of, k: int = 5):
    """過去k走の「1角位置÷頭数」の平均（0=先頭 1=最後方）。データがなければ None"""
    if not horse_id:
        return None
    key = (horse_id, str(as_of))
    if key in _STYLE_CACHE:
        return _STYLE_CACHE[key]
    p = FULL / f"{horse_id}.json"
    if not p.exists():
        _STYLE_CACHE[key] = None
        return None
    try:
        recs = json.loads(p.read_text())
    except Exception:
        _STYLE_CACHE[key] = None
        return None
    cut = re.search(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})", str(as_of))
    cut = (int(cut.group(1)), int(cut.group(2)), int(cut.group(3))) if cut else None
    vals = []
    for r in recs:                                   # 新しい順
        d = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
        if not d:
            continue
        if cut and (int(d.group(1)), int(d.group(2)), int(d.group(3))) >= cut:
            continue
        corner = re.findall(r"\d+", r.get("corner", "") or "")
        try:
            field = int(r.get("field") or 0)
        except ValueError:
            continue
        if corner and field >= 5:
            vals.append((int(corner[0]) - 1) / (field - 1))
        if len(vals) >= k:
            break
    out = float(np.mean(vals)) if vals else None
    _STYLE_CACHE[key] = out
    return out


def forecast(entries, horse_ids: dict, surface: str, dist: int, race_date):
    """
    戻り値: {"pace": 予測の前後半差(秒), "label": 前傾/やや前傾/平均/やや後傾/後傾,
             "styles": {馬名: 前に行く度合い}, "n_style": 使えた頭数}
    """
    styles = {}
    for e in entries:
        s = style_of(horse_ids.get(e.horse_name, ""), race_date)
        if s is not None:
            styles[e.horse_name] = s
    st = np.array(list(styles.values()))
    if len(st) < 4:
        return None
    x = {"n_front": float((st <= 0.20).sum()), "front_min": float(st.min()),
         "front_top2": float(np.sort(st)[:2].mean()), "front_mean": float(st.mean()),
         "field": float(len(entries)), "dist_z": (dist - 1800) / 400,
         "is_turf": 1.0 if surface == "芝" else 0.0}
    pace = COEF["const"] + sum(COEF[k] * v for k, v in x.items())
    # 全レースの平均は -1.0秒、標準偏差 2.7秒。そこからの離れ具合で言葉にする
    z = (pace - (-1.0)) / 2.7
    label = ("前傾（前半が速い）" if z <= -0.7 else "やや前傾" if z <= -0.25 else
             "平均的" if z < 0.25 else "やや後傾" if z < 0.7 else "後傾（前半が遅い）")
    return {"pace": float(pace), "label": label, "styles": styles, "n_style": len(st),
            "n_front": int(x["n_front"])}


def comment_lines(fc: dict, sorted_results) -> list[str]:
    """CSVの評価コメントに出す行"""
    if not fc:
        return []
    order = sorted(fc["styles"].items(), key=lambda kv: kv[1])
    names = {e.horse_name: e.horse_number for e, _ in sorted_results}
    front = " / ".join(f"{names.get(n, '?')}番{n}" for n, _ in order[:3])
    back = " / ".join(f"{names.get(n, '?')}番{n}" for n, _ in order[-3:][::-1])
    return [f"【ペース想定】{fc['label']}（前後半差 {fc['pace']:+.1f}秒の想定・前に行くタイプ{fc['n_front']}頭）"
            f" ※展開の目安であり順位づけには使っていません（検証で着順への上乗せなし）",
            f"　　前に行きそう: {front}",
            f"　　後方から: {back}"]
