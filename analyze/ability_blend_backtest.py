"""
能力指数v2を予想ロジックに組み込んだ場合のバックテスト（2026-09-20・scorerは変更しない）

比較する順位づけ（重みは 〜2025/06 の学習期間のみで決定し、テスト 2025/07〜 で評価）:
  A 現行予想スコア
  B 能力指数v2のみ
  C 現行スコア + v2（2変数の重みを学習）
  D v2 + 現行の「能力以外」因子の合計（能力系因子＝過去の成績を測る因子はv2に置き換え）
  E v2 + 「能力以外」因子を個別に再重み付け（L2正則化）
  M 市場人気順（参考）

評価: verify/bet_metrics_standard の9馬券種（総合・クラス別）＋現行買いサイン
      （3勝/OP・非18頭・三連複1軸-相手2〜6位10点）。1点100円。払戻は cache/payouts。
使い方: python3 analyze/ability_blend_backtest.py
"""
import sys, tempfile
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M
import ability_index as A
import verify.bet_analysis2 as ba2
from verify.bet_metrics_standard import sim_bet, BET_SPECS, CLASSES

TRAIN_END = pd.Timestamp(2025, 7, 1)
# 「過去の成績＝能力」を測っている因子（v2と役割が重複するので D/E では外す）
ABILITY_FACTORS = ["前走重賞近差", "前々走重賞近差", "前走3F最速", "同コース実績", "近走上昇傾向", "前走好走", "前々走好走",
                   "グレード実績(3-4走前)", "クラス実績(格×着差)", "複勝安定ボーナス", "勝利数ボーナス", "内容評価スコア",
                   "急坂パワー", "競馬場巧者", "昇級初戦", "前走ローカル"]


def attach_v2(df):
    margins, races = A.load_margins(), A.load_races()
    ratings = {}
    for s in ("芝", "ダ"):
        obs, hmap, rr = A.build_obs(races, margins, s)
        ratings.update(A.walk_forward(obs, hmap, rr, 365, 2.0, "yr"))
    name_dt = {}
    for r in races:
        for e in r["ents"]:
            name_dt[(e["horse_name"], r["dt"])] = e["horse_id"]
    v = [ratings.get((name_dt.get((nm, dt)), dt), (np.nan, 0))[0] for nm, dt in zip(df["馬名"], df["dt"])]
    df["v2"] = v
    print(f"v2付与率: {df['v2'].notna().mean():.1%}")
    m = df.groupby("rid")["v2"].transform("mean")
    df["v2_c"] = (df["v2"].fillna(m) - m).fillna(0.0)
    return df


PARAMS = {}


def fit_util(df, cols, l2):
    tr = df[df.dt < TRAIN_END]
    mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
    _, utr = np.unique(tr.rid, return_inverse=True)
    w = M.fit(((tr[cols] - mu) / sd).values, (tr["実着順"] == 1).values.astype(float), utr, utr.max() + 1, l2=l2, iters=1200)
    PARAMS[tuple(cols)] = {"cols": cols, "w": [float(x) for x in w], "mu": [float(x) for x in mu], "sd": [float(x) for x in sd]}
    return ((df[cols] - mu) / sd).values @ w, dict(zip(cols, np.round(w, 3)))


def buy_sign(var_df, races):
    """現行買いサイン: 3勝/OP・非18頭・三連複 1軸(1位)-相手2〜6位 10点"""
    rid_of = {r["key"]: r["race_id"] for r in races}
    n = hits = invest = collect = 0
    for key, g in var_df.groupby(["日付", "レース名"]):
        if g["クラス"].iloc[0] not in ("3勝クラス", "OP") or len(g) == 18 or len(g) < 6 or key not in rid_of:
            continue
        nums, amounts = ba2.get_payout(rid_of[key], "3連複")
        if not amounts or len(nums) < 3 * len(amounts):
            continue
        g = g.sort_values("予想順位")
        axis, others = int(g["馬番"].iloc[0]), [int(x) for x in g["馬番"].iloc[1:6]]
        bets = {frozenset((axis,) + c) for c in combinations(others, 2)}
        n += 1
        invest += 100 * len(bets)
        got = sum(a for k, a in enumerate(amounts) if frozenset(nums[3 * k:3 * k + 3]) in bets)
        hits += got > 0
        collect += got
    return n, hits / max(n, 1) * 100, collect / max(invest, 1) * 100


