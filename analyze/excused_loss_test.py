"""
「理由のある負け」を採点に入れられるか（2026-10-24）

実戦で「前走の負けに理由があり、そこまで割り引かなくていい馬」を手で拾った（休み明け・距離・道悪・馬体重・出遅れ）。
これを採点に入れる前に、事前に決めた定義で3段階を検証する。学習〜2025/06・テスト2025/07〜。
  ① 確認: 前走6着以下で理由あり（horse_notes.excuse_reasons と同じ定義＋「近4走に3着内か0.5秒差内がある」）の馬を、
     案Gが過小評価しているか（3着内率 − 案G見込み〈頭数帯×案G順位〉）、人気比も併記
  ② 案Gの第4変数として足す（重みは〜2025/06で学習）
  ③ 能力指数v3の計算で、理由のある凡走（その走が休み明け・道悪・距離±400m・芝ダ替わり・昇級・出遅れ・馬体重±15kg）の
     評価 y（負の値）を 0.5倍 / 0倍 に弱めて推定し直し、案G 3変数で比べる
合格: 買い条件（10〜13頭・重賞以外）の三連複1軸6点・馬連5頭BOXが、学習・テスト両期間で現行を上回り、上位3件除外でも下がらない。
使い方: python3 analyze/excused_loss_test.py
"""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import ability_index as A
import ability_index_v3 as V
import front_ace_blend_test as FA
import ability_blend_backtest as B
import comeback_test as CB
TRAIN_END = FA.TRAIN_END
CUR_LVL = {"2勝クラス": 2, "3勝クラス": 3, "OP": 4, "重賞": 5}


def load_hist():
    """horse_id → 走の一覧（古い順）。馬体重増減つき"""
    out = {}
    for p in (BASE / "cache" / "horse_full_history").glob("*.json"):
        rows = []
        for r in json.loads(p.read_text()):
            m = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
            dm = re.match(r"^(芝|ダ|障)(\d+)", r.get("dist_raw", ""))
            if not m or not dm or not str(r.get("pos_raw", "")).isdigit(): continue
            fld = int(r["field"]) if str(r.get("field", "")).isdigit() else 0
            c1 = str(r.get("corner", "")).split("-")[0]
            try: mg = float(r.get("margin", ""))
            except ValueError: mg = np.nan
            w = re.search(r"\(([+-]?\d+)\)", str(r.get("weight", "")))
            rows.append(dict(dt=pd.Timestamp(*map(int, m.groups())), pos=int(r["pos_raw"]), mg=mg, surf=dm.group(1),
                             dist=int(dm.group(2)), track=r.get("track", ""), lvl=CB.lvl(r.get("race_raw", "")),
                             wd=int(w.group(1)) if w else None, c1r=(int(c1) / fld) if c1.isdigit() and fld else np.nan))
        out[p.stem] = sorted([x for x in rows if x["surf"] != "障"], key=lambda x: x["dt"])
    return out


def run_reasons(h, k):
    """h[k] の走そのものに付く理由（③用・その走の前の情報だけで判定）"""
    p, prior = h[k], h[:k]
    rs = []
    usual = [x["c1r"] for x in prior[-5:] if not np.isnan(x["c1r"])]
    if not np.isnan(p["c1r"]) and usual and p["c1r"] - np.mean(usual) >= 0.3: rs.append("出遅れ")
    if p["track"] in ("重", "不"): rs.append("道悪")
    if p["wd"] is not None and abs(p["wd"]) >= 15: rs.append("馬体重")
    if prior:
        q = prior[-1]
        if (p["dt"] - q["dt"]).days >= 120: rs.append("休み明け")
        if abs(p["dist"] - q["dist"]) >= 400: rs.append("距離")
        if p["surf"] != q["surf"]: rs.append("芝ダ替わり")
        if p["lvl"] > q["lvl"]: rs.append("昇級")
    return rs


