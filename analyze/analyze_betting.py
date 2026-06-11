"""買い方ごとの的中パターン分析（オッズなし・点数ベース）"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, glob
from itertools import combinations

csv_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "results", "prediction_*_最終.csv")))

strategies = {
    "馬連TOP3BOX(3点)":   {"bet": "馬連", "pred_n": 3, "need": 2, "of": 2},
    "馬連TOP5BOX(10点)":  {"bet": "馬連", "pred_n": 5, "need": 2, "of": 2},
    "ワイドTOP3BOX(3点)":  {"bet": "ワイド", "pred_n": 3, "need": 2, "of": 3},
    "ワイドTOP5BOX(10点)": {"bet": "ワイド", "pred_n": 5, "need": 2, "of": 3},
    "3連複TOP3BOX(1点)":  {"bet": "3連複", "pred_n": 3, "need": 3, "of": 3},
    "3連複TOP5BOX(10点)": {"bet": "3連複", "pred_n": 5, "need": 3, "of": 3},
    "3連複TOP7BOX(35点)": {"bet": "3連複", "pred_n": 7, "need": 3, "of": 3},
}

results = {k: {"hits": 0, "total": 0} for k in strategies}
race_details = []

for path in csv_files:
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    race_name = rows[0][0] if rows else os.path.basename(path)

    header_idx = None
    for i, row in enumerate(rows):
        if row and row[0] == "実結果":
            header_idx = i
            break
    if header_idx is None:
        continue

    header = rows[header_idx]
    try:
        col_actual = header.index("実結果")
        col_pred   = header.index("予想順位")
        col_name   = header.index("馬名")
    except ValueError:
        continue

    horses = []
    for row in rows[header_idx + 1:]:
        if not row or not row[col_actual]:
            continue
        try:
            actual = int(row[col_actual])
            pred   = int(row[col_pred])
            name   = row[col_name]
            horses.append((actual, pred, name))
        except (ValueError, IndexError):
            continue

    # 実1〜3着馬の予想順位セット
    actual_top3_preds = {p for a, p, n in horses if a <= 3}
    actual_top3_names = {n for a, p, n in horses if a <= 3}

    race_row = {"race": race_name}
    for key, cfg in strategies.items():
        pred_n = cfg["pred_n"]
        need   = cfg["need"]
        of     = cfg["of"]

        # 予想上位pred_n頭の実際の着順を取得
        top_n_preds = {p for a, p, n in horses if p <= pred_n}
        top_n_actual = {a for a, p, n in horses if p <= pred_n}
        # 予想上位pred_n頭の中で実1〜of着に入った頭数
        hits_in_pred = sum(1 for a, p, n in horses if p <= pred_n and a <= of)

        hit = hits_in_pred >= need
        results[key]["hits"] += int(hit)
        results[key]["total"] += 1
        race_row[key] = "○" if hit else "×"

    race_details.append(race_row)

# 表示
print(f"{'買い方':<22} {'的中':>4} {'全':>4} {'的中率':>7}")
print("-" * 45)
for key, r in results.items():
    rate = r["hits"] / r["total"] * 100 if r["total"] else 0
    print(f"{key:<22} {r['hits']:>4}/{r['total']:<4} {rate:>6.1f}%")

print()
print(f"{'レース名':<26}", end="")
for key in strategies:
    print(f" {key[:6]:>6}", end="")
print()
print("-" * (26 + len(strategies) * 7))
for row in race_details:
    print(f"{row['race']:<26}", end="")
    for key in strategies:
        print(f" {row.get(key,'?'):>6}", end="")
    print()

print()
print("【補足】")
print("  馬連: 1〜2着の2頭が予想TOP内に両方含まれるか")
print("  ワイド: 1〜3着のうち2頭以上が予想TOP内に含まれるか")
print("  3連複: 1〜3着の3頭すべてが予想TOP内に含まれるか")
