"""
このシステムはどういうレースで強いのか（2026-09-25）

条件を先に決めてから、学習期間（2024/06〜2025/06）とテスト期間（2025/07〜）の**両方**で成績を出す。
片方だけ良い条件は偶然とみなす（馬単1→2で選択バイアスに引っかかった反省）。

条件（事前に決めたもの）:
  馬場 / 芝ダ / クラス / 頭数 / 距離 / 1番人気のオッズ（堅いレースか荒れそうか）
  予想1位が市場で何番人気か / 予想1位と2位の総合点差（乖離）/ 予想1位のオッズ帯 / 開催場
指標: 予想1位の複勝率・単勝ROI、三連複「1軸-相手2〜5位（6点・現行の買い目）」の的中率とROI。
使い方: python3 analyze/strength_profile.py
"""
import json, sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_residual_model as M
import ability_blend_backtest as B
import wet_track_calibration as WET
import verify.bet_analysis2 as ba2

TRAIN_END = pd.Timestamp(2025, 7, 1)
LOCAL = {"札幌", "函館", "福島", "新潟", "中京", "小倉"}


def build():
    df, factors = M.load()
    v3 = pd.read_parquet(BASE / "data" / "v3_eval.parquet")[["馬名", "dt", "v3_c"]]
    v3 = v3[~v3.duplicated(subset=["馬名", "dt"])].set_index(["馬名", "dt"])
    j = df.join(v3, on=["馬名", "dt"])
    m = j.groupby("rid")["v3_c"].transform("mean")
    df["v3_c"] = (j["v3_c"].fillna(m) - m).fillna(0.0)
    df["rest_sum"] = df[[c for c in factors if c not in B.ABILITY_FACTORS]].sum(axis=1)
    u, w = B.fit_util(df, ["v3_c", "rest_sum"], 0.5)
    df["u_G"] = u
    df["rank_G"] = df.groupby("rid")["u_G"].rank(ascending=False, method="first")
    df["pop"] = df["市場人気"].astype(float)
    print("案Gの重み:", w)

    full = WET.going_from_full_history()
    fb = {}
    for q in (BASE / "cache" / "race_result").glob("*.json"):
        d = json.loads(q.read_text())
        if d.get("date"):
            fb[(M.jp_date(d["date"]), d.get("venue", ""), d.get("surface", ""))] = WET.NORM.get(d.get("track_condition") or "", "")
    surf = np.where(df["コース"].astype(str).str.startswith("芝"), "芝", "ダ")
    df["going"] = [full.get(k) or fb.get(k, "") for k in zip(df["dt"], df["競馬場"], surf)]

    rid_of = {r["key"]: r["race_id"] for r in ba2.load_races()}
    pay = {}
    for p in (BASE / "cache" / "payouts").glob("*.json"):
        nums, amounts = ba2.get_payout(p.stem, "3連複")
        if amounts and len(nums) >= 3 * len(amounts):
            pay[p.stem] = ([frozenset(nums[3 * k:3 * k + 3]) for k in range(len(amounts))], amounts)

    # レース単位に集約
    rows = []
    for key, g in df.groupby(["日付", "レース名"]):
        g = g.sort_values("rank_G")
        if len(g) < 6:
            continue
        rid = rid_of.get(key)
        top = g.iloc[0]
        fav_odds = float(g.loc[g["pop"].idxmin(), "単勝オッズ"]) if g["pop"].notna().any() else np.nan
        got = inv = np.nan
        if rid in pay:
            axis, others = int(top["馬番"]), [int(x) for x in g["馬番"].iloc[1:5]]
            bets = {frozenset((axis,) + c) for c in combinations(others, 2)}
            combos, amounts = pay[rid]
            got = sum(a for c, a in zip(combos, amounts) if c in bets)
            inv = 100 * len(bets)
        rows.append({"dt": top["dt"], "cls": top["クラス"], "surface": "芝" if str(top["コース"]).startswith("芝") else "ダ",
                     "venue": top["競馬場"], "going": top["going"], "n": len(g),
                     "dist": int(str(top["距離"]).replace("m", "") or 0),
                     "fav_odds": fav_odds, "top_odds": float(top["単勝オッズ"]), "top_pop": top["pop"],
                     "gap": float(g["u_G"].iloc[0] - g["u_G"].iloc[1]) * 10,
                     "top_rank": top["実着順"], "trio_got": got, "trio_inv": inv})
    return pd.DataFrame(rows)


