"""
人気上位の中でシステム最上位を軸にした馬連流し分析
戦略: 人気1〜N位の馬のうち、予想順位が最も上位の馬を軸 → 予想TOP5の残り馬へ流し
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, glob, re, time, requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

def fetch_popularity(race_id: str) -> dict[str, int]:
    """馬名→人気順位 を取得"""
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    time.sleep(0.5)
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return {}
    pop_map = {}
    for row in tables[0].find_all("tr")[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 10:
            continue
        try:
            name = cells[3]
            popularity = int(cells[9])
            pop_map[name] = popularity
        except (ValueError, IndexError):
            continue
    return pop_map

csv_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "results", "prediction_*_最終.csv")))

# 人気上位N位の中からシステム最上位を軸にするNの値を試す
for popular_n in [3]:
    print(f"\n{'='*75}")
    print(f"【人気TOP{popular_n}の中でシステム最上位を軸】馬連→予想TOP5流し (4点)")
    print(f"{'='*75}")

    results_by_range = {
        "馬連TOP5(4点)": {"hits": 0, "anchor": 0, "wide_count": 0, "total": 0, "rows": []},
        "ワイドTOP5(4点)": {"hits": 0, "anchor": 0, "wide_count": 0, "total": 0, "rows": []},
    }

    for path in csv_files:
        race_id_m = re.search(r"prediction_(\d{12})_", os.path.basename(path))
        if not race_id_m:
            continue
        race_id = race_id_m.group(1)

        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        race_name = rows[0][0]

        header_idx = next((i for i, r in enumerate(rows) if r and r[0] == "実結果"), None)
        if header_idx is None:
            continue
        header = rows[header_idx]
        col_a = header.index("実結果")
        col_p = header.index("予想順位")
        col_n = header.index("馬名")

        horses = []
        for row in rows[header_idx+1:]:
            if not row or not row[col_a]:
                continue
            try:
                horses.append((int(row[col_a]), int(row[col_p]), row[col_n]))
            except (ValueError, IndexError):
                continue

        # 人気データ取得
        pop_map = fetch_popularity(race_id)
        if not pop_map:
            print(f"  {race_name:<18}  人気データ取得失敗")
            continue

        # 人気TOP N の馬
        popular_horses = [(pop_map[n], p, a, n)
                          for a, p, n in horses if n in pop_map and pop_map[n] <= popular_n]
        if not popular_horses:
            continue

        # 人気TOP N の中でシステム予想順位が最も上位（小さい）の馬を軸に
        anchor = min(popular_horses, key=lambda x: x[1])  # x[1]=予想順位
        anchor_pop, anchor_pred, anchor_actual, anchor_name = anchor

        # 軸が1〜2着に来たか
        anchor_hit = anchor_actual <= 2

        actual_top2 = {n for a, p, n in horses if a <= 2}
        actual_top3 = {n for a, p, n in horses if a <= 3}
        partners_top5 = [(a, p, n) for a, p, n in horses if p <= 5 and n != anchor_name]

        # 馬連(1〜2着) TOP5流し
        umaren_hit_names = [n for a, p, n in partners_top5 if n in actual_top2]
        umaren_hit = anchor_hit and len(umaren_hit_names) > 0

        # ワイド(1〜3着) TOP5フォーメーション
        anchor_in_top3 = anchor_actual <= 3
        wide_hit_names = [n for a, p, n in partners_top5 if n in actual_top3 and n != anchor_name]
        from math import comb
        wide_count = len(wide_hit_names)  # 的中本数
        wide_hit = anchor_in_top3 and wide_count > 0

        for label, hit, anchor_cond, hit_names, pts in [
            ("馬連TOP5(4点)", umaren_hit, anchor_hit,      umaren_hit_names, 4),
            ("ワイドTOP5(4点)", wide_hit,  anchor_in_top3, wide_hit_names,   4),
        ]:
            results_by_range[label]["hits"]       += int(hit)
            results_by_range[label]["anchor"]     += int(anchor_cond)
            results_by_range[label]["wide_count"] += wide_count if label.startswith("ワイド") else 0
            results_by_range[label]["total"]      += 1
            results_by_range[label]["rows"].append({
                "race": race_name, "anchor": anchor_name,
                "pop": anchor_pop, "pred": anchor_pred,
                "actual": anchor_actual, "hit": hit,
                "anchor_cond": anchor_cond,
                "hit_names": hit_names,
                "wide_count": wide_count if label.startswith("ワイド") else None,
            })

    # 結果表示
    for label, pts, bet_type, anchor_label in [
        ("馬連TOP5(4点)", 4, "馬連", "1〜2着"),
        ("ワイドTOP5(4点)", 4, "ワイド", "1〜3着"),
    ]:
        r = results_by_range[label]
        n = r["total"]
        print(f"\n  --- {label} ({bet_type}: 軸が{anchor_label}に来ること) ---")
        for row in r["rows"]:
            status = "✅的中" if row["hit"] else ("軸ハズレ" if not row["anchor_cond"] else "相手ハズレ")
            wc = f" {row['wide_count']}本" if row["wide_count"] is not None and row["hit"] else ""
            print(f"  {row['race']:<18} 軸:{row['anchor']}(人気{row['pop']}位/予想{row['pred']}位/実{row['actual']}着) {status}{wc}")
        print(f"  軸が{anchor_label}: {r['anchor']}/{n} ({r['anchor']/n*100:.1f}%)")
        if label.startswith("ワイド"):
            total_wide = r["wide_count"]
            print(f"  ワイド的中レース: {r['hits']}/{n} ({r['hits']/n*100:.1f}%)  合計{total_wide}本的中")
            print(f"  投資: {pts}点×{n}レース = {pts*n*100}円")
            print(f"  損益分岐: ワイド平均{pts*n*100//max(total_wide,1)}円/本 で±0")
        else:
            print(f"  馬連的中:   {r['hits']}/{n} ({r['hits']/n*100:.1f}%)")
            print(f"  投資: {pts}点×{n}レース = {pts*n*100}円")
            print(f"  損益分岐: 馬連{pts*n*100//max(r['hits'],1)}円/本 で±0")
