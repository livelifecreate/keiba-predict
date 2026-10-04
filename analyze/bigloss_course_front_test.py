"""
京都大賞典（エコロディノス・15番人気1着）から出た2つの仮説の検証（2026-10-04）

H1 異常な大差負け: 直近3走以内に勝ち馬から3.0秒以上の負けがある馬を、案Gは過小評価しているか
   （比較: 1.5〜3.0秒差の負けあり / どちらもなし）
H2 コース巧者の先行馬 × 前に行く馬が少ない:
   先行 = 近5走の1角位置÷頭数の平均 ≤ 0.35 / 巧者 = 同じ場×芝ダで2走以上・3着内率50%以上 /
   先行少 = そのレースの先行馬が2頭以下
期待値: 案G見込み＝同じ頭数帯×同じ案G順位の平均3着内率、人気見込み＝同じ頭数帯×同じ人気の平均。学習/テスト別。
使い方: python3 analyze/bigloss_course_front_test.py
"""
import json, re, sys, textwrap
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import comeback_test as CB
TRAIN_END = CB.TRAIN_END


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
            dm = re.match(r"^(芝|ダ)(\d+)", r.get("dist_raw", ""))
            if not m or not dm or not str(r.get("pos_raw", "")).isdigit(): continue
            fld = int(r["field"]) if str(r.get("field", "")).isdigit() else 0
            c1 = str(r.get("corner", "")).split("-")[0]
            try: mg = float(r.get("margin", ""))
            except ValueError: mg = np.nan
            rows.append(dict(dt=pd.Timestamp(*map(int, m.groups())), pos=int(r["pos_raw"]), mg=mg, surf=dm.group(1),
                             venue=re.sub(r"\d", "", r.get("kaisan", "")),
                             c1r=(int(c1) / fld) if c1.isdigit() and fld else np.nan))
        out[nm] = sorted(rows, key=lambda x: x["dt"])
    return out


def build():
    src = open(Path(__file__).resolve().parent / "comeback_test.py", encoding="utf-8").read()
    body = src.split("def main():")[1].split("    H = histories()")[0]
    ns = dict(vars(CB)); exec(textwrap.dedent(body), ns)
    df = ns["df"]
    df["expG"] = df.groupby(["nbin", "rank_G"], observed=True)["top3"].transform("mean")
    H = histories()
    surf = np.where(df["コース"].astype(str).str.startswith("芝"), "芝", "ダ")
    f_big, f_mid, front, ace = [], [], [], []
    for i, (nm, dt, ven) in enumerate(zip(df["馬名"], df["dt"], df["競馬場"])):
        h = [x for x in H.get(nm, []) if x["dt"] < dt]
        l3 = h[-3:]
        f_big.append(any(x["mg"] >= 3.0 for x in l3 if not np.isnan(x["mg"])))
        f_mid.append(any(1.5 <= x["mg"] < 3.0 for x in l3 if not np.isnan(x["mg"])))
        c = [x["c1r"] for x in h[-5:] if not np.isnan(x["c1r"])]
        front.append(np.mean(c) <= 0.35 if len(c) >= 2 else np.nan)
        here = [x for x in h if x["venue"] == ven and x["surf"] == surf[i]]
        ace.append(len(here) >= 2 and np.mean([x["pos"] <= 3 for x in here]) >= 0.5)
    df["big"], df["mid"], df["ace"] = f_big, f_mid, ace
    df["front"] = pd.array(front, dtype="boolean").fillna(False).astype(bool)
    df["n_front"] = df.groupby("rid")["front"].transform("sum")
    df["few_front"] = df["n_front"] <= 2
    return df


def main():
    df = build()

    def line(x, lab):
        if len(x) < 40:
            print(f"  {lab:<34} n={len(x):>4}（少数）"); return
        tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
        dG = lambda y: (y.top3.mean() - y.expG.mean()) * 100
        dM = lambda y: (y.top3.mean() - y.exp3.mean()) * 100
        y = x[x.has_fk]
        print(f"  {lab:<34} n={len(x):>5} 3着内{x.top3.mean()*100:5.1f}% 案G比{dG(x):+5.1f}（学習{dG(tr):+5.1f}/テスト{dG(te):+5.1f}）"
              f" 人気比{dM(x):+5.1f}（{dM(tr):+.1f}/{dM(te):+.1f}） 単勝ROI{x.win.mean():4.0f}% 複勝ROI{y.place.mean():4.0f}%（{y[y.dt<TRAIN_END].place.mean():.0f}/{y[y.dt>=TRAIN_END].place.mean():.0f}）")

    print("\n■ H1 直近3走以内の大差負け（全馬）")
    line(df[df.big], "3.0秒以上の負けあり")
    line(df[df.mid & ~df.big], "1.5〜3.0秒の負けあり（3.0秒以上なし）")
    line(df[~df.mid & ~df.big], "どちらもなし")
    print("  └ 案G上位5頭に限ると")
    t = df[df.rank_G <= 5]
    line(t[t.big], "3.0秒以上の負けあり")
    line(t[~t.big], "なし")
    print("  └ 案G6位以下に限ると")
    t = df[df.rank_G > 5]
    line(t[t.big], "3.0秒以上の負けあり")
    line(t[~t.big], "なし")

    print("\n■ H2 コース巧者の先行馬 × 前に行く馬が少ない（全馬）")
    print(f"  先行馬の割合 {df.front.mean():.0%} / 先行2頭以下のレース {df.groupby('rid').few_front.first().mean():.0%} / 巧者の割合 {df.ace.mean():.0%}")
    line(df[df.front], "先行馬")
    line(df[df.front & df.few_front], "先行馬 × 先行2頭以下のレース")
    line(df[df.front & ~df.few_front], "先行馬 × 先行3頭以上のレース")
    line(df[df.ace], "コース巧者")
    line(df[df.ace & df.front], "巧者 × 先行")
    line(df[df.ace & df.front & df.few_front], "巧者 × 先行 × 先行2頭以下")
    line(df[df.ace & df.front & df.few_front & (df.rank_G > 5)], "  うち案G6位以下（見落とし側）")


if __name__ == "__main__":
    main()