def main():
    raw = pd.read_csv(M.CSV, dtype=str)
    df, factors = M.load()                       # 因子はレース内中心化済み
    df = attach_v2(df)
    rest = [c for c in factors if c not in ABILITY_FACTORS]
    df["rest_sum"] = df[rest].sum(axis=1)
    print(f"能力系因子 {len([c for c in factors if c in ABILITY_FACTORS])}個をv2に置換 / 残す因子 {len(rest)}個: {rest}")

    utils = {"A 現行予想スコア": df["予想スコア"].astype(float).values}
    utils["B v2のみ"] = df["v2_c"].values
    utils["C 現行スコア+v2"], wc = fit_util(df, ["score_z", "v2_c"], 0.5)
    utils["D v2+能力以外の因子合計"], wd = fit_util(df, ["v2_c", "rest_sum"], 0.5)
    utils["E v2+能力以外を個別再重み"], we = fit_util(df, ["v2_c"] + rest, 5.0)
    # v3（能力θと条件効果の同時推定・analyze/ability_index_v3.py が保存）があれば比較に加える
    v3p = BASE / "data" / "v3_eval.parquet"
    if v3p.exists():
        v3 = pd.read_parquet(v3p)[["馬名", "dt", "v3_c", "ctx_c", "v3_full"]]
        v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
        j = df.join(v3, on=["馬名", "dt"])
        cover = j["v3_full"].notna().mean()
        for c in ("v3_c", "ctx_c", "v3_full"):
            m = j.groupby("rid")[c].transform("mean")
            df[c] = (j[c].fillna(m) - m).fillna(0.0)
        print(f"v3付与率: {cover:.1%}")
        utils["F v3(能力+条件)"] = df["v3_full"].values
        utils["G v3能力+現行の能力以外"], wg = fit_util(df, ["v3_c", "rest_sum"], 0.5)
        utils["H v3(能力+条件)+残り因子"], wh = fit_util(df, ["v3_full", "rest_sum"], 0.5)
        print("  v3の重み  G:", wg, " H:", wh)
    utils["M 市場人気順(参考)"] = -df["市場人気"].astype(float).values
    import json
    out_p = BASE / "data" / "plan_d_params.json"
    out_p.write_text(json.dumps({"note": "案D: u = Σ w·(x-mu)/sd, x=[v2_c(能力指数v2のレース内中心化), rest_sum(能力系16因子を除いた現行スコアのレース内中心化)]。学習 〜2025/06",
                                 "tau": 365, "lam": 2.0, "ykey": "yr", "ability_factors": ABILITY_FACTORS,
                                 **PARAMS[("v2_c", "rest_sum")]}, ensure_ascii=False, indent=1))
    print("案Dパラメータ保存:", out_p)
    print("学習した重み  C:", wc, " D:", wd)
    print("             E:", {k: v for k, v in sorted(we.items(), key=lambda kv: -abs(kv[1]))[:8]})

    test = df[df.dt >= TRAIN_END]
    raw = raw.loc[test.index]
    tmp = Path(tempfile.mkdtemp())
    summary, per_class, signs = {}, {}, {}
    for label, u in utils.items():
        t = test.assign(u=pd.Series(u, index=df.index).loc[test.index])
        rk = t.groupby("rid")["u"].rank(ascending=False, method="first").astype(int)
        out = raw.copy()
        out["予想順位"] = rk.astype(str)
        out["予想スコア"] = t["u"].round(4).astype(str)
        path = tmp / f"{label[0]}.csv"
        out.to_csv(path, index=False, encoding="utf-8-sig")
        ba2.CSV_PATH = path
        races = ba2.load_races()
        summary[label] = {name: sim_bet(races, kind) for name, kind in BET_SPECS}
        per_class[label] = {c: {name: sim_bet([r for r in races if r["class"] == c], kind) for name, kind in BET_SPECS} for c in CLASSES}
        top = t[rk == 1]
        summary[label]["_top1"] = ((top["実着順"] == 1).mean() * 100, (top["実着順"] <= 3).mean() * 100, len(races))
        ret = (top["単勝オッズ"] * (top["実着順"] == 1)).sort_values(ascending=False)
        half = top["dt"] < pd.Timestamp(2026, 1, 1)
        summary[label]["_robust"] = (ret.sum() / len(ret) * 100, ret.iloc[3:].sum() / len(ret) * 100, ret.iloc[10:].sum() / len(ret) * 100,
                                     ret[half].sum() / half.sum() * 100, ret[~half].sum() / (~half).sum() * 100,
                                     top["単勝オッズ"].median(), top["市場人気"].astype(float).mean())
        signs[label] = buy_sign(out.assign(予想順位=rk.values), races)

    labels = list(utils)
    print(f"\n===== テスト期間 2025/07〜（払戻ありレース n={summary[labels[0]]['_top1'][2]}）総合: 的中率% / ROI% =====")
    print(f"{'馬券種別':<14}" + "".join(f"{l[:12]:>16}" for l in labels))
    print(f"{'予想1位 勝率/複勝率':<14}" + "".join(f"{summary[l]['_top1'][0]:>8.1f}/{summary[l]['_top1'][1]:>5.1f}  " for l in labels))
    for name, _ in BET_SPECS:
        print(f"{name:<14}" + "".join(f"{summary[l][name]['hit_rate']:>8.1f}/{summary[l][name]['roi']:>5.0f}  " for l in labels))
    print(f"{'現行買いサイン':<14}" + "".join(f"{signs[l][1]:>8.1f}/{signs[l][2]:>5.0f}  " for l in labels) + f"  (n={signs[labels[0]][0]})")

    print("\n===== 単勝ROIの頑健性（予想1位・テスト全レース）=====")
    print(f"{'':<24}{'ROI':>6}{'上位3除外':>9}{'上位10除外':>10}{'2025後半':>9}{'2026':>7}{'1位の中央オッズ':>12}{'1位の平均人気':>10}")
    for l in labels:
        a = summary[l]["_robust"]
        print(f"{l:<24}{a[0]:>6.0f}{a[1]:>9.0f}{a[2]:>10.0f}{a[3]:>9.0f}{a[4]:>7.0f}{a[5]:>12.1f}{a[6]:>10.1f}")

    for c in CLASSES:
        n = per_class[labels[0]][c]["単勝"]["n"]
        print(f"\n--- {c} (n={n}) 的中率% / ROI% ---")
        for name, _ in BET_SPECS:
            print(f"{name:<14}" + "".join(f"{per_class[l][c][name]['hit_rate']:>8.1f}/{per_class[l][c][name]['roi']:>5.0f}  " for l in labels))


if __name__ == "__main__":
    main()
