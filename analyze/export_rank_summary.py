import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv
from collections import defaultdict

src = "/Users/du/Documents/競馬予想システム/data/検証_芝_2026年3〜5月.csv"
out = "/Users/du/Documents/競馬予想システム/data/検証_順位別確率.csv"

data = defaultdict(lambda: defaultdict(lambda: [0]*5))

with open(src, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            rank   = int(row["予想順位"])
            actual = int(row["実着順"])
            cls    = row["クラス"]
        except:
            continue
        for c in [cls, "全体"]:
            d = data[rank][c]
            d[0] += 1
            if actual == 1: d[1] += 1
            if actual == 2: d[2] += 1
            if actual == 3: d[3] += 1
            if actual >= 4: d[4] += 1

classes = ["全体", "2勝クラス", "OP", "重賞"]

rows_out = []
for rank in sorted(data.keys()):
    for cls in classes:
        d = data[rank].get(cls)
        if not d or d[0] == 0:
            continue
        total, win, p2, p3, out_n = d
        place = win + p2 + p3
        rows_out.append({
            "予想順位":    rank,
            "クラス":      cls,
            "出現頭数":    total,
            "1着数":       win,
            "1着率%":      round(win/total*100, 1),
            "2着数":       p2,
            "2着率%":      round(p2/total*100, 1),
            "3着数":       p3,
            "3着率%":      round(p3/total*100, 1),
            "複勝数":      place,
            "複勝率%":     round(place/total*100, 1),
            "連対数":      win+p2,
            "連対率%":     round((win+p2)/total*100, 1),
            "4着以下数":   out_n,
            "4着以下率%":  round(out_n/total*100, 1),
        })

with open(out, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
    writer.writeheader()
    writer.writerows(rows_out)

print(f"出力完了: {out}  ({len(rows_out)}行)")
print()
print(f"{'順位':>4} {'クラス':^8} {'頭数':>5} {'単勝率':>6} {'複勝率':>6} {'連対率':>6}")
print("-" * 45)
for r in rows_out:
    if r["クラス"] == "全体":
        print(f"{r['予想順位']:>4}位 {'全体':^8} {r['出現頭数']:>5} {r['1着率%']:>5.1f}% {r['複勝率%']:>5.1f}% {r['連対率%']:>5.1f}%")
