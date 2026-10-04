"""
出走数の少ない馬を案Gはどう評価しているか（2026-10-04）
中央での出走数（レース日より前・race_resultから）ごとに、3着内の実績と案Gの見込み（同じ頭数帯×同じ案G順位の平均）の差を見る。
使い方: python3 analyze/experience_bias_test.py
"""
import json, sys, textwrap
from pathlib import Path
import numpy as np, pandas as pd
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import comeback_test as CB
TRAIN_END = CB.TRAIN_END


def jra_counts():
    """{馬名: [中央の出走日...]}"""
    out = {}
    for p in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(p.read_text())
        import re
        m = re.match(r"(\d+)年(\d+)月(\d+)日", d.get("date", ""))
        if not m: continue
        dt = pd.Timestamp(*map(int, m.groups()))
        for e in d.get("entries", []):
            out.setdefault(e.get("horse_name", ""), []).append(dt)
    return {k: sorted(v) for k, v in out.items()}


def build():
    src = open(Path(__file__).resolve().parent / "comeback_test.py", encoding="utf-8").read()
    body = src.split("def main():")[1].split("    def line(x, lab):")[0]
    ns = dict(vars(CB)); exec(textwrap.dedent(body), ns)
    df = ns["df"]
    C = jra_counts()
    df["n_jra"] = [sum(1 for x in C.get(nm, []) if x < dt) for nm, dt in zip(df["馬名"], df["dt"])]
    df["expG"] = df.groupby(["nbin", "rank_G"], observed=True)["top3"].transform("mean")
    return df


def main():
    df = build()
    df["nb"] = pd.cut(df.n_jra, [-1, 0, 1, 2, 3, 5, 8, 999], labels=["0走", "1走", "2走", "3走", "4-5走", "6-8走", "9走以上"])
    print("※ race_result は2024/06以降のみなので「中央での出走数」はその期間内の数（それ以前の出走は数えていない）")
    for scope, s in (("全馬", df), ("案G上位5頭", df[df.rank_G <= 5])):
        print(f"\n■ {scope}")
        for b, x in s.groupby("nb", observed=True):
            tr, te = x[x.dt < TRAIN_END], x[x.dt >= TRAIN_END]
            d = lambda y: (y.top3.mean() - y.expG.mean()) * 100
            print(f"  {b:<7} n={len(x):>5} 3着内{x.top3.mean()*100:5.1f}% 案G見込み{x.expG.mean()*100:5.1f}% 差{d(x):+5.1f}（学習{d(tr):+5.1f}/テスト{d(te):+5.1f}） 人気見込みとの差{(x.top3.mean()-x.exp3.mean())*100:+5.1f}")


if __name__ == "__main__":
    main()
