"""
能力指数 v2（同時推定型・2026-09-20）

旧Elo（market_residual_model.build_elo）の欠陥:
  逐次更新のため「キャッシュ最初のレースのクラス初期値」が残り続け、下から昇級した馬を
  構造的に過小評価、重賞から記録が始まる馬を過大評価していた（例: ヴーレヴー1636 vs コスモキュランダ1926）。

v2 の考え方（人間の評価と同じ構造）:
  能力θ_i = 対戦相手の平均能力 + その中での相対パフォーマンス
  - 全馬・全レースを同時に反復で解く（初期値・クラス事前値なし。クラス間の差は昇降級馬の結果から決まる）
  - 相対パフォーマンス y: 着差ベース（勝ち馬からの秒差・1600m換算・上限つき）または 着順の正規スコア
    着差は cache/horse_history スナップショットから (馬ID, 日付) で引く。欠損は同レース内の既知着差から着順で補間
  - 時間減衰 w = exp(-経過日数/τ) で「現時点の強さ」に寄せる
  - 実績の少ない馬は「対戦相手並み」に縮小: θ_i = Σw·相手平均/Σw + Σw·y/(Σw+λ)
  - 芝・ダート別に推定。評価日より前のレースのみ使用（先読みなし）

検証: ウォークフォワード（各開催日の朝に再推定）。学習 〜2025/06、テスト 2025/07〜。
  ① 指数単体の予測力（レース内softmax）を 旧Elo・予想スコア・市場 と比較
  ② 歪み診断: 「初登場クラスが低い馬/高い馬」で 指数順位−人気順位 の平均（0に近いほど歪みなし）
  ③ 市場残差: 市場のみ vs 市場+指数 の対数損失

使い方:
  python3 analyze/ability_index.py                 # 検証
  python3 analyze/ability_index.py --csv results/2026-09-20/中山/score_....csv   # 出走馬の現在指数
"""
import argparse, glob, json, re, sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M

BASE = Path(__file__).resolve().parent.parent
RACE_DIR = BASE / "cache" / "race_result"
HIST_DIR = BASE / "cache" / "horse_history"
MARGIN_CAP = 2.0          # 秒（1600m換算）。これ以上の大敗は同じ扱い
TRAIN_END = pd.Timestamp(2025, 7, 1)
EVAL_START = pd.Timestamp(2024, 10, 1)   # 推定の助走期間（2024/06〜09）の後から評価
_ND = NormalDist()


# ------------------------------------------------------------------ データ
def load_margins() -> dict:
    """{(horse_id, 日付): 勝ち馬からの秒差(勝ち馬は0)} をスナップショットから収集"""
    out = {}
    for p in HIST_DIR.glob("*.json"):
        hid = p.stem.split("_")[0]
        try:
            lines = json.loads(p.read_text())
        except Exception:
            continue
        for s in lines:
            if not isinstance(s, str):
                continue
            md = re.match(r"(\d+)年(\d+)月(\d+)日", s)
            mm = re.search(r"3F\s*[\d.]*\(([-\d.]+)\)", s)
            if not md or not mm:
                continue
            try:
                v = float(mm.group(1))
            except ValueError:
                continue
            out[(hid, pd.Timestamp(int(md.group(1)), int(md.group(2)), int(md.group(3))))] = max(v, 0.0)
    return out


def load_races() -> list[dict]:
    races = []
    for p in glob.glob(str(RACE_DIR / "*.json")):
        d = json.load(open(p))
        if d.get("surface") not in ("芝", "ダ") or not d.get("date"):
            continue
        if "障害" in (d.get("race_name", "") + d.get("conditions", "")):
            continue
        ents = [e for e in d["entries"] if isinstance(e.get("rank"), int) and e["rank"] > 0 and e.get("horse_id")]
        if len(ents) < 4:
            continue
        m = re.search(r"(\d+)", str(d.get("distance", "")))
        races.append({"rid": d.get("race_id") or Path(p).stem, "dt": M.jp_date(d["date"]), "surface": d["surface"],
                      "cls": d.get("race_class"), "dist": int(m.group(1)) if m else 1600,
                      "ents": sorted(ents, key=lambda e: e["rank"])})
    races.sort(key=lambda r: r["dt"])
    return races