def prev_reasons(h, dt, surf, dist, cur_lvl):
    """今回(dt)から見た前走の理由（①②用・horse_notes.excuse_reasons と同じ定義）。戻り値 (前走着順, 理由, ふだん走れているか)"""
    hh = [x for x in h if x["dt"] < dt]
    if not hh: return None, [], False
    p, prior = hh[-1], hh[:-1]
    rs = []
    usual = [x["c1r"] for x in prior[-5:] if not np.isnan(x["c1r"])]
    if not np.isnan(p["c1r"]) and usual and p["c1r"] - np.mean(usual) >= 0.3: rs.append("出遅れ・位置取り負け")
    if p["track"] in ("重", "不"): rs.append("道悪")
    if abs(p["dist"] - dist) >= 400: rs.append("距離±400m")
    if p["surf"] != surf: rs.append("芝ダ替わり")
    if min(p["lvl"], 5) > min(cur_lvl, 5): rs.append("格上")
    if prior and (p["dt"] - prior[-1]["dt"]).days >= 120: rs.append("休み明け")
    if p["wd"] is not None and abs(p["wd"]) >= 15: rs.append("馬体重±15kg")
    if p["surf"] == surf and 200 <= abs(p["dist"] - dist) < 400:
        if any(x["surf"] == surf and abs(x["dist"] - dist) <= 100 and x["pos"] <= 3 for x in prior): rs.append("得意距離外")
    close = any(x["pos"] <= 3 or (not np.isnan(x["mg"]) and x["mg"] <= 0.5) for x in prior[-4:])
    return p["pos"], rs, close


def estimate(factor, races, prevs, going, sires, H):
    """理由のある凡走の y を factor 倍にして v3 を推定。戻り値: 馬名×日付→θ"""
    tab = []
    for surface in ("芝", "ダ"):
        def adj(obs, rr):
            if factor == 1.0: return 0
            y = obs["y"].copy(); n = 0
            for k, (ri, e) in enumerate(obs["meta"]):
                if y[k] >= 0: continue
                h = H.get(e["horse_id"])
                if not h: continue
                dt = pd.Timestamp(rr[ri]["dt"])
                idx = next((i for i, x in enumerate(h) if x["dt"] == dt), None)
                if idx is not None and run_reasons(h, idx):
                    y[k] *= factor; n += 1
            obs["y"] = y
            return n
        obs0, hmap, jmap, rr = V.build(races, surface, prevs)
        n = adj(obs0, rr)
        byday0, _ = V.walk_forward(obs0, hmap, jmap, rr)
        obs, hmap, jmap, rr = V.build(races, surface, prevs, going, sires, byday0)
        adj(obs, rr)
        byday, _ = V.walk_forward(obs, hmap, jmap, rr)
        print(f"   [{surface}] 弱めた凡走 {n}件 / 観測{len(obs['y'])}", flush=True)
        for ri, e in obs["meta"]:
            r = rr[ri]
            if r["dt"] not in byday: continue
            theta, W, a, beta = byday[r["dt"]]
            j = hmap[e["horse_id"]]
            tab.append({"馬名": e["horse_name"], "dt": r["dt"], "v3": theta[j] if W[j] > 0 else np.nan})
    tab = pd.DataFrame(tab)
    return tab[~tab.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])["v3"]


def rank_with(df, cols):
    u, w = B.fit_util(df, cols, 0.5)
    return pd.Series(-u, index=df.index).groupby(df["rid"]).rank(method="first"), w


