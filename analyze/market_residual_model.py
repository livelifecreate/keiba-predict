"""
市場残差モデル検証（2026-09-19）

目的:
  「市場オッズに対して、我々の因子・新情報に上乗せの予測力が残っているか」を
  レース内ソフトマックス（条件付きロジット・勝ち馬予測）で測る。
  市場に勝つには 市場のみモデル より out-of-sample の対数損失が下がる必要がある。

データ（外部アクセスなし）:
  - data/検証_新ロジック_調教あり.csv … 2勝クラス以上の採点済み全頭（オッズ・人気・着順・因子）
  - cache/race_result/*.json          … 全クラスの着順（対戦相手レーティング=Elo の材料）

検証方法（ウォークフォワード・先読みなし）:
  fold1: 学習 〜2025/06 → テスト 2025/07〜2025/12
  fold2: 学習 〜2025/12 → テスト 2026/01〜
  Elo は各レース日より前の結果のみで算出。

出力: モデル別の対数損失・予想1位勝率/複勝率、単勝バリューベット（p×オッズ>閾値）のROI。
使い方: python3 analyze/market_residual_model.py
"""
import json, glob, re, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
CSV = BASE / "data" / "検証_新ロジック_調教あり.csv"
RACE_DIR = BASE / "cache" / "race_result"

CLASS_INIT = {"新馬": 1400, "未勝利": 1400, "1勝クラス": 1500, "2勝クラス": 1600,
              "3勝クラス": 1700, "OP": 1800, "重賞": 1900}
ELO_K = 24.0


def jp_date(s: str) -> pd.Timestamp:
    m = re.match(r"(\d+)年(\d+)月(\d+)日", s)
    return pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))


# ---------------------------------------------------------------- Elo
def build_elo() -> dict:
    """{(馬名, 日付): (レース前レーティング, それまでの出走数)} を返す。"""
    races = []
    for p in glob.glob(str(RACE_DIR / "*.json")):
        d = json.load(open(p))
        if not d.get("date") or not d.get("entries"):
            continue
        races.append((jp_date(d["date"]), d))
    races.sort(key=lambda x: x[0])

    rating, runs, out = {}, defaultdict(int), {}
    by_day = defaultdict(list)
    for dt, d in races:
        by_day[dt].append(d)
    for dt in sorted(by_day):
        updates = {}
        for d in by_day[dt]:
            init = CLASS_INIT.get(d.get("race_class"), 1500)
            ents = [e for e in d["entries"] if isinstance(e.get("rank"), int) and e["rank"] > 0]
            for e in d["entries"]:
                nm = e["horse_name"]
                out[(nm, dt)] = (rating.get(nm, init), runs[nm], init)
            n = len(ents)
            if n < 2:
                continue
            R = np.array([rating.get(e["horse_name"], init) for e in ents], dtype=float)
            rk = np.array([e["rank"] for e in ents], dtype=float)
            S = (n - rk) / (n - 1)                       # 1着=1, 最下位=0
            diff = (R[None, :] - R[:, None]) / 400.0
            E = (1.0 / (1.0 + 10 ** diff)).sum(axis=1) - 0.5   # 自分自身(0.5)を除く
            E = E / (n - 1)
            for e, r, s, ex in zip(ents, R, S, E):
                updates[e["horse_name"]] = r + ELO_K * (n - 1) ** 0.5 * (s - ex)
        for nm, v in updates.items():
            rating[nm] = v
            runs[nm] += 1
    return out


# ---------------------------------------------------------------- data
NON_FACTOR = ["日付", "競馬場", "レース名", "クラス", "コース", "距離", "出走頭数", "馬名", "馬番",
              "予想順位", "予想スコア", "単勝オッズ", "市場人気", "実着順", "調教あり"]