def fill_margins(race: dict, margins: dict, step: float) -> tuple[np.ndarray, int]:
    """レース内の1600m換算着差（上限つき）。欠損は既知着差から着順で補間、末尾は step ずつ外挿"""
    k = 1600.0 / race["dist"]
    ranks = np.array([e["rank"] for e in race["ents"]], dtype=float)
    known = {0: 0.0}
    for i, e in enumerate(race["ents"]):
        v = margins.get((e["horse_id"], race["dt"]))
        if v is not None:
            known[i] = v * k if e["rank"] > 1 else 0.0
    idx = sorted(known)
    xs, ys = ranks[idx], np.maximum.accumulate([known[i] for i in idx])     # 着順に対して単調に
    out = np.interp(ranks, xs, ys)
    beyond = ranks > xs[-1]
    out[beyond] = ys[-1] + (ranks[beyond] - xs[-1]) * step
    return np.minimum(out, MARGIN_CAP), len(known) - 1


def build_obs(races, margins, surface):
    """観測配列を作る: 馬index・レースindex・日付(序数)・y(着差型)・y(着順型)"""
    hmap, H, R, D, YM, YR = {}, [], [], [], [], []
    rr = [r for r in races if r["surface"] == surface]
    # 着順1つあたりの典型的な着差（外挿用）
    incs = []
    for r in rr:
        ms = [(e["rank"], margins.get((e["horse_id"], r["dt"]))) for e in r["ents"]]
        ms = [(a, b * 1600.0 / r["dist"]) for a, b in ms if b is not None and a > 1 and b < 3]
        incs += [b / (a - 1) for a, b in ms]
    step = float(np.median(incs)) if incs else 0.15
    n_known = n_all = 0
    for ri, r in enumerate(rr):
        m, k = fill_margins(r, margins, step)
        n = len(r["ents"])
        n_known += k + 1
        n_all += n
        ym = -(m - m.mean())
        for i, e in enumerate(r["ents"]):
            H.append(hmap.setdefault(e["horse_id"], len(hmap)))
            R.append(ri)
            D.append(r["dt"].toordinal())
            YM.append(ym[i])
            YR.append(_ND.inv_cdf((n - e["rank"] + 0.5) / n))
    obs = {"h": np.array(H), "r": np.array(R), "d": np.array(D), "ym": np.array(YM), "yr": np.array(YR)}
    sd = obs["ym"].std()
    obs["ym"] = obs["ym"] / sd * obs["yr"].std()          # 2種類のyを同じスケールに
    print(f"[{surface}] {len(rr)}R / {len(hmap)}頭 / 観測{len(H)}  着差の実測率 {n_known / n_all:.1%}  典型着差/着順 {step:.3f}秒")
    return obs, hmap, rr


# ------------------------------------------------------------------ 推定
EPS = 1e-2   # 全体平均への極小の錨（定数分の不定性を消す。値にはほぼ影響しない）


