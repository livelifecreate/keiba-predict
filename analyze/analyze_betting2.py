"""ワイドTOP5ボックス・馬連流し の詳細分析"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, glob

csv_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "results", "prediction_*_最終.csv")))

print("=" * 80)
print("【A】ワイドTOP5ボックス (10点) — 的中数ごとの内訳")
print("=" * 80)
wide_summary = {"0本": 0, "1本": 0, "2本": 0, "3本(トリプル)": 0}

for path in csv_files:
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    race_name = rows[0][0]
    header_idx = next((i for i, r in enumerate(rows) if r and r[0] == "実結果"), None)
    if header_idx is None: continue
    header = rows[header_idx]
    col_a, col_p, col_n = header.index("実結果"), header.index("予想順位"), header.index("馬名")

    horses = []
    for row in rows[header_idx+1:]:
        if not row or not row[col_a]: continue
        try: horses.append((int(row[col_a]), int(row[col_p]), row[col_n]))
        except: continue

    # 予想TOP5に入っている実1〜3着馬の数 = ワイド的中本数
    top5_names = {n for a, p, n in horses if p <= 5}
    actual_top3 = [(a, n) for a, p, n in horses if a <= 3]
    hits_in_top5 = [n for a, n in actual_top3 if n in top5_names]
    wide_count = len(hits_in_top5)
    # ワイド的中本数: TOP5内に3着以内が k頭いれば C(k,2)本的中
    from math import comb
    wide_hits = comb(wide_count, 2)  # k頭いれば k*(k-1)/2 通り的中

    key = f"{wide_count}頭({wide_hits}本的中)" if wide_count > 0 else "0頭(0本)"
    label = {0: "0本", 1: "1本", 2: "2本", 3: "3本(トリプル)"}.get(wide_hits, "その他")
    wide_summary[label] += 1

    hits_str = ", ".join(hits_in_top5) if hits_in_top5 else "なし"
    print(f"  {race_name:<18} TOP5内に{wide_count}頭 → ワイド{wide_hits}本的中  ({hits_str})")

print()
print("  内訳:")
for k, v in wide_summary.items():
    print(f"    {k}: {v}レース")
total = sum(wide_summary.values())
avg_hits = (wide_summary["1本"]*1 + wide_summary["2本"]*2 + wide_summary["3本(トリプル)"]*3)
print(f"  9レース合計: {avg_hits}本的中 / {total*10}点投資")
print(f"  平均回収必要オッズ: {total*10*100 / max(avg_hits,1):.0f}円/本 で±0")

print()
print("=" * 80)
print("【B】馬連 予想1位→2〜5位 流し (4点) — 予想1位が1〜2着に来たか")
print("=" * 80)
nagashi_results = []

for path in csv_files:
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    race_name = rows[0][0]
    header_idx = next((i for i, r in enumerate(rows) if r and r[0] == "実結果"), None)
    if header_idx is None: continue
    header = rows[header_idx]
    col_a, col_p, col_n = header.index("実結果"), header.index("予想順位"), header.index("馬名")

    horses = []
    for row in rows[header_idx+1:]:
        if not row or not row[col_a]: continue
        try: horses.append((int(row[col_a]), int(row[col_p]), row[col_n]))
        except: continue

    pred1 = next(((a, n) for a, p, n in horses if p == 1), None)
    top5_others = [(a, n) for a, p, n in horses if 2 <= p <= 5]
    actual_top2 = {n for a, p, n in horses if a <= 2}

    if pred1 is None: continue
    pred1_actual, pred1_name = pred1
    pred1_hit = pred1_actual <= 2  # 予想1位が1〜2着に来たか

    # 相手馬で馬連的中したか
    partner_hits = [n for a, n in top5_others if n in actual_top2] if pred1_hit else []
    hit = len(partner_hits) > 0

    nagashi_results.append({
        "race": race_name,
        "pred1": pred1_name,
        "pred1_actual": pred1_actual,
        "pred1_hit": pred1_hit,
        "partner_hits": partner_hits,
        "hit": hit,
    })

    status = "✅的中" if hit else ("軸ハズレ" if not pred1_hit else "相手ハズレ")
    partner_str = ", ".join(partner_hits) if partner_hits else "—"
    print(f"  {race_name:<18} 軸:{pred1_name}(実{pred1_actual}着)  {status}  相手的中:{partner_str}")

total_hit = sum(1 for r in nagashi_results if r["hit"])
pred1_hit_count = sum(1 for r in nagashi_results if r["pred1_hit"])
print()
print(f"  的中: {total_hit}/{len(nagashi_results)}レース  ({total_hit/len(nagashi_results)*100:.1f}%)")
print(f"  軸(予想1位)が1〜2着: {pred1_hit_count}/{len(nagashi_results)}レース ({pred1_hit_count/len(nagashi_results)*100:.1f}%)")
print(f"  投資: 4点×9レース = {4*len(nagashi_results)*100}円")
print(f"  平均回収必要オッズ: {4*len(nagashi_results)*100 / max(total_hit,1):.0f}円/本 で±0")

print()
print("=" * 80)
print("【C】ワイドTOP5 vs 馬連流し — コスト比較まとめ")
print("=" * 80)
print(f"  ワイドTOP5ボックス: 10点/レース  計{total*10}点  的中{avg_hits}本")
print(f"  馬連予想1位流し(4点): 4点/レース  計{4*len(nagashi_results)}点  的中{total_hit}レース")
