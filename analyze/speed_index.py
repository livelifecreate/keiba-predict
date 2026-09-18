"""
スピード指数の算出と合否判定（2026-09-19 作成・データ取得待ち）

入力: cache/horse_full_history/{horse_id}.json（fetch_full_career.py が保存。タイム列つき）
      ※ 2026-09-19 時点では未取得（netkeiba 通信制限中）。取得後にそのまま実行できる。

指数（西田式に準拠した簡易版）:
  基準タイム  = (競馬場, 芝ダ, 距離) ごとの 良・稍重 走破タイム中央値（30走以上ある条件のみ）
  馬場差      = (日付, 競馬場, 芝ダ) ごとの「(走破タイム-基準)/距離×1000」の中央値（5走以上、無ければ0）
  指数        = 80 + (基準 - タイム)×距離係数×10 + 馬場差補正 + (斤量-55)×2
                距離係数 = 1000/距離×… ではなく 1/(基準タイム/100) を使い、距離間で1秒の重みを揃える
  馬ごとの特徴量（レース日より前の走のみ・同じ芝ダのみ・過去2年）:
    si_best3 = 近3走の最高指数 / si_mean3 = 近3走平均 / si_last = 前走指数

合否（CLAUDE.md 2026-09-19 の方針）:
  analyze/market_residual_model.py と同じウォークフォワードで
  「市場のみ」より「市場+指数」の out-of-sample 対数損失が明確に下がり、
  かつ単勝バリューベットが n≥50・ROI>100%・高配当上位除外でも崩れないこと。満たさなければ却下。

使い方: python3 analyze/speed_index.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M

BASE = Path(__file__).resolve().parent.parent
FULL_DIR = BASE / "cache" / "horse_full_history"
RACE_DIR = BASE / "cache" / "race_result"
VENUES = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]


def parse_time(s: str) -> float | None:
    m = re.match(r"^(\d+):(\d{2})\.(\d)$", (s or "").strip())
    if m:
        return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 10
    m = re.match(r"^(\d{2})\.(\d)$", (s or "").strip())
    return int(m.group(1)) + int(m.group(2)) / 10 if m else None


def load_runs() -> pd.DataFrame:
    rows = []
    for p in FULL_DIR.glob("*.json"):
        try:
            recs = json.loads(p.read_text())
        except Exception:
            continue
        for r in recs:
            t = parse_time(r.get("time", ""))
            venue = next((v for v in VENUES if v in r.get("kaisan", "")), None)   # 地方・海外は除外
            dm = re.match(r"^(芝|ダ)(\d+)", r.get("dist_raw", ""))
            if t is None or venue is None or not dm:
                continue
            try:
                carried = float(r.get("carried") or 55)
            except ValueError:
                carried = 55.0
            rows.append({"horse_id": p.stem, "dt": pd.Timestamp(r["date_raw"].replace("/", "-")), "venue": venue,
                         "surface": dm.group(1), "dist": int(dm.group(2)), "track": r.get("track", ""),
                         "time": t, "carried": carried})
    return pd.DataFrame(rows)


def add_figures(runs: pd.DataFrame) -> pd.DataFrame:
    key = ["venue", "surface", "dist"]
    good = runs[runs["track"].isin(["良", "稍", "稍重"])]
    base = good.groupby(key)["time"].agg(["median", "count"]).reset_index()
    base = base[base["count"] >= 30].rename(columns={"median": "base"})[key + ["base"]]
    runs = runs.merge(base, on=key, how="inner")
    runs["dev"] = (runs["time"] - runs["base"]) / runs["dist"] * 1000          # 1000mあたりの遅れ(秒)
    day = runs.groupby(["dt", "venue", "surface"])["dev"].agg(["median", "count"]).reset_index()
    day["variant"] = np.where(day["count"] >= 5, day["median"], 0.0)
    runs = runs.merge(day[["dt", "venue", "surface", "variant"]], on=["dt", "venue", "surface"], how="left")
    adj_time = runs["time"] - runs["variant"] * runs["dist"] / 1000             # 馬場差を除いたタイム
    runs["si"] = 80 + (runs["base"] - adj_time) / (runs["base"] / 100) * 10 + (runs["carried"] - 55) * 2
    return runs


def horse_id_map() -> dict:
    """(馬名, 日付) → horse_id（CSVには馬IDが無いため race_result から引く）"""
    out = {}
    for p in RACE_DIR.glob("*.json"):
        d = json.loads(p.read_text())
        if not d.get("date"):
            continue
        dt = M.jp_date(d["date"])
        for e in d["entries"]:
            if e.get("horse_id"):
                out[(e["horse_name"], dt)] = e["horse_id"]
    return out


def attach(df: pd.DataFrame, runs: pd.DataFrame) -> pd.DataFrame:
    by_horse = {h: g.sort_values("dt") for h, g in runs.groupby("horse_id")}
    idmap = horse_id_map()
    best3, mean3, last = [], [], []
    for nm, dt, surf in zip(df["馬名"], df["dt"], df["コース"]):
        g = by_horse.get(idmap.get((nm, dt)))
        v = []
        if g is not None:
            s = "芝" if str(surf).startswith("芝") else "ダ"
            past = g[(g["dt"] < dt) & (g["dt"] >= dt - pd.Timedelta(days=730)) & (g["surface"] == s)]
            v = past["si"].tail(3).tolist()
        best3.append(max(v) if v else np.nan)
        mean3.append(float(np.mean(v)) if v else np.nan)
        last.append(v[-1] if v else np.nan)
    df = df.assign(si_best3=best3, si_mean3=mean3, si_last=last)
    print(f"指数付与率: {df['si_best3'].notna().mean():.1%}")
    for c in ["si_best3", "si_mean3", "si_last"]:                # 欠損はレース平均、レース内中心化
        m = df.groupby("rid")[c].transform("mean")
        df[c] = (df[c].fillna(m) - m).fillna(0.0)
    return df


def main():
    if not FULL_DIR.exists() or not any(FULL_DIR.glob("*.json")):
        sys.exit("cache/horse_full_history/ が空です。先に平日に python3 fetch_full_career.py --test → --run を実行してください。")
    runs = load_runs()
    if runs.empty:
        sys.exit("タイム列を持つレコードがありません（旧形式の取得データ？）。fetch_full_career.py で再取得してください。")
    runs = add_figures(runs)
    print(f"指数算出: {len(runs)}走 / {runs['horse_id'].nunique()}頭  指数 平均{runs['si'].mean():.1f} 標準偏差{runs['si'].std():.1f}")

    df, factors = M.load()
    df = attach(df, runs)
    si = ["si_best3", "si_mean3", "si_last"]
    models = {"A 市場のみ": ["log_mkt"], "B 市場+予想スコア": ["log_mkt", "score_z"],
              "S1 市場+指数": ["log_mkt"] + si, "S2 市場+スコア+指数": ["log_mkt", "score_z"] + si,
              "S3 指数のみ": si, "S4 スコア+指数(市場なし)": ["score_z"] + si, "F スコアのみ": ["score_z"]}
    folds = [(pd.Timestamp(2025, 7, 1), pd.Timestamp(2026, 1, 1)), (pd.Timestamp(2026, 1, 1), pd.Timestamp(2027, 1, 1))]
    pooled = defaultdict(list)
    for t0, t1 in folds:
        tr, te = df[df.dt < t0], df[(df.dt >= t0) & (df.dt < t1)]
        for label, cols in models.items():
            mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
            if "log_mkt" in cols:
                mu["log_mkt"], sd["log_mkt"] = 0.0, 1.0
            rtr, utr = np.unique(tr.rid, return_inverse=True)
            rte, ute = np.unique(te.rid, return_inverse=True)
            w = M.fit(((tr[cols] - mu) / sd).values, (tr["実着順"] == 1).values.astype(float), utr, len(rtr), l2=0.5)
            print(f"  fold {t0.date()} {label}: w={dict(zip(cols, np.round(w, 3)))}")
            pooled[label].append(te.assign(p=M.predict(((te[cols] - mu) / sd).values, w, ute, len(rte))))

    print("\n===== テスト期間合算 =====")
    base = None
    for label, parts in pooled.items():
        d = pd.concat(parts)
        r = M.evaluate(d, d["p"].values, label)
        base = r["logloss"] if base is None else base
        ev = "  ".join(f"ev>{k[3:]}:{v[0]}件/{v[1]:.0%}" for k, v in r.items() if k.startswith("ev>"))
        print(f"{label:<24} n={r['n']} logloss={r['logloss']:.4f} ({r['logloss'] - base:+.4f}) "
              f"1位勝率{r['top1_win']:.1%} 複勝{r['top1_place']:.1%} 単ROI{r['top1_roi']:.0%}  {ev}")
    print("\n判定基準: S1/S2 の logloss が A より明確に低く（目安 -0.01 以下）、バリューベットが n≥50・ROI>100% で"
          "高配当上位除外でも崩れないこと。満たさなければ却下。")


if __name__ == "__main__":
    main()