def line(d, lab):
    if len(d) < 25:
        return f"{lab:<22}{len(d):>5}  ——（少数）"
    plc = (d.top_rank <= 3).mean() * 100
    roi = (d.top_odds * (d.top_rank == 1)).mean() * 100
    t = d[d.trio_inv.notna()]
    thit = (t.trio_got > 0).mean() * 100 if len(t) else np.nan
    troi = t.trio_got.sum() / t.trio_inv.sum() * 100 if len(t) else np.nan
    return f"{lab:<22}{len(d):>5}{plc:>8.1f}%{roi:>8.0f}%{thit:>8.1f}%{troi:>7.0f}%"


def main():
    df = build()
    tr, te = df[df.dt < TRAIN_END], df[df.dt >= TRAIN_END]
    print(f"\n対象レース: 学習期間{len(tr)}R / テスト期間{len(te)}R")
    conds = [
        ("馬場", [("良", lambda d: d.going == "良"), ("稍重", lambda d: d.going == "稍重"),
                 ("重・不良", lambda d: d.going.isin(["重", "不良"]))]),
        ("芝ダ", [("芝", lambda d: d.surface == "芝"), ("ダート", lambda d: d.surface == "ダ")]),
        ("クラス", [(c, (lambda c: lambda d: d.cls == c)(c)) for c in ("2勝クラス", "3勝クラス", "OP", "重賞")]),
        ("頭数", [("〜10頭", lambda d: d.n <= 10), ("11〜13頭", lambda d: d.n.between(11, 13)),
                 ("14〜15頭", lambda d: d.n.between(14, 15)), ("16頭〜", lambda d: d.n >= 16)]),
        ("距離", [("〜1400m", lambda d: d.dist <= 1400), ("1500〜1800m", lambda d: d.dist.between(1500, 1800)),
                 ("1900m〜", lambda d: d.dist >= 1900)]),
        ("1番人気のオッズ", [("断然 〜2.0倍", lambda d: d.fav_odds < 2.0), ("2.0〜3.5倍", lambda d: d.fav_odds.between(2.0, 3.5)),
                       ("3.5倍〜（混戦）", lambda d: d.fav_odds > 3.5)]),
        ("予想1位の人気", [("1番人気と一致", lambda d: d.top_pop == 1), ("2〜3番人気", lambda d: d.top_pop.between(2, 3)),
                     ("4〜6番人気", lambda d: d.top_pop.between(4, 6)), ("7番人気以下", lambda d: d.top_pop >= 7)]),
        ("予想1位のオッズ", [("〜3倍", lambda d: d.top_odds <= 3), ("3〜6倍", lambda d: d.top_odds.between(3, 6)),
                      ("6〜12倍", lambda d: d.top_odds.between(6, 12)), ("12倍〜", lambda d: d.top_odds > 12)]),
        ("1位と2位の点差", [("〜2点（横並び）", lambda d: d.gap <= 2), ("2〜5点", lambda d: d.gap.between(2, 5)),
                      ("5点〜（抜けている）", lambda d: d.gap > 5)]),
        ("開催場", [("中央4場", lambda d: ~d.venue.isin(LOCAL)), ("ローカル", lambda d: d.venue.isin(LOCAL))]),
    ]
    for title, items in conds:
        print(f"\n■ {title}")
        print(f"{'':<22}{'R数':>5}{'1位複勝':>9}{'単ROI':>8}{'三連複':>8}{'ROI':>7}   ｜ テスト期間")
        for lab, f in items:
            a, b = line(tr[f(tr)], lab), line(te[f(te)], "")
            print(f"{a}   ｜{b[22:]}")
    print("\n（左＝学習期間 2024/06〜2025/06 / 右＝テスト期間 2025/07〜。三連複は1軸-相手2〜5位の6点）")


if __name__ == "__main__":
    main()