def load() -> tuple[pd.DataFrame, list[str]]:
    df = pd.read_csv(CSV)
    df["dt"] = df["日付"].map(jp_date)
    df["rid"] = df["日付"] + df["競馬場"] + df["レース名"] + df["距離"].astype(str) + df["コース"]
    df["実着順"] = pd.to_numeric(df["実着順"], errors="coerce")
    df["単勝オッズ"] = pd.to_numeric(df["単勝オッズ"], errors="coerce")
    factors = [c for c in df.columns if c not in NON_FACTOR + ["dt", "rid"]]
    for c in factors:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # 同名レース衝突（馬番重複）・オッズ欠損・勝ち馬なしのレースは除外
    ok = []
    for rid, g in df.groupby("rid"):
        if g["馬番"].duplicated().any():
            continue
        if (g["単勝オッズ"].isna() | (g["単勝オッズ"] <= 0)).any():
            continue
        if (g["実着順"] == 1).sum() != 1:
            continue
        ok.append(rid)
    n_all = df["rid"].nunique()
    df = df[df["rid"].isin(ok)].copy()
    print(f"対象レース: {len(ok)} / {n_all}（除外 {n_all - len(ok)}: オッズ欠損・同名衝突・同着/勝ち馬不明）")

    elo = build_elo()
    vals = [elo.get((nm, dt), (np.nan, 0, np.nan)) for nm, dt in zip(df["馬名"], df["dt"])]
    df["elo"] = [v[0] for v in vals]
    df["elo_runs"] = [v[1] for v in vals]
    print(f"Elo付与率: {df['elo'].notna().mean():.1%}  出走履歴2走以上: {(df['elo_runs'] >= 2).mean():.1%}")
    df["elo"] = df["elo"].fillna(df.groupby("rid")["elo"].transform("mean")).fillna(1600)

    g = df.groupby("rid")
    imp = 1.0 / df["単勝オッズ"]
    df["log_mkt"] = np.log(imp / imp.groupby(df["rid"]).transform("sum"))
    df["score_z"] = (df["予想スコア"] - g["予想スコア"].transform("mean")) / (g["予想スコア"].transform("std") + 1e-9)
    df["elo_d"] = (df["elo"] - g["elo"].transform("mean")) / 100.0
    df["elo_conf"] = df["elo_d"] * np.minimum(df["elo_runs"], 6) / 6.0   # 履歴が浅い馬は縮小
    for c in factors:                                                     # 因子はレース内中心化
        df[c] = df[c] - df.groupby("rid")[c].transform("mean")
    return df, factors


# ---------------------------------------------------------------- conditional logit
def fit(X, win, ridx, n_races, l2=1.0, iters=1500, lr=0.05):
    """レース内softmax。X:(n,k) win:(n,) 0/1  ridx:(n,) レース番号。Adam最適化。"""
    k = X.shape[1]
    w = np.zeros(k); m = np.zeros(k); v = np.zeros(k)
    for t in range(1, iters + 1):
        p = predict(X, w, ridx, n_races)
        grad = -(X * (win - p)[:, None]).sum(axis=0) / n_races + l2 * w / n_races
        m = 0.9 * m + 0.1 * grad
        v = 0.999 * v + 0.001 * grad ** 2
        w -= lr * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    return w


def predict(X, w, ridx, n_races):
    u = X @ w
    mx = np.full(n_races, -np.inf)
    np.maximum.at(mx, ridx, u)
    e = np.exp(u - mx[ridx])
    s = np.zeros(n_races)
    np.add.at(s, ridx, e)
    return e / s[ridx]


def evaluate(df, p, label, thresholds=(1.0, 1.1, 1.2, 1.3, 1.5)):
    d = df.assign(p=p)
    n = d["rid"].nunique()
    ll = -np.log(d.loc[d["実着順"] == 1, "p"]).mean()
    top = d.loc[d.groupby("rid")["p"].idxmax()]
    res = {"model": label, "n": n, "logloss": ll,
           "top1_win": (top["実着順"] == 1).mean(), "top1_place": (top["実着順"] <= 3).mean(),
           "top1_roi": (top["単勝オッズ"] * (top["実着順"] == 1)).mean()}
    for th in thresholds:
        b = d[d["p"] * d["単勝オッズ"] > th]
        res[f"ev>{th}"] = (len(b), (b["単勝オッズ"] * (b["実着順"] == 1)).sum() / max(len(b), 1))
    return res