def fit(obs, as_of: int, tau: float, lam: float, ykey: str, n_horses: int, theta0=None, iters=2000, tol=1e-7):
    """
    重み付き最小二乗  Σ w (ỹ_ir − (θ_i − レース平均θ_r))² + EPS·Σθ_i²  を前処理つき共役勾配法で解く。
      ỹ_ir: 相対パフォーマンスを馬ごとの信頼度 s_i = W_i/(W_i+λ) で縮小し、レース内で再中心化したもの
            （再中心化でレース内の総和が0になり、解が一意に存在する。初版はこれが崩れて発散した）
    解は「各馬の残差の加重平均が0」= 馬は平均して指数どおりに走る、を満たす。
    """
    mask = obs["d"] < as_of
    if mask.sum() == 0:
        return np.full(n_horses, np.nan), np.zeros(n_horses)
    h, y = obs["h"][mask], obs[ykey][mask]
    _, r = np.unique(obs["r"][mask], return_inverse=True)
    w = np.exp(-(as_of - obs["d"][mask]) / tau)
    nr = int(r.max()) + 1
    cnt = np.bincount(r, minlength=nr).astype(float)
    W = np.bincount(h, weights=w, minlength=n_horses)
    seen = W > 0
    ys = (W / (W + lam))[h] * y
    ys = ys - (np.bincount(r, weights=ys, minlength=nr) / cnt)[r]
    b = np.bincount(h, weights=w * ys, minlength=n_horses)
    diag = W + EPS

    def matvec(x):
        rm = np.bincount(r, weights=x[h], minlength=nr) / cnt
        return diag * x - np.bincount(h, weights=w * rm[r], minlength=n_horses)

    x = np.zeros(n_horses) if theta0 is None else np.where(np.isnan(theta0), 0.0, theta0)
    res = b - matvec(x)
    z = res / diag
    p = z.copy()
    rz = res @ z
    bnorm = np.sqrt(b @ b) + 1e-12
    for _ in range(iters):
        Ap = matvec(p)
        alpha = rz / (p @ Ap)
        x += alpha * p
        res -= alpha * Ap
        if np.sqrt(res @ res) / bnorm < tol:
            break
        z = res / diag
        rz_new = res @ z
        p = z + (rz_new / rz) * p
        rz = rz_new
    x[seen] -= np.average(x[seen], weights=W[seen])
    x[~seen] = np.nan
    return x, W


def walk_forward(obs, hmap, rr, tau, lam, ykey):
    """各開催日の朝に再推定し {(horse_id, 日付): (θ, 有効走数)} を返す"""
    out, theta = {}, None
    days = sorted({r["dt"] for r in rr if r["dt"] >= EVAL_START})
    by_day = defaultdict(list)
    for r in rr:
        by_day[r["dt"]].append(r)
    for dt in days:
        theta, den = fit(obs, dt.toordinal(), tau, lam, ykey, len(hmap), theta0=theta)
        for r in by_day[dt]:
            for e in r["ents"]:
                j = hmap[e["horse_id"]]
                out[(e["horse_id"], dt)] = (theta[j], den[j])
    return out


# ------------------------------------------------------------------ 評価
def eval_frame(races, ratings: dict, elo: dict) -> pd.DataFrame:
    rows = []
    first_cls = {}
    for r in races:
        for e in r["ents"]:
            first_cls.setdefault(e["horse_id"], r["cls"])
    for r in races:
        if r["dt"] < EVAL_START or r["cls"] == "新馬":
            continue
        if any(not e.get("odds") for e in r["ents"]):
            continue
        for e in r["ents"]:
            th, ne = ratings.get((e["horse_id"], r["dt"]), (np.nan, 0.0))
            rows.append({"rid": r["rid"], "dt": r["dt"], "cls": r["cls"], "surface": r["surface"], "馬名": e["horse_name"],
                         "rank": e["rank"], "odds": e["odds"], "pop": e["popularity"], "v2": th, "neff": ne,
                         "elo": elo.get((e["horse_name"], r["dt"]), (np.nan,))[0], "first_cls": first_cls[e["horse_id"]]})
    df = pd.DataFrame(rows)
    ok = df.groupby("rid")["v2"].transform(lambda s: s.notna().mean()) >= 0.6     # 指数のある馬が6割以上のレースのみ
    df = df[ok].copy()
    for c in ("v2", "elo"):
        m = df.groupby("rid")[c].transform("mean")
        df[c + "_c"] = (df[c].fillna(m) - m).fillna(0.0)
    imp = 1.0 / df["odds"]
    df["log_mkt"] = np.log(imp / imp.groupby(df["rid"]).transform("sum"))
    return df


