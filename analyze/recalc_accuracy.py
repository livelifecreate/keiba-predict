"""過去バックテストCSVから新指標（予想TOP3/TOP5に実1〜3着が何頭入るか）で再集計"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, glob, re

csv_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "results", "prediction_*_最終.csv")))

total_hit3 = 0
total_hit5 = 0
total_races = 0

print(f"{'レース名':<30} {'TOP3':>8} {'TOP5':>8}  的中馬")
print("-" * 75)

for path in csv_files:
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    # 1行目: レース情報
    race_name = rows[0][0] if rows else os.path.basename(path)

    # ヘッダ行を探す
    header_idx = None
    for i, row in enumerate(rows):
        if row and row[0] == "実結果":
            header_idx = i
            break
    if header_idx is None:
        print(f"{race_name:<30}  ヘッダ行見つからず")
        continue

    header = rows[header_idx]
    try:
        col_actual = header.index("実結果")
        col_pred   = header.index("予想順位")
        col_name   = header.index("馬名")
    except ValueError as e:
        print(f"{race_name:<30}  列名エラー: {e}")
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

    actual_top3 = [(a, p, n) for a, p, n in horses if a <= 3]
    hit3_names = [n for a, p, n in actual_top3 if p <= 3]
    hit5_names = [n for a, p, n in actual_top3 if p <= 5]

    h3 = len(hit3_names)
    h5 = len(hit5_names)
    total_hit3 += h3
    total_hit5 += h5
    total_races += 1

    hit5_str = ", ".join(hit5_names) if hit5_names else "なし"
    print(f"{race_name:<30} {h3}/3{' ':>5} {h5}/3{' ':>5}  {hit5_str}")

print("-" * 75)
print(f"{'合計 ' + str(total_races) + 'レース':<30} {total_hit3}/{total_races*3}{' ':>3} {total_hit5}/{total_races*3}")
print(f"{'的中率':<30} {total_hit3/(total_races*3)*100:.1f}%{' ':>5} {total_hit5/(total_races*3)*100:.1f}%")