def main():
    df, factors = load()
    folds = [("〜2025/06→2025/07-12", pd.Timestamp(2025, 7, 1), pd.Timestamp(2026, 1, 1)),
             ("〜2025/12→2026/01-", pd.Timestamp(2026, 1, 1), pd.Timestamp(2027, 1, 1))]
    models = {
        "A 市場のみ": ["log_mkt"],
        "B 市場+予想スコア": ["log_mkt", "score_z"],
        "C 市場+Elo": ["log_mkt", "elo_conf"],
        "D 市場+スコア+Elo": ["log_mkt", "score_z", "elo_conf"],
        "E 市場+全因子+Elo": ["log_mkt", "elo_conf"] + factors,
        "F スコアのみ(市場なし)": ["score_z"],
        "G Eloのみ(市場なし)": ["elo_conf"],
        "H 全因子+Elo(市場なし)": ["elo_conf"] + factors,
    }
    pooled = defaultdict(list)
    for name, t0, t1 in folds:
        tr, te = df[df["dt"] < t0], df[(df["dt"] >= t0) & (df["dt"] < t1)]
        print(f"\n===== fold {name}: 学習 {tr['rid'].nunique()}R / テスト {te['rid'].nunique()}R =====")
        for label, cols in models.items():
            mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
            if "log_mkt" in cols:
                mu["log_mkt"], sd["log_mkt"] = 0.0, 1.0
            rtr, utr = np.unique(tr["rid"], return_inverse=True)
            rte, ute = np.unique(te["rid"], return_inverse=True)
            w = fit(((tr[cols] - mu) / sd).values, (tr["実着順"] == 1).values.astype(float), utr, len(rtr),
                    l2=5.0 if len(cols) > 5 else 0.5)
            p = predict(((te[cols] - mu) / sd).values, w, ute, len(rte))
            pooled[label].append(te.assign(p=p))
            if len(cols) <= 3:
                print(f"  {label}: w={dict(zip(cols, np.round(w, 3)))}")
            else:
                order = np.argsort(-np.abs(w))[:8]
                print(f"  {label}: 上位係数 {[(cols[i], round(w[i], 3)) for i in order]}")

    print("\n===== テスト期間合算（out-of-sample）=====")
    rows = []
    for label, parts in pooled.items():
        d = pd.concat(parts)
        rows.append(evaluate(d, d["p"].values, label))
    # 市場の生の暗黙確率（無調整）も基準として併記
    d = pd.concat(pooled["A 市場のみ"])
    rows.insert(0, evaluate(d, np.exp(d["log_mkt"].values), "0 市場オッズ生値"))
    base = rows[1]["logloss"]
    print(f"{'モデル':<26}{'n':>5}{'logloss':>9}{'Δvs市場':>9}{'1位勝率':>8}{'1位複勝':>8}{'1位単ROI':>9}   バリューベット(件数, ROI)")
    for r in rows:
        ev = "  ".join(f"ev>{k[3:]}:{v[0]}件/{v[1]:.0%}" for k, v in r.items() if k.startswith("ev>"))
        print(f"{r['model']:<26}{r['n']:>5}{r['logloss']:>9.4f}{r['logloss'] - base:>+9.4f}"
              f"{r['top1_win']:>8.1%}{r['top1_place']:>8.1%}{r['top1_roi']:>9.1%}   {ev}")

    # クラス別（モデルDとA）
    print("\n===== クラス別: バリューベット ev>1.2 （A市場のみ / D市場+スコア+Elo）=====")
    for label in ["A 市場のみ", "D 市場+スコア+Elo", "E 市場+全因子+Elo"]:
        d = pd.concat(pooled[label])
        for cls, g in d.groupby("クラス"):
            b = g[g["p"] * g["単勝オッズ"] > 1.2]
            roi = (b["単勝オッズ"] * (b["実着順"] == 1)).sum() / max(len(b), 1)
            print(f"  {label:<20} {cls:<8} R={g['rid'].nunique():>4} 件数={len(b):>4} 的中={int((b['実着順'] == 1).sum()):>3} ROI={roi:.0%}")


if __name__ == "__main__":
    main()
