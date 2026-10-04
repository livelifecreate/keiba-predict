"""
「能力上位×前走大敗」の掘り下げ（2026-10-04）

recency_bias_test.py で、案G上位3頭×前走10着以下が人気期待より3着内+4.2pt（学習/テストとも）と出た。
大敗の理由（事前に決めた6区分＋理由なし）で分け、市場がどの大敗を過剰に割り引いているかを調べる。
期待値＝同じ頭数帯×同じ人気の平均。単勝・複勝の回収率は実払戻。学習(〜2025/06)/テスト別。
使い方: python3 analyze/comeback_test.py
"""
import json, re, sys
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M, ability_blend_backtest as B, verify.bet_analysis2 as ba2
TRAIN_END = pd.Timestamp(2025, 7, 1)
CUR_LVL = {"2勝": 2, "3勝": 3, "OP": 4, "重賞": 5}


def lvl(race_raw: str) -> int:
    s = race_raw or ""
    if re.search(r"\((GI|G1|JpnI|GII|G2|JpnII|GIII|G3|JpnIII)\)", s): return 5
    if re.search(r"\((L|OP)\)", s) or "オープン" in s: return 4
    if "3勝" in s or "1600万" in s: return 3
    if "2勝" in s or "1000万" in s: return 2
    if "1勝" in s or "500万" in s: return 1
    return 0


def histories():
    id2name = {}
    for p in (BASE / "cache" / "race_result").glob("*.json"):
        for e in json.loads(p.read_text()).get("entries", []):
            if e.get("horse_id"): id2name[e["horse_id"]] = e.get("horse_name", "")
    out = {}
    for p in (BASE / "cache" / "horse_full_history").glob("*.json"):
        nm = id2name.get(p.stem)
        if not nm: continue
        rows = []
        for r in json.loads(p.read_text()):
            m = re.match(r"(\d{4})/(\d{2})/(\d{2})", r.get("date_raw", ""))
            dm = re.match(r"^(芝|ダ|障)(\d+)", r.get("dist_raw", ""))
            if not m or not dm or not str(r.get("pos_raw", "")).isdigit(): continue
            fld = int(r["field"]) if str(r.get("field", "")).isdigit() else 0
            c1 = str(r.get("corner", "")).split("-")[0]
            try: mg = float(r.get("margin", ""))
            except ValueError: mg = np.nan
            rows.append(dict(dt=pd.Timestamp(*map(int, m.groups())), pos=int(r["pos_raw"]), fld=fld, mg=mg,
                             surf=dm.group(1), dist=int(dm.group(2)), track=r.get("track", ""), lvl=lvl(r.get("race_raw", "")),
                             c1r=(int(c1) / fld) if c1.isdigit() and fld else np.nan))
        out[nm] = sorted(rows, key=lambda x: x["dt"])
    return out


