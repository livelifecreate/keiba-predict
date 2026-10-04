"""
能力指数v3に着差を入れる検証（改善案⑤・2026-10-04）

v3 の走りの評価 y は「着順の標準化（正規分位）」だけで、5着0.1秒差と5着2秒差が同じ。
cache/race_margin（tools/fetch_race_margin.py で全出走馬の勝ち馬との秒差を取得）を使い、
  rank : 現行（着順のみ）
  mix  : 0.5×着順 + 0.5×秒差スコア（秒差は1600m換算・2.0秒で頭打ち、レース内で標準化）
を同じ手順（2パス・ウォークフォワード・テスト2025/07〜）で推定し、予測力を比べる。
着差の取れないレースは着順のみのまま。data/v3_eval.parquet は上書きしない。

判定: 「θのみ」「市場＋θ」の対数損失・予想1位の勝率/複勝率が、mix で明確に良くなれば採用候補
      （目安: θのみの対数損失 -0.01以下、または複勝率 +1pt 以上）。
使い方: python3 analyze/ability_margin_test.py
"""
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import ability_index_v3 as V

BASE = Path(__file__).resolve().parent.parent
MARGIN_DIR = BASE / "cache" / "race_margin"


def load_margins():
    out = {}
    for p in MARGIN_DIR.glob("*.json"):
        d = json.loads(p.read_text())
        out[d["race_id"]] = {e["horse_id"]: e.get("margin") for e in d["entries"] if e.get("horse_id")}
    return out


def apply_margin(obs, rr, margins, alpha):
    """obs["y"] を 着順(1-alpha) + 秒差(alpha) の混合に置き換える（着差の無いレースは着順のみ）"""
    if alpha == 0:
        return 0.0
    y = obs["y"].copy()
    by_race = {}
    for k, (ri, e) in enumerate(obs["meta"]):
        by_race.setdefault(ri, []).append((k, e))
    covered = 0
    for ri, items in by_race.items():
        m = margins.get(rr[ri]["rid"])
        if not m:
            continue
        vals = [m.get(e["horse_id"]) for _, e in items]
        if sum(v is not None for v in vals) < len(items) * 0.8:
            continue
        scale = 1600.0 / max(rr[ri]["dist"], 1000)
        s = np.array([-(min(v, 2.0) * scale) if v is not None else np.nan for v in vals], dtype=float)
        s = np.where(np.isnan(s), np.nanmin(s), s)
        sd = s.std()
        if sd < 1e-6:
            continue
        z = (s - s.mean()) / sd
        idx = [k for k, _ in items]
        y[idx] = (1 - alpha) * obs["y"][idx] + alpha * z
        covered += 1
    obs["y"] = y
    return covered / max(len(by_race), 1)


def run(alpha, races, prevs, going, sires, margins):
    rows = []
    for surface in ("芝", "ダ"):
        obs0, hmap, jmap, rr = V.build(races, surface, prevs)
        cov = apply_margin(obs0, rr, margins, alpha)
        byday0, _ = V.walk_forward(obs0, hmap, jmap, rr)
        obs, hmap, jmap, rr = V.build(races, surface, prevs, going, sires, byday0)
        apply_margin(obs, rr, margins, alpha)
        byday, _ = V.walk_forward(obs, hmap, jmap, rr)
        print(f"  [{surface}] 着差を使えたレース {cov:.0%}")
        for k, (ri, e) in enumerate(obs["meta"]):
            r = rr[ri]
            if r["dt"] not in byday or r["cls"] == "新馬" or not e.get("odds"):
                continue
            theta, W, a, beta = byday[r["dt"]]
            j = hmap[e["horse_id"]]
            rows.append({"rid": r["rid"], "dt": r["dt"], "cls": r["cls"], "rank": e["rank"], "odds": e["odds"],
                         "v3": theta[j] if W[j] > 0 else np.nan})
    df = pd.DataFrame(rows)
    df = df[df.groupby("rid")["v3"].transform(lambda s: s.notna().mean()) >= 0.6].copy()
    m = df.groupby("rid")["v3"].transform("mean")
    df["v3_c"] = (df["v3"].fillna(m) - m).fillna(0.0)
    imp = 1.0 / df["odds"]
    df["log_mkt"] = np.log(imp / imp.groupby(df["rid"]).transform("sum"))
    return df


def main():
    races = A.load_races()
    prevs, going, sires = V.prev_map(), V.going_map(races), V.sire_map()
    margins = load_margins()
    print(f"着差データ {len(margins)}R / race_result {len(races)}R")
    res = {}
    for alpha, lab in ((0.0, "rank（現行・着順のみ）"), (0.5, "mix（着順0.5＋秒差0.5）")):
        print(f"\n===== {lab} =====")
        df = run(alpha, races, prevs, going, sires, margins)
        for scope, d in (("全クラス", df), ("2勝以上", df[df.cls.isin(["2勝クラス", "3勝クラス", "OP", "重賞"])])):
            for cols, cl in ((["v3_c"], "θのみ"), (["log_mkt", "v3_c"], "市場＋θ")):
                r = V._eval(d, cols, cl)
                res[(lab, scope, cl)] = r
                print(f"  {scope:<5} {cl:<5} n={r['n']} 対数損失={r['logloss']:.4f} 予想1位 勝率{r['win']:.1%} 複勝率{r['place']:.1%} 単勝ROI{r['roi']:.0%} 重み{r['w']}")
    print("\n===== 差（mix − rank）=====")
    for scope in ("全クラス", "2勝以上"):
        for cl in ("θのみ", "市場＋θ"):
            a, b = res[("rank（現行・着順のみ）", scope, cl)], res[("mix（着順0.5＋秒差0.5）", scope, cl)]
            print(f"  {scope:<5} {cl:<5} 対数損失 {b['logloss'] - a['logloss']:+.4f} / 勝率 {(b['win'] - a['win']) * 100:+.1f}pt / 複勝率 {(b['place'] - a['place']) * 100:+.1f}pt")


if __name__ == "__main__":
    main()
