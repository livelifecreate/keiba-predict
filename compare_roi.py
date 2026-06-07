"""
ワイド買い方別 回収率比較
  A: 軸1頭流し（人気TOP3×システム最上位 → 予想TOP5流し 4点）
  B: ワイドTOP3ボックス（3点）
  C: ワイドTOP5ボックス（10点）
"""
import csv, glob, os, re, time, requests
from itertools import combinations
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

def fetch_race_data(race_id: str):
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    time.sleep(0.6)
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return {}, {}, {}
    num2name, name2pop = {}, {}
    for row in tables[0].find_all("tr")[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 10:
            continue
        try:
            num2name[cells[2]] = cells[3]
            name2pop[cells[3]] = int(cells[9])
        except (ValueError, IndexError):
            continue
    wide_payouts = {}
    for tbl in tables:
        wide_row = tbl.find("tr", class_="Wide")
        if not wide_row:
            continue
        result_td = wide_row.find("td", class_="Result")
        payout_td = wide_row.find("td", class_="Payout")
        if not result_td or not payout_td:
            continue
        combos = []
        for ul in result_td.find_all("ul"):
            nums = [s.get_text(strip=True) for s in ul.find_all("span") if s.get_text(strip=True)]
            if len(nums) >= 2:
                combos.append((nums[0], nums[1]))
        pays = [p.strip().replace("円", "").replace(",", "")
                for p in payout_td.get_text(separator="\n").split("\n") if "円" in p]
        for combo, pay in zip(combos, pays):
            try:
                wide_payouts[combo] = int(pay)
            except ValueError:
                pass
        break
    return num2name, name2pop, wide_payouts

def wide_return(buy_names: list[str], name2num: dict, wide_payouts: dict) -> tuple[int, list]:
    """購入馬リストからワイド払戻し合計を計算。的中組合せも返す"""
    total = 0
    hits = []
    for n1, n2 in combinations(buy_names, 2):
        num1 = name2num.get(n1, "")
        num2 = name2num.get(n2, "")
        if not num1 or not num2:
            continue
        combo = tuple(sorted([num1, num2], key=lambda x: int(x) if x.isdigit() else 99))
        pay = wide_payouts.get(combo, 0)
        if pay > 0:
            total += pay
            hits.append(f"{n1}-{n2}:{pay}円")
    return total, hits

csv_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "prediction_*_最終.csv")))

strategies = {
    "A_軸流し(4点)":    {"invest": 400, "hits": 0, "returns": 0, "rows": []},
    "B_TOP3BOX(3点)":   {"invest": 300, "hits": 0, "returns": 0, "rows": []},
    "C_TOP5BOX(10点)":  {"invest": 1000, "hits": 0, "returns": 0, "rows": []},
}

print(f"{'レース名':<18}  {'A_軸流し':>8} {'B_TOP3BOX':>10} {'C_TOP5BOX':>10}")
print("-" * 55)

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
    for row in rows[header_idx + 1:]:
        if not row or not row[col_a]:
            continue
        try:
            horses.append((int(row[col_a]), int(row[col_p]), row[col_n]))
        except (ValueError, IndexError):
            continue

    num2name, name2pop, wide_payouts = fetch_race_data(race_id)
    if not name2pop:
        continue
    name2num = {v: k for k, v in num2name.items()}

    # 軸選定（人気TOP3×システム最上位）
    popular = [(name2pop[n], p, a, n) for a, p, n in horses if n in name2pop and name2pop[n] <= 3]
    if not popular:
        continue
    anchor = min(popular, key=lambda x: x[1])
    _, _, _, anchor_name = anchor
    partners_top5 = [n for a, p, n in horses if p <= 5 and n != anchor_name]

    # 各戦略の買い馬リストと払戻し計算
    top3_names = [n for a, p, n in sorted(horses, key=lambda x: x[1])[:3]]
    top5_names = [n for a, p, n in sorted(horses, key=lambda x: x[1])[:5]]

    # A: 軸1頭流し（軸×相手4頭の4点のみ。相手同士は買わない）
    ret_a, hits_a = 0, []
    anchor_num = name2num.get(anchor_name, "")
    for p_name in partners_top5:
        p_num = name2num.get(p_name, "")
        if not anchor_num or not p_num:
            continue
        combo = tuple(sorted([anchor_num, p_num], key=lambda x: int(x) if x.isdigit() else 99))
        pay = wide_payouts.get(combo, 0)
        if pay > 0:
            ret_a += pay
            hits_a.append(f"{anchor_name}-{p_name}:{pay}円")
    # B: TOP3ボックス
    ret_b, hits_b = wide_return(top3_names, name2num, wide_payouts)
    # C: TOP5ボックス
    ret_c, hits_c = wide_return(top5_names, name2num, wide_payouts)

    for key, ret in [("A_軸流し(4点)", ret_a), ("B_TOP3BOX(3点)", ret_b), ("C_TOP5BOX(10点)", ret_c)]:
        strategies[key]["returns"] += ret
        if ret > 0:
            strategies[key]["hits"] += 1

    strategies["A_軸流し(4点)"]["rows"].append((race_name, ret_a, hits_a))
    strategies["B_TOP3BOX(3点)"]["rows"].append((race_name, ret_b, hits_b))
    strategies["C_TOP5BOX(10点)"]["rows"].append((race_name, ret_c, hits_c))

    def fmt(ret, invest):
        return f"{ret:>5}円({ret*100//invest:>3}%)" if ret > 0 else f"{'—':>9}"

    print(f"  {race_name:<18} {fmt(ret_a,400):>12} {fmt(ret_b,300):>12} {fmt(ret_c,1000):>12}")

print("-" * 55)
n = len(strategies["A_軸流し(4点)"]["rows"])

print()
print(f"{'戦略':<16} {'購入点数':>6} {'的中回数':>8} {'総投資':>8} {'総払戻':>8} {'回収率':>7} {'収支':>8}")
print("-" * 70)
for key, pts in [("A_軸流し(4点)", 4), ("B_TOP3BOX(3点)", 3), ("C_TOP5BOX(10点)", 10)]:
    s = strategies[key]
    invest = pts * 100 * n
    ret    = s["returns"]
    roi    = ret / invest * 100
    diff   = ret - invest
    print(f"  {key:<16} {pts:>6}点  {s['hits']:>5}回/{n}回  {invest:>6}円  {ret:>6}円  {roi:>6.1f}%  {diff:>+7}円")

print()
print("=== 各戦略の的中内訳 ===")
for key in strategies:
    print(f"\n【{key}】")
    for race, ret, hits in strategies[key]["rows"]:
        if hits:
            print(f"  {race:<18} {ret:>5}円  {' / '.join(hits)}")
        else:
            print(f"  {race:<18}  —")
