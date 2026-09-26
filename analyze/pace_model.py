"""
ペース予測モデル（2026-09-26）

やること:
  ① 各馬の「前に行く度合い」を通算成績の通過順から数値化する（脚質スコア）
  ② レースのペース（前半3F − 後半3F）を、出走馬の脚質構成・頭数・距離・コース・クラスから予測する
  ③ 予測ペースと各馬の脚質の相性（前傾なら差し有利 / 後傾なら先行有利）が着順を説明するか検証する

データ: cache/horse_full_history（ペース92% / 通過順99%）。レース日より前の走のみ使う（先読みなし）。
  ペース表記 "35.5-34.8" は 前半3F-後半3F（netkeiba）。値が小さいほど前半が速い＝前傾。

検証の作法（これまでの反省を踏まえる）:
  - 学習期間（〜2025/06）でモデルを作り、テスト期間（2025/07〜）で評価する
  - ③は「乖離方式」: 能力指数v3で説明できる分を引いた残差に対して、相性が効くかを見る
使い方: python3 analyze/pace_model.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import market_residual_model as M

FULL = BASE / "cache" / "horse_full_history"
ND = NormalDist()
TRAIN_END = pd.Timestamp(2025, 7, 1)
VENUES = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]


def load_runs() -> pd.DataFrame:
    """通算成績を1走=1行に展開（日付・レース識別・通過順・ペース・着順）"""
    rows = []
    for p in FULL.glob("*.json"):
        try:
            recs = json.loads(p.read_text())
        except Exception:
            continue
        hid = p.stem
        for r in recs:
            d = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
            dm = re.match(r"^(芝|ダ)(\d+)", r.get("dist_raw", ""))
            if not d or not dm:
                continue
            venue = next((v for v in VENUES if v in (r.get("kaisan") or "")), None)
            if not venue:
                continue
            corner = [int(x) for x in re.findall(r"\d+", r.get("corner", "") or "")]
            pm = re.match(r"^([\d.]+)-([\d.]+)$", (r.get("pace") or "").strip())
            try:
                field = int(r.get("field") or 0)
                pos = int(r["pos_raw"])
            except (ValueError, TypeError):
                continue
            if field < 5 or pos < 1:
                continue
            rows.append({
                "hid": hid, "dt": pd.Timestamp(int(d.group(1)), int(d.group(2)), int(d.group(3))),
                "venue": venue, "surface": dm.group(1), "dist": int(dm.group(2)),
                "race": re.sub(r"\s", "", r.get("race_raw", ""))[:12], "field": field, "pos": pos,
                "first_corner": corner[0] if corner else np.nan,
                "pace_first": float(pm.group(1)) if pm else np.nan,
                "pace_last": float(pm.group(2)) if pm else np.nan,
            })
    return pd.DataFrame(rows)


def main():
    runs = load_runs()
    # レース名は通算成績と race_result で表記が違う（"〇〇T(GIII)" vs "〇〇T"）ため、
    # 日付・場・芝ダ・距離・頭数で突合する。同一日・同一場で同条件・同頭数が重なる確率は低い。
    runs["rid"] = (runs["dt"].astype(str) + "_" + runs["venue"] + "_" + runs["surface"]
                   + runs["dist"].astype(str) + "_" + runs["field"].astype(str))
    print(f"通算成績: {len(runs):,}走 / {runs.hid.nunique():,}頭 / レース{runs.rid.nunique():,}")

    # ---------------- ① 脚質スコア（前に行く度合い）: 1角の位置を頭数で正規化。0=最内先頭 1=最後方
    runs["pos_rate"] = (runs["first_corner"] - 1) / (runs["field"] - 1)
    runs = runs.sort_values("dt")

    # ---------------- ② レース単位のペース（実測）
    races = runs.dropna(subset=["pace_first", "pace_last"]).groupby("rid").agg(
        dt=("dt", "first"), venue=("venue", "first"), surface=("surface", "first"), dist=("dist", "first"),
        field=("field", "first"), pf=("pace_first", "median"), pl=("pace_last", "median"), n_obs=("hid", "size")).reset_index()
    races["pace_gap"] = races["pf"] - races["pl"]          # マイナス=前傾（前半が速い）
    print(f"ペース実測のあるレース: {len(races):,}  前後半差の平均{races.pace_gap.mean():+.2f}秒 / 標準偏差{races.pace_gap.std():.2f}")
    print("  参考: 前傾（前半が速い）ほど差しが決まりやすいとされる")

    # 各レースの出走馬（通過順が取れた馬）と、その馬の「過去の脚質」
    hist = defaultdict(list)                                # hid -> [(dt, pos_rate)]
    for r in runs.dropna(subset=["pos_rate"]).itertuples():
        hist[r.hid].append((r.dt, r.pos_rate))

    def style_before(hid, dt, k=5):
        v = [p for d, p in hist.get(hid, []) if d < dt]
        return float(np.mean(v[-k:])) if v else np.nan

    feats = []
    members = runs.groupby("rid")
    for r in races.itertuples():
        g = members.get_group(r.rid)
        st = np.array([style_before(h, r.dt) for h in g.hid], dtype=float)
        st = st[~np.isnan(st)]
        if len(st) < 4:
            continue
        feats.append({"rid": r.rid, "dt": r.dt, "venue": r.venue, "surface": r.surface, "dist": r.dist,
                      "field": r.field, "pace_gap": r.pace_gap, "n_style": len(st),
                      "front_min": st.min(), "front_mean": st.mean(),
                      "n_front": int((st <= 0.20).sum()),          # 逃げ・先行タイプの数
                      "n_front2": int((st <= 0.35).sum()),
                      "front_top2": float(np.sort(st)[:2].mean())})
    f = pd.DataFrame(feats)
    print(f"脚質が4頭以上そろったレース: {len(f):,}")

    # ---------------- ペース予測モデル（学習期間で係数を決め、テスト期間で当てる）
    f["is_turf"] = (f.surface == "芝").astype(float)
    f["dist_z"] = (f.dist - 1800) / 400
    cols = ["n_front", "front_min", "front_top2", "front_mean", "field", "dist_z", "is_turf"]
    tr, te = f[f.dt < TRAIN_END], f[f.dt >= TRAIN_END]
    X = lambda d: np.column_stack([d[c] for c in cols] + [np.ones(len(d))])
    coef, *_ = np.linalg.lstsq(X(tr), tr.pace_gap.values, rcond=None)
    pred_te = X(te) @ coef
    r = np.corrcoef(pred_te, te.pace_gap)[0, 1]
    base_err = np.abs(te.pace_gap - tr.pace_gap.mean()).mean()
    print(f"\n■ ペース予測（学習{len(tr):,}R → テスト{len(te):,}R）")
    print("   係数: " + " / ".join(f"{c}{v:+.3f}" for c, v in zip(cols, coef)))
    print(f"   テストでの相関 r={r:.3f}  平均絶対誤差 {np.abs(pred_te - te.pace_gap).mean():.2f}秒"
          f"（予測せず平均値を使うと {base_err:.2f}秒）")
    te = te.assign(pred=pred_te)
    for lab, q in [("前傾と予測（上位25%）", te.pred <= te.pred.quantile(0.25)),
                   ("中間", (te.pred > te.pred.quantile(0.25)) & (te.pred < te.pred.quantile(0.75))),
                   ("後傾と予測（下位25%）", te.pred >= te.pred.quantile(0.75))]:
        g = te[q]
        print(f"   {lab:<22} n={len(g):>5} 実測の前後半差 {g.pace_gap.mean():+.2f}秒")
    f.to_parquet(BASE / "data" / "pace_features.parquet")
    print(f"\n保存: data/pace_features.parquet（{len(f):,}行）")


if __name__ == "__main__":
    main()