def main():
    races = A.load_races()
    prevs, going, sires = V.prev_map(), V.going_map(races), V.sire_map()
    H = load_hist()
    id2name = {}
    for p in (BASE / "cache" / "race_result").glob("*.json"):
        for e in json.loads(p.read_text()).get("entries", []):
            if e.get("horse_id"): id2name.setdefault(e.get("horse_name", ""), e["horse_id"])
    base = FA.build()
    pays = FA.payouts()

    # 現行の v3 を同じ手順で作り直す（比較の土台をそろえる）
    res = {}
    for factor, lab in ((1.0, "現行（着順のまま）"), (0.5, "理由ある凡走を0.5倍"), (0.0, "理由ある凡走を数えない")):
        print(f"[推定] {lab}", flush=True)
        tab = estimate(factor, races, prevs, going, sires, H)
        df = base.copy()
        v = df.join(tab.rename("v3n"), on=["馬名", "dt"])["v3n"]
        m = v.groupby(df["rid"]).transform("mean")
        df["v3_c"] = (v.fillna(m) - m).fillna(0.0)
        res[lab] = df

    # ① 確認・② 第4変数（現行v3の上で）
    df = res["現行（着順のまま）"]
    df["r"], w0 = rank_with(df, ["v3_c", "rest_sum", "ace"])
    surf = np.where(df["コース"].astype(str).str.startswith("芝"), "芝", "ダ")
    dist = df["距離"].astype(str).str.extract(r"(\d+)")[0].astype(float).values
    lvl = df["クラス"].map(CUR_LVL).fillna(2).values
    pp, rs, cl = [], [], []
    for i, (nm, dt) in enumerate(zip(df["馬名"], df["dt"])):
        a, b, c = prev_reasons(H.get(id2name.get(nm), []), dt, surf[i], dist[i], lvl[i])
        pp.append(a); rs.append(b); cl.append(c)
    df["ppos"], df["rs"], df["close"] = pp, rs, cl
    df["top3"] = (df["実着順"].astype(float) <= 3).astype(float)
    df["nbin"] = pd.cut(df["出走頭数"].astype(int), [0, 9, 13, 15, 18])
    df["pop"] = df["市場人気"].astype(float)
    df["expG"] = df.groupby(["nbin", "r"], observed=True)["top3"].transform("mean")
    df["expP"] = df.groupby(["nbin", "pop"], observed=True)["top3"].transform("mean")
    df["win"] = np.where(df["実着順"].astype(float) == 1, df["単勝オッズ"].astype(float) * 100, 0.0)
    loss = df["ppos"].fillna(0) >= 6
    has = df["rs"].apply(len) > 0
    df["exc"] = (loss & has & df["close"]).astype(float)

    def line(x, lab):
        if len(x) < 60:
            print(f"   {lab:<34} n={len(x):>5}（少数）"); return
        tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
        g = lambda y, c: (y.top3.mean() - y[c].mean()) * 100
        okG = g(tr, "expG") > 0 and g(te, "expG") > 0
        print(f"   {lab:<34} n={len(x):>5} 3着内{x.top3.mean()*100:5.1f}% 案G比{g(x,'expG'):+5.1f}（{g(tr,'expG'):+5.1f}/{g(te,'expG'):+5.1f}）{'◎' if okG else '  '}"
              f" 人気比{g(x,'expP'):+5.1f}（{g(tr,'expP'):+5.1f}/{g(te,'expP'):+5.1f}） 単勝{x.win.mean():4.0f}%")

    print("\n■ ① 前走6着以下の馬（2勝以上・全頭数）  ※案G比/人気比 = 3着内率 − 見込み(pt)（学習/テスト）◎=案G比が両期間プラス")
    for scope, s in (("全馬", df), ("案G 1〜3位", df[df.r <= 3]), ("案G 4〜6位", df[df.r.between(4, 6)]), ("案G 7位以下", df[df.r >= 7])):
        print(f"  [{scope}]")
        x = s[loss.loc[s.index]]
        line(x, "前走6着以下 全体")
        line(x[x.exc == 1], "理由あり・ふだん走れている（表示の定義）")
        line(x[has.loc[x.index] & ~x["close"]], "理由あり・大敗続き")
        line(x[x.rs.apply(len) == 0], "理由なし")
    print("  [全馬・理由別（表示の定義のうち）]")
    x = df[df.exc == 1]
    for k in ("出遅れ・位置取り負け", "道悪", "距離±400m", "芝ダ替わり", "格上", "休み明け", "馬体重±15kg", "得意距離外"):
        line(x[x.rs.apply(lambda r: k in r)], k)
    b = df[df["出走頭数"].astype(int).between(10, 13) & (df["クラス"] != "重賞")]
    print("  [買い条件内（10〜13頭・重賞以外）]")
    line(b[b.exc == 1], "理由あり・ふだん走れている")
    line(b[(b.exc == 1) & (b.r <= 5)], "  うち案G 1〜5位")
    line(b[(b.exc == 1) & (b.r >= 6)], "  うち案G 6位以下")

    print("\n■ ②③ 順位づけを替えたときの成績（ROI（学習/テスト）・除3=上位3件除外）")
    variants = [("G 現行（v3+能力以外+巧者）", res["現行（着順のまま）"], ["v3_c", "rest_sum", "ace"]),
                ("② G+理由ある負け", df, ["v3_c", "rest_sum", "ace", "exc"]),
                ("③ v3で理由ある凡走を0.5倍", res["理由ある凡走を0.5倍"], ["v3_c", "rest_sum", "ace"]),
                ("③ v3で理由ある凡走を数えない", res["理由ある凡走を数えない"], ["v3_c", "rest_sum", "ace"])]
    out = []
    for lab, d, cols in variants:
        d = d.copy()
        d["rk"], w = rank_with(d, cols)
        e = FA.evaluate(d, "rk", pays)
        out.append((lab, w, e))
        print(f"   {lab}: 重み {w}", flush=True)
    for title, f in (("買い条件（10〜13頭・重賞以外）", lambda e: e[e.n.between(10, 13) & ~e.g]),
                     ("2勝以上 重賞以外 全頭数", lambda e: e[~e.g])):
        print(f"\n  [{title}]")
        for lab, w, e in out:
            FA.report(f(e).reset_index(drop=True), lab)


if __name__ == "__main__":
    main()