def main():
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"]); m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)
    u, _ = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["rank_G"] = df.assign(u=u).groupby("rid")["u"].rank(ascending=False, method="first")
    df["pop"] = df["市場人気"].astype(float)
    df["top3"] = (df["実着順"].astype(float) <= 3).astype(float)
    df["win"] = np.where(df["実着順"].astype(float) == 1, df["単勝オッズ"].astype(float) * 100, 0.0)
    df["nbin"] = pd.cut(df["出走頭数"].astype(int), [0, 12, 15, 18])
    df["exp3"] = df.groupby(["nbin", "pop"], observed=True)["top3"].transform("mean")

    # 複勝の払戻
    rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}
    fk = {}
    for key in df[["日付", "レース名"]].drop_duplicates().itertuples(index=False):
        rid = rid_of.get(tuple(key))
        if rid:
            nums, am = ba2.get_payout(rid, "複勝")
            if am and len(nums) >= len(am):
                fk[tuple(key)] = dict(zip(nums[:len(am)], am))
    df["has_fk"] = [(a, b) in fk for a, b in zip(df["日付"], df["レース名"])]
    df["place"] = [fk.get((a, b), {}).get(int(n), 0) for a, b, n in zip(df["日付"], df["レース名"], df["馬番"])]
    df["expP"] = df[df.has_fk].groupby(["nbin", "pop"], observed=True)["place"].transform("mean")

    H = histories()
    cur_surf = np.where(df["コース"].astype(str).str.startswith("芝"), "芝", "ダ")
    cur_dist = df["距離"].astype(str).str.extract(r"(\d+)")[0].astype(float).values
    cur_lvl = df["クラス"].map(CUR_LVL).fillna(2).values
    recs = []
    for i, (nm, dt) in enumerate(zip(df["馬名"], df["dt"])):
        h = [x for x in H.get(nm, []) if x["dt"] < dt and x["surf"] != "障"]
        if not h:
            recs.append(None); continue
        p = h[-1]
        prior = h[:-1]
        usual = np.nanmean([x["c1r"] for x in prior[-5:]]) if prior else np.nan
        reasons = []
        if not np.isnan(p["c1r"]) and not np.isnan(usual) and p["c1r"] - usual >= 0.3: reasons.append("出遅れ・位置取り負け")
        if p["track"] in ("重", "不"): reasons.append("道悪")
        if abs(p["dist"] - cur_dist[i]) >= 400: reasons.append("距離（±400m以上）")
        if p["surf"] != cur_surf[i]: reasons.append("芝ダ替わり")
        if p["lvl"] > cur_lvl[i]: reasons.append("格上（前走が上のクラス）")
        if prior and (p["dt"] - prior[-1]["dt"]).days >= 120: reasons.append("前走が休み明け")
        recs.append(dict(pos=p["pos"], mg=p["mg"], reasons=reasons))
    df["prev"] = recs
    df["bigloss"] = [bool(r) and r["pos"] >= 10 for r in recs]
    df["reasons"] = [r["reasons"] if r else [] for r in recs]

    def line(x, lab):
        if len(x) < 40:
            print(f"  {lab:<26} n={len(x):>4}（少数）"); return
        tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
        d3 = lambda y: (y.top3.mean() - y.exp3.mean()) * 100
        y = x[x.has_fk]
        print(f"  {lab:<26} n={len(x):>4} 3着内{x.top3.mean()*100:5.1f}% 人気比{d3(x):+5.1f}（学習{d3(tr):+5.1f}/テスト{d3(te):+5.1f}）"
              f" 単勝ROI{x.win.mean():4.0f}%（{tr.win.mean():.0f}/{te.win.mean():.0f}）"
              f" 複勝ROI{y.place.mean():4.0f}%（{y[y.dt<TRAIN_END].place.mean():.0f}/{y[y.dt>=TRAIN_END].place.mean():.0f}・人気期待{y.expP.mean():.0f}%）")

    reasons = ["出遅れ・位置取り負け", "道悪", "距離（±400m以上）", "芝ダ替わり", "格上（前走が上のクラス）", "前走が休み明け"]
    for scope, s in (("案G上位3頭", df[df.rank_G <= 3]), ("全馬（参考）", df)):
        b = s[s.bigloss]
        print(f"\n■ {scope} × 前走10着以下")
        line(s, "（参考）この範囲の全体")
        line(b, "前走10着以下 全体")
        for rs in reasons:
            line(b[b.reasons.apply(lambda r: rs in r)], rs)
        line(b[b.reasons.apply(len) == 0], "理由なし")
        line(b[b.reasons.apply(len) > 0], "理由あり（いずれか）")
    s = df[(df.rank_G <= 3) & df["出走頭数"].astype(int).between(10, 13) & (df["クラス"] != "重賞")]
    print("\n■ 買い条件内（10〜13頭・重賞以外）の案G上位3頭")
    line(s[s.bigloss], "前走10着以下")
    line(s[s.bigloss & (s.reasons.apply(len) > 0)], "前走10着以下・理由あり")


if __name__ == "__main__":
    main()
