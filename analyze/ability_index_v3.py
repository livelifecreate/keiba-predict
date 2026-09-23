"""
能力指数 v3（能力と条件の同時推定・2026-09-22）

v2 の限界: θ（能力）に「良い騎手が乗り続けた分」「内枠が多かった分」などの条件が混ざる。
  加減点（現行34因子のうち能力以外の18因子）は人が決めた固定配点で、データ由来ではない。

v3 の考え方: 1本の式で能力と条件を同時に推定する。
  走り y_ir = θ_i（馬の能力） + Σ_k x_ir,k · β_k（条件） + 残差     ※ すべてレース内で中心化
  条件 x: 騎手 / 枠順（馬番÷頭数と内外）/ 斤量 / 年齢・性別 / 休養間隔 / 距離変化 / クラス変化
  - θ と β を最小二乗で同時に解く（前処理つき共役勾配法・v2 と同じ枠組み）
  - 騎手など多水準の効果は L2 で縮小（出走の少ない騎手は0へ寄る）
  - 時間減衰 τ=365日、実績の少ない馬は縮小（λ）、芝ダ別、評価日より前のレースのみ使用（先読みなし）

これにより (a) θ が条件を除いた純粋な能力になり、(b) 加減点がデータで決まる。

検証: ウォークフォワード（開催日ごとに再推定）、テスト2025/07〜。
  ① θ_v3 単体 vs θ_v2 単体 vs 現行予想スコア vs 市場
  ② θ_v3 + 推定した条件効果（= v3の予測値）vs 案D（v2 + 手作り加減点18因子）
使い方: python3 analyze/ability_index_v3.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import market_residual_model as M
import wet_track_calibration as WET

BASE = Path(__file__).resolve().parent.parent
FULL_DIR = BASE / "cache" / "horse_full_history"
ND = NormalDist()
TAU, LAM = 365.0, 2.0
L2_JOCKEY, L2_DENSE = 40.0, 5.0      # 騎手は強めに縮小
CLASS_LEVEL = {"新馬": 0, "未勝利": 0, "1勝クラス": 1, "2勝クラス": 2, "3勝クラス": 3, "OP": 4, "重賞": 5}


# ------------------------------------------------------------------ 前走情報
def prev_map() -> dict:
    """{(馬ID, レース日): (前走日, 前走距離, 前走クラスレベル)} を通算成績から作る"""
    out = {}
    for p in FULL_DIR.glob("*.json"):
        try:
            recs = json.loads(p.read_text())
        except Exception:
            continue
        rows = []
        for r in recs:
            m = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
            dm = re.match(r"^(芝|ダ)(\d+)", r.get("dist_raw", ""))
            if m and dm:
                rows.append((pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3))),
                             int(dm.group(2)), _lvl(r.get("race_raw", ""))))
        rows.sort()
        hid = p.stem
        for k in range(1, len(rows)):
            out[(hid, rows[k][0])] = rows[k - 1]
    return out


def _lvl(race_raw: str) -> int:
    s = race_raw or ""
    if re.search(r"\((GI|G1|JpnI)\)", s): return 5
    if re.search(r"\((GII|G2|JpnII|GIII|G3|JpnIII)\)", s): return 5
    if re.search(r"\((L|OP)\)", s) or "オープン" in s: return 4
    if "3勝" in s or "1600万" in s: return 3
    if "2勝" in s or "1000万" in s: return 2
    if "1勝" in s or "500万" in s: return 1
    return 0


# ------------------------------------------------------------------ 馬場と道悪適性
def going_map(races) -> dict:
    """{rid: 良/稍重/重/不良}。通算成績の4区分を優先し、無ければ race_result の2値"""
    full = WET.going_from_full_history()
    venue, fb = {}, {}
    for p in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(p.read_text())
        rid = d.get("race_id") or p.stem
        venue[rid] = d.get("venue") or ""
        fb[rid] = WET.NORM.get(d.get("track_condition") or "", "")
    out = {}
    for r in races:
        g = full.get((r["dt"], venue.get(r["rid"], ""), r["surface"])) if full else None
        out[r["rid"]] = g or fb.get(r["rid"], "")
    return out


def sire_map() -> dict:
    out = {}
    for p in (BASE / "cache" / "sire").glob("*.json"):
        try:
            v = json.loads(p.read_text())
            out[p.stem] = v if isinstance(v, str) else (v.get("sire") or v.get("name") or "")
        except Exception:
            pass
    return out


def wet_features(obs, rr, going, sires, byday, k_horse=2.0, k_sire=30.0):
    """
    重・不良への適性を特徴量にする（時系列に蓄積・先読みなし）。
      残差 e = 実際の相対パフォーマンス − 能力から期待される値（1パス目のθを使用）
      馬・父それぞれについて「重・不良での残差の縮小平均」を持ち、当日が重・不良のときだけ効かせる。
    戻り値: (n_obs, 2) 列 = [重不良 × 馬自身の道悪残差, 重不良 × 父の(道悪−良)残差]
    """
    n = len(obs["h"])
    heavy = np.array([going.get(rr[ri]["rid"], "") in ("重", "不良") for ri, _ in obs["meta"]])
    # 1パス目のθからレース内中心化した期待値を作り、残差を出す
    theta_c = np.full(n, 0.0)
    for k, (ri, e) in enumerate(obs["meta"]):
        day = byday.get(rr[ri]["dt"])
        if day is None:
            continue
        theta_c[k] = day[0][obs["h"][k]] if not np.isnan(day[0][obs["h"][k]]) else 0.0
    rid_idx = obs["r"]
    mean_by_race = np.bincount(rid_idx, weights=theta_c) / np.bincount(rid_idx)
    resid = obs["y"] - 1.4 * (theta_c - mean_by_race[rid_idx])     # 係数1.4は良馬場での回帰から（WET参照）

    order = np.argsort(obs["d"], kind="stable")
    hsum, hcnt = defaultdict(float), defaultdict(int)
    ssum, scnt = defaultdict(float), defaultdict(int)
    sgood_s, sgood_c = defaultdict(float), defaultdict(int)
    feat = np.zeros((n, 2))
    day_buf = []
    cur_day = None
    for k in order:
        d = obs["d"][k]
        if d != cur_day:                      # 同じ日の結果は当日の特徴量に入れない
            for kk, hid, sire, e, hv in day_buf:
                if hv:
                    hsum[hid] += e; hcnt[hid] += 1
                    if sire:
                        ssum[sire] += e; scnt[sire] += 1
                elif sire:
                    sgood_s[sire] += e; sgood_c[sire] += 1
            day_buf, cur_day = [], d
        ri, ent = obs["meta"][k]
        hid = ent["horse_id"]
        sire = sires.get(hid, "")
        if heavy[k]:
            feat[k, 0] = hsum[hid] / (hcnt[hid] + k_horse)
            if sire:
                feat[k, 1] = (ssum[sire] / (scnt[sire] + k_sire)) - (sgood_s[sire] / (sgood_c[sire] + k_sire))
        day_buf.append((k, hid, sire, resid[k], heavy[k]))
    print(f"  重・不良の観測 {heavy.sum()}件（{heavy.mean():.1%}）  道悪残差が入った観測 {(feat[:, 0] != 0).sum()}件")
    return feat


# ------------------------------------------------------------------ 設計行列
def build(races, surface, prevs, going=None, sires=None, byday=None):
    """観測ごとの y・馬index・レースindex・条件行列を作る"""
    rr = [r for r in races if r["surface"] == surface]
    hmap, jmap = {}, {}
    H, R, D, Y, J, X, META = [], [], [], [], [], [], []
    for ri, r in enumerate(rr):
        n = len(r["ents"])
        lvl = CLASS_LEVEL.get(r["cls"], 2)
        for e in r["ents"]:
            hid = e["horse_id"]
            META.append((ri, e))
            H.append(hmap.setdefault(hid, len(hmap)))
            R.append(ri)
            D.append(r["dt"].toordinal())
            Y.append(ND.inv_cdf((n - e["rank"] + 0.5) / n))
            J.append(jmap.setdefault(e.get("jockey") or "?", len(jmap)))
            try:
                num = int(e["horse_num"])
            except (ValueError, TypeError):
                num = (n + 1) / 2
            pos = (num - 1) / max(n - 1, 1)                     # 0=最内 1=最外
            try:
                carried = float(e["weight_carried"])
            except (ValueError, TypeError, KeyError):
                carried = 55.0
            age = int(e["age_sex"][1]) if len(e.get("age_sex", "")) >= 2 and e["age_sex"][1].isdigit() else 4
            sex = e.get("age_sex", "牡")[0]
            pv = prevs.get((hid, r["dt"]))
            if pv:
                days = (r["dt"] - pv[0]).days
                dist_ch = (r["dist"] - pv[1]) / max(pv[1], 1)
                cls_ch = lvl - pv[2]
                known = 1.0
            else:
                days, dist_ch, cls_ch, known = 60, 0.0, 0.0, 0.0
            X.append([
                pos, pos ** 2,                                   # 枠順（内外・曲線）
                carried, 1.0 if sex == "牝" else 0.0, 1.0 if sex == "セ" else 0.0,
                1.0 if age == 3 else 0.0, 1.0 if age == 4 else 0.0, 1.0 if age >= 7 else 0.0,
                known * (1.0 if days <= 21 else 0.0),            # 連闘〜3週
                known * (1.0 if 64 <= days <= 119 else 0.0),     # 2〜4か月
                known * (1.0 if 120 <= days <= 179 else 0.0),    # 4〜6か月
                known * (1.0 if days >= 180 else 0.0),           # 半年以上
                known * max(dist_ch, 0.0), known * max(-dist_ch, 0.0),   # 距離延長 / 短縮
                known * max(cls_ch, 0.0), known * max(-cls_ch, 0.0),     # 昇級 / 降級
            ])
    names = ["枠(外)", "枠(外)^2", "斤量", "牝馬", "セン馬", "3歳", "4歳", "7歳以上",
             "3週以内", "2〜4か月", "4〜6か月", "半年以上", "距離延長", "距離短縮", "昇級", "降級"]
    if going is not None:
        names += ["重不良×馬の道悪実績", "重不良×父の道悪傾向"]
    obs = {"h": np.array(H), "r": np.array(R), "d": np.array(D), "y": np.array(Y),
           "j": np.array(J), "x": np.array(X, dtype=float), "names": names, "meta": META}
    if going is not None and byday is not None:
        obs["x"] = np.column_stack([obs["x"], wet_features(obs, rr, going, sires or {}, byday)])
    have_prev = np.mean([1 if prevs.get((e["horse_id"], rr[ri]["dt"])) else 0 for ri, e in META])
    print(f"[{surface}] {len(rr)}R / 馬{len(hmap)} / 騎手{len(jmap)} / 観測{len(H)}  前走が通算成績から引けた割合 {have_prev:.0%}")
    return obs, hmap, jmap, rr


# ------------------------------------------------------------------ 同時推定
def fit(obs, as_of: int, n_h: int, n_j: int, lam=LAM, iters=3000, tol=1e-8):
    """θ（馬）・a（騎手）・β（条件）を同時に解く。戻り値: θ, W(有効走数), a, β"""
    mask = obs["d"] < as_of
    if mask.sum() == 0:
        return np.full(n_h, np.nan), np.zeros(n_h), np.zeros(n_j), np.zeros(obs["x"].shape[1])
    h, j, y = obs["h"][mask], obs["j"][mask], obs["y"][mask]
    x = obs["x"][mask]
    _, r = np.unique(obs["r"][mask], return_inverse=True)
    w = np.exp(-(as_of - obs["d"][mask]) / TAU)
    nr = int(r.max()) + 1
    cnt = np.bincount(r, minlength=nr).astype(float)
    nx = x.shape[1]
    W = np.bincount(h, weights=w, minlength=n_h)
    Wj = np.bincount(j, weights=w, minlength=n_j)

    def center(v):                       # レース内で平均を引く
        return v - (np.bincount(r, weights=v, minlength=nr) / cnt)[r]

    xc = np.column_stack([center(x[:, k]) for k in range(nx)])
    ys = (W / (W + lam))[h] * y          # 実績の少ない馬は成績を縮小（v2と同じ）
    ys = center(ys)

    # 未知数 u = [θ(n_h), a(n_j), β(nx)]
    def z_of(u):
        return u[h] + u[n_h:n_h + n_j][j] + x @ u[n_h + n_j:]

    def matvec(u):
        cz = center(z_of(u))
        wz = w * cz
        out = np.empty_like(u)
        out[:n_h] = np.bincount(h, weights=wz, minlength=n_h) - np.bincount(h, weights=w * (np.bincount(r, weights=cz, minlength=nr) / cnt)[r], minlength=n_h)
        out[n_h:n_h + n_j] = np.bincount(j, weights=wz, minlength=n_j) - np.bincount(j, weights=w * (np.bincount(r, weights=cz, minlength=nr) / cnt)[r], minlength=n_j)
        out[n_h + n_j:] = xc.T @ wz
        out[:n_h] += A.EPS * u[:n_h]
        out[n_h:n_h + n_j] += L2_JOCKEY * u[n_h:n_h + n_j]
        out[n_h + n_j:] += L2_DENSE * u[n_h + n_j:]
        return out

    b = np.concatenate([np.bincount(h, weights=w * ys, minlength=n_h),
                        np.bincount(j, weights=w * ys, minlength=n_j),
                        xc.T @ (w * ys)])
    diag = np.concatenate([W + A.EPS, Wj + L2_JOCKEY, (xc ** 2 * w[:, None]).sum(axis=0) + L2_DENSE])
    u = np.zeros(n_h + n_j + nx)
    res = b - matvec(u)
    z = res / diag
    p = z.copy()
    rz = res @ z
    bn = np.sqrt(b @ b) + 1e-12
    for _ in range(iters):
        Ap = matvec(p)
        al = rz / (p @ Ap)
        u += al * p
        res -= al * Ap
        if np.sqrt(res @ res) / bn < tol:
            break
        z = res / diag
        rz2 = res @ z
        p = z + (rz2 / rz) * p
        rz = rz2
    theta, a, beta = u[:n_h].copy(), u[n_h:n_h + n_j].copy(), u[n_h + n_j:].copy()
    seen = W > 0
    theta[seen] -= np.average(theta[seen], weights=W[seen])
    theta[~seen] = np.nan
    return theta, W, a, beta


def walk_forward(obs, hmap, jmap, rr):
    """開催日ごとに再推定し {日付: (θ, W, 騎手効果a, 条件係数β)} を返す（評価日より前のみ使用）"""
    out, last = {}, None
    days = sorted({r["dt"] for r in rr if r["dt"] >= A.EVAL_START})
    for dt in days:
        last = fit(obs, dt.toordinal(), len(hmap), len(jmap))
        out[dt] = last
    return out, last


def main():
    races = A.load_races()
    prevs = prev_map()
    print(f"レース {len(races)}R / 通算成績 {len(list(FULL_DIR.glob('*.json')))}頭ぶん")

    rows = []
    coef_report = {}
    going, sires = going_map(races), sire_map()
    for surface in ("芝", "ダ"):
        obs0, hmap, jmap, rr = build(races, surface, prevs)          # 1パス目（道悪特徴量なし）
        byday0, _ = walk_forward(obs0, hmap, jmap, rr)
        obs, hmap, jmap, rr = build(races, surface, prevs, going, sires, byday0)   # 2パス目
        byday, last = walk_forward(obs, hmap, jmap, rr)
        theta_f, W_f, a_f, beta_f = last
        coef_report[surface] = (dict(zip(obs["names"], beta_f)), a_f, jmap)
        for k, (ri, e) in enumerate(obs["meta"]):
            r = rr[ri]
            if r["dt"] not in byday or r["cls"] == "新馬" or not e.get("odds"):
                continue
            theta, W, a, beta = byday[r["dt"]]
            j = hmap[e["horse_id"]]
            rows.append({"rid": r["rid"], "dt": r["dt"], "cls": r["cls"], "surface": surface,
                         "馬名": e["horse_name"], "rank": e["rank"], "odds": e["odds"], "pop": e["popularity"],
                         "v3": theta[j] if W[j] > 0 else np.nan,
                         "ctx": a[obs["j"][k]] + obs["x"][k] @ beta,
                         "wet": float(obs["x"][k][-2:] @ beta[-2:]),      # 重不良×(馬の道悪実績, 父の道悪傾向)
                         "jockey": float(a[obs["j"][k]])})
    df = pd.DataFrame(rows)
    ok = df.groupby("rid")["v3"].transform(lambda s: s.notna().mean()) >= 0.6
    df = df[ok].copy()
    for c in ("v3", "ctx", "wet", "jockey"):
        m = df.groupby("rid")[c].transform("mean")
        df[c + "_c"] = (df[c].fillna(m) - m).fillna(0.0)
    df["v3_full"] = df["v3_c"] + df["ctx_c"]
    imp = 1.0 / df["odds"]
    df["log_mkt"] = np.log(imp / imp.groupby(df["rid"]).transform("sum"))
    df["実着順"] = df["rank"]

    print("\n===== 推定された条件効果（値は着順の標準化スケール。+ほど好走方向）=====")
    for surface in ("芝", "ダ"):
        beta, a, jmap = coef_report[surface]
        print(f"[{surface}] " + " / ".join(f"{k}{v:+.3f}" for k, v in beta.items()))
        inv = {v: k for k, v in jmap.items()}
        top = np.argsort(-a)[:6]
        bot = np.argsort(a)[:3]
        print(f"     騎手 上位: " + ", ".join(f"{inv[i]}{a[i]:+.2f}" for i in top))
        print(f"     騎手 下位: " + ", ".join(f"{inv[i]}{a[i]:+.2f}" for i in bot))

    print("\n===== 予測力（テスト2025/07〜・レース内softmax）=====")
    for cols, lab in [(["log_mkt"], "市場のみ"), (["v3_c"], "θ_v3（能力のみ）"), (["v3_full"], "θ_v3＋条件効果"),
                      (["v3_c", "ctx_c"], "θ_v3＋条件(重み学習)"), (["log_mkt", "v3_full"], "市場＋v3")]:
        r = _eval(df, cols, lab)
        print(f"  {lab:<22} n={r['n']} logloss={r['logloss']:.4f} 1位勝率{r['win']:.1%} 複勝率{r['place']:.1%} 単ROI{r['roi']:.0%}  w={r['w']}")
    out = BASE / "data" / "v3_eval.parquet"
    try:
        df.to_parquet(out)
        print(f"\n評価用データを保存: {out}")
    except Exception:
        df.to_csv(out.with_suffix(".csv"), index=False)
        print(f"\n評価用データを保存: {out.with_suffix('.csv')}")


def _eval(df, cols, label):
    tr, te = df[df.dt < pd.Timestamp(2025, 7, 1)], df[df.dt >= pd.Timestamp(2025, 7, 1)]
    mu, sd = tr[cols].mean(), tr[cols].std() + 1e-9
    if "log_mkt" in cols:
        mu["log_mkt"], sd["log_mkt"] = 0.0, 1.0
    _, utr = np.unique(tr.rid, return_inverse=True)
    rte, ute = np.unique(te.rid, return_inverse=True)
    w = M.fit(((tr[cols] - mu) / sd).values, (tr["rank"] == 1).values.astype(float), utr, utr.max() + 1, l2=0.5, iters=1000)
    p = M.predict(((te[cols] - mu) / sd).values, w, ute, len(rte))
    d = te.assign(p=p)
    top = d.loc[d.groupby("rid")["p"].idxmax()]
    return {"n": len(rte), "logloss": -np.log(d.loc[d["rank"] == 1, "p"]).mean(),
            "win": (top["rank"] == 1).mean(), "place": (top["rank"] <= 3).mean(),
            "roi": (top["odds"] * (top["rank"] == 1)).mean(), "w": dict(zip(cols, np.round(w, 3)))}


if __name__ == "__main__":
    main()
