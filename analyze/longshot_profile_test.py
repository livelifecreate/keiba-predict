"""
5番人気以下で3着内に来る馬の共通点（2026-10-05）

「来た穴馬」だけを見ると見かけの共通点が出るので、5番人気以下の全馬（2勝以上）を対象に、
事前に固定した条件ごとに「3着内率 − 人気見込み（同じ頭数帯×同じ人気の平均）」を学習(〜2025/06)/テスト別に出す。
両期間とも見込みを上回った条件だけを残し、単勝・複勝の回収率（上位3件除外つき）を見る。
最後に、残った条件どうし・案G上位との重ね合わせを確認する（重ね合わせは結果を見る前に下の COMBOS で固定）。
使い方: python3 analyze/longshot_profile_test.py
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bigloss_course_front_test as BF
import comeback_test as CB
TRAIN_END = CB.TRAIN_END


def add_history(df):
    H = CB.histories()
    cur_dist = df["距離"].astype(str).str.extract(r"(\d+)")[0].astype(float).values
    cur_surf = np.where(df["コース"].astype(str).str.startswith("芝"), "芝", "ダ")
    cur_lvl = df["クラス"].map(CB.CUR_LVL).fillna(2).values
    cols = {k: [] for k in ("d_dist", "gap", "gap2", "p_pos", "p_mg", "p_fld", "reasons")}
    for i, (nm, dt) in enumerate(zip(df["馬名"], df["dt"])):
        h = [x for x in H.get(nm, []) if x["dt"] < dt and x["surf"] != "障"]
        if not h:
            for k in cols: cols[k].append([] if k == "reasons" else np.nan)
            continue
        p = h[-1]
        prior = h[:-1]
        usual = np.nanmean([x["c1r"] for x in prior[-5:]]) if prior else np.nan
        rs = []   # comeback_test.py と同じ大敗理由の定義
        if not np.isnan(p["c1r"]) and not np.isnan(usual) and p["c1r"] - usual >= 0.3: rs.append("出遅れ・位置取り負け")
        if p["track"] in ("重", "不"): rs.append("道悪")
        if abs(p["dist"] - cur_dist[i]) >= 400: rs.append("距離（±400m以上）")
        if p["surf"] != cur_surf[i]: rs.append("芝ダ替わり")
        if p["lvl"] > cur_lvl[i]: rs.append("格上（前走が上のクラス）")
        if prior and (p["dt"] - prior[-1]["dt"]).days >= 120: rs.append("前走が休み明け")
        cols["reasons"].append(rs)
        cols["d_dist"].append(cur_dist[i] - p["dist"])
        cols["gap"].append((dt - p["dt"]).days)
        cols["gap2"].append((p["dt"] - h[-2]["dt"]).days if len(h) >= 2 else np.nan)
        cols["p_pos"].append(p["pos"]); cols["p_mg"].append(p["mg"]); cols["p_fld"].append(p["fld"])
    for k, v in cols.items():
        df[k] = v
    df["bigloss"] = df["p_pos"] >= 10
    return df


def conditions(d):
    rs = d["reasons"]
    return {
        "案G 1〜3位": d.rank_G <= 3,
        "案G 4〜5位": d.rank_G.between(4, 5),
        "巻き返し（前走10着以下・理由あり）": d.bigloss & rs.apply(len).gt(0),
        "コース巧者": d.ace.astype(bool),
        "先行": d.front.astype(bool),
        "先行×先行馬2頭以下": d.front.astype(bool) & d.few_front.astype(bool),
        "距離延長（+200m以上）": d.d_dist >= 200,
        "距離短縮（-200m以上）": d.d_dist <= -200,
        "休み明け（中90日以上）": d.gap >= 90,
        "叩き2戦目": (d.gap2 >= 90) & (d.gap < 90),
        "前走3着以内": d.p_pos <= 3,
        "前走6着以下だが0.5秒差以内": (d.p_pos >= 6) & (d.p_mg <= 0.5),
        "前走3秒以上の大差負け": d.p_mg >= 3.0,
        "前走が上のクラス": rs.apply(lambda r: "格上（前走が上のクラス）" in r),
        "芝ダ替わり": rs.apply(lambda r: "芝ダ替わり" in r),
    }


COMBOS = {
    "案G 1〜3位 × 前走6着以下0.5秒差内": ("案G 1〜3位", "前走6着以下だが0.5秒差以内"),
    "案G 1〜3位 × コース巧者": ("案G 1〜3位", "コース巧者"),
    "案G 1〜3位 × 先行": ("案G 1〜3位", "先行"),
    "案G 1〜5位 × 距離短縮": ("案G 1〜5位", "距離短縮（-200m以上）"),
    "コース巧者 × 先行": ("コース巧者", "先行"),
}


def line(x, lab):
    if len(x) < 60:
        print(f"   {lab:<34} n={len(x):>5}（少数）"); return None
    tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
    d3 = lambda y: (y.top3.mean() - y.exp3.mean()) * 100
    y = x[x.has_fk]
    pl = y.place
    ex3 = pl.drop(pl.nlargest(3).index).mean()
    ok = d3(tr) > 0 and d3(te) > 0
    print(f"   {lab:<34} n={len(x):>5} 3着内{x.top3.mean()*100:5.1f}% 人気比{d3(x):+5.1f}（{d3(tr):+5.1f}/{d3(te):+5.1f}）{'◎' if ok else '  '}"
          f" 単勝{x.win.mean():4.0f}%（{tr.win.mean():.0f}/{te.win.mean():.0f}）"
          f" 複勝{pl.mean():4.0f}%（{y[y.dt<TRAIN_END].place.mean():.0f}/{y[y.dt>=TRAIN_END].place.mean():.0f}・除3 {ex3:.0f}・見込み{y.expP.mean():.0f}%）")
    return ok


def main():
    df = add_history(BF.build())
    for scope, d in (("5番人気以下（2勝以上）", df[df["pop"] >= 5]),
                     ("5〜9番人気", df[df["pop"].between(5, 9)]),
                     ("5番人気以下・買い条件内（10〜13頭・重賞以外）", df[(df["pop"] >= 5) & df["出走頭数"].astype(int).between(10, 13) & (df["クラス"] != "重賞")])):
        print(f"\n■ {scope}   ※人気比=3着内率−人気見込み(pt)（学習/テスト）◎=両期間プラス / 回収率（学習/テスト・除3=上位3件除外）")
        line(d, "（参考）全体")
        cs = conditions(d)
        cs["案G 1〜5位"] = d.rank_G <= 5
        for lab, mask in cs.items():
            line(d[mask.fillna(False).astype(bool)], lab)
        print("   --- 重ね合わせ（事前に固定）---")
        for lab, (a, b) in COMBOS.items():
            line(d[(cs[a] & cs[b]).fillna(False).astype(bool)], lab)


if __name__ == "__main__":
    main()