def softmax_eval(df, cols, label):
    tr, te = df[df.dt < TRAIN_END], df[df.dt >= TRAIN_END]
    mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
    if "log_mkt" in cols:
        mu["log_mkt"], sd["log_mkt"] = 0.0, 1.0
    rtr, utr = np.unique(tr.rid, return_inverse=True)
    rte, ute = np.unique(te.rid, return_inverse=True)
    w = M.fit(((tr[cols] - mu) / sd).values, (tr["rank"] == 1).values.astype(float), utr, len(rtr), l2=0.5, iters=800)
    p = M.predict(((te[cols] - mu) / sd).values, w, ute, len(rte))
    d = te.assign(p=p)
    top = d.loc[d.groupby("rid")["p"].idxmax()]
    ll = -np.log(d.loc[d["rank"] == 1, "p"]).mean()
    return {"model": label, "n": len(rte), "logloss": ll, "win": (top["rank"] == 1).mean(),
            "place": (top["rank"] <= 3).mean(), "roi": (top["odds"] * (top["rank"] == 1)).mean(),
            "w": dict(zip(cols, np.round(w, 3)))}


def spearman_with_market(df, col):
    te = df[df.dt >= TRAIN_END]
    cors = []
    for _, g in te.groupby("rid"):
        if g[col].std() > 0:
            cors.append(g[col].rank(ascending=False).corr(g["pop"].rank()))
    return float(np.mean(cors))


def bias_table(df, col):
    te = df[(df.dt >= TRAIN_END) & df["cls"].isin(["2勝クラス", "3勝クラス", "OP", "重賞"])].copy()
    te["idx_rank"] = te.groupby("rid")[col].rank(ascending=False)
    te["gap"] = te["idx_rank"] - te["pop"]          # +なら指数が市場より低く評価
    low = te[te["first_cls"].isin(["新馬", "未勝利", "1勝クラス"])]
    high = te[te["first_cls"].isin(["OP", "重賞"])]
    return low["gap"].mean(), len(low), high["gap"].mean(), len(high)


def run_validation():
    margins = load_margins()
    races = load_races()
    print(f"レース {len(races)}R  着差データ {len(margins)}件")
    elo = M.build_elo()
    configs = [("着差型 τ=365 λ=2", 365, 2.0, "ym"), ("着差型 τ=540 λ=2", 540, 2.0, "ym"), ("着差型 τ=270 λ=2", 270, 2.0, "ym"),
               ("着差型 τ=365 λ=4", 365, 4.0, "ym"), ("着順型 τ=365 λ=2", 365, 2.0, "yr")]
    built = {s: build_obs(races, margins, s) for s in ("芝", "ダ")}
    results, frames = [], {}
    for label, tau, lam, yk in configs:
        ratings = {}
        for s in ("芝", "ダ"):
            obs, hmap, rr = built[s]
            ratings.update(walk_forward(obs, hmap, rr, tau, lam, yk))
        df = eval_frame(races, ratings, elo)
        frames[label] = df
        r = softmax_eval(df, ["v2_c"], "v2 " + label)
        r["spearman"] = spearman_with_market(df, "v2_c")
        r["bias"] = bias_table(df, "v2_c")
        r["resid"] = softmax_eval(df, ["log_mkt", "v2_c"], "")["logloss"]
        results.append(r)
        print(f"  完了: {label}", flush=True)

    df = frames[configs[0][0]]
    base_mkt = softmax_eval(df, ["log_mkt"], "市場のみ")
    r_elo = softmax_eval(df, ["elo_c"], "旧Elo")
    r_elo["spearman"] = spearman_with_market(df, "elo_c")
    r_elo["bias"] = bias_table(df, "elo_c")
    r_elo["resid"] = softmax_eval(df, ["log_mkt", "elo_c"], "")["logloss"]

    print(f"\n===== 全クラス（新馬除く）テスト 2025/07〜  n={base_mkt['n']}R =====")
    print(f"{'指数':<22}{'logloss':>8}{'1位勝率':>8}{'1位複勝':>8}{'単ROI':>7}{'人気との順位相関':>10}  歪み(指数順位−人気): 下から昇級組 / 上位クラス初登場組   市場+指数logloss")
    print(f"{'市場(人気)':<22}{base_mkt['logloss']:>8.4f}{base_mkt['win']:>8.1%}{base_mkt['place']:>8.1%}{base_mkt['roi']:>7.0%}{'—':>10}  {'—':<50} {base_mkt['logloss']:.4f}")
    for r in [r_elo] + results:
        b = r["bias"]
        print(f"{r['model']:<22}{r['logloss']:>8.4f}{r['win']:>8.1%}{r['place']:>8.1%}{r['roi']:>7.0%}{r['spearman']:>10.3f}"
              f"  {b[0]:>+6.2f} (n={b[1]}) / {b[2]:>+6.2f} (n={b[3]}){'':<14} {r['resid']:.4f}")

    # 2勝以上: 予想スコアと比較
    best = min(results, key=lambda r: r["logloss"])
    bl = best["model"][3:]
    csv_df, _ = M.load()
    key = frames[bl].set_index(["馬名", "dt"])[["v2_c", "elo_c"]]
    key = key[~key.index.duplicated()]
    sub = csv_df.join(key, on=["馬名", "dt"], how="inner").rename(columns={"実着順": "rank", "単勝オッズ": "odds"})
    sub = sub[sub.groupby("rid")["v2_c"].transform("count") >= 5]
    print(f"\n===== 2勝クラス以上・採点CSVと突合（最良設定: {bl}）=====")
    for cols, lab in [(["log_mkt"], "市場のみ"), (["score_z"], "現行予想スコア"), (["v2_c"], "能力指数v2"), (["elo_c"], "旧Elo"),
                      (["score_z", "v2_c"], "予想スコア+v2"), (["log_mkt", "v2_c"], "市場+v2"), (["log_mkt", "score_z", "v2_c"], "市場+スコア+v2")]:
        r = softmax_eval(sub, cols, lab)
        print(f"  {lab:<16} n={r['n']} logloss={r['logloss']:.4f} 1位勝率{r['win']:.1%} 複勝率{r['place']:.1%} 単ROI{r['roi']:.0%}  w={r['w']}")


def show_entries(csv_path: str, tau=365, lam=2.0, ykey="yr"):   # 検証で最良だった設定
    margins, races = load_margins(), load_races()
    rows = [r for r in __import__("csv").reader(open(csv_path, encoding="utf-8-sig"))]
    info = next((r for r in rows if r and r[0].startswith("■レース情報")), None)
    surface = "芝" if info and info[1].startswith("芝") else "ダ"
    names = [(r[2], r[3], r[5], r[6]) for r in rows[1:] if len(r) > 6 and r[0].isdigit()]
    obs, hmap, rr = build_obs(races, margins, surface)
    today = pd.Timestamp.today().normalize().toordinal() + 1
    theta, den = fit(obs, today, tau, lam, ykey, len(hmap))
    name2id = {}
    for r in races:
        for e in r["ents"]:
            name2id[e["horse_name"]] = e["horse_id"]
    active = den > 0.5
    mu, sd = np.nanmean(theta[active]), np.nanstd(theta[active])
    out = []
    for num, nm, odds, pop in names:
        j = hmap.get(name2id.get(nm))
        th = theta[j] if j is not None else np.nan
        out.append((50 + 10 * (th - mu) / sd if not np.isnan(th) else np.nan, num, nm, odds, pop, den[j] if j is not None else 0))
    out.sort(key=lambda x: -(x[0] if not np.isnan(x[0]) else -99))
    print(f"\n能力指数v2（{surface}・偏差値表示: 現役{surface}馬 {int(active.sum())}頭の平均50・標準偏差10）")
    print(f"{'順':>2} {'馬番':>3} {'馬名':<12}{'指数':>6}{'有効走数':>7}{'単勝':>7} {'人気':>5}")
    for i, (v, num, nm, odds, pop, ne) in enumerate(out, 1):
        print(f"{i:>2} {num:>3} {nm:<12}{v:>6.1f}{ne:>7.1f}{odds:>7} {pop:>5}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="", help="予想CSV（出走馬の現在指数を表示）")
    a = ap.parse_args()
    show_entries(a.csv) if a.csv else run_validation()
