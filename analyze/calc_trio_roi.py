"""
3連複/3連単 フォーメーション 回収率分析
  軸1頭（人気TOP3×システム最上位）
  2列目: 予想TOP5（軸除く4頭）固定
  3列目: 予想TOP5〜TOP10 を段階的に広げて比較

3連複: {軸, 2列目の1頭, 3列目の1頭} の組み合わせを購入（順不同）
3連単: (軸→2列目→3列目) の順序付き組み合わせを購入（1着=軸固定）
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, glob, re, time, requests
from itertools import combinations, permutations
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

def fetch_all_payouts(race_id: str):
    """馬番→馬名マップ、人気マップ、ワイド/3連複/3連単払戻しを取得"""
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    time.sleep(0.6)
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return {}, {}, {}, None, None

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

    def parse_combo_payout(tr_class):
        for tbl in tables:
            row = tbl.find("tr", class_=tr_class)
            if not row:
                continue
            result_td = row.find("td", class_="Result")
            payout_td = row.find("td", class_="Payout")
            if not result_td or not payout_td:
                continue
            nums = [s.get_text(strip=True) for s in result_td.find_all("span") if s.get_text(strip=True)]
            pay_str = payout_td.get_text(strip=True).replace("円", "").replace(",", "")
            try:
                return tuple(nums), int(pay_str)
            except ValueError:
                return None, None
        return None, None

    # ワイド払戻し（全3組み合わせ）
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

    trio_nums,  trio_pay  = parse_combo_payout("Fuku3")  # 3連複
    tri3_nums,  tri3_pay  = parse_combo_payout("Tan3")   # 3連単

    return num2name, name2pop, wide_payouts, (trio_nums, trio_pay), (tri3_nums, tri3_pay)


csv_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "results", "prediction_*_最終.csv")))

# 3列目の広さバリエーション（予想TOP5〜TOP10）
COL3_RANGES = list(range(5, 11))

# 集計: {bet_type: {col3_n: {invest, returns, hits}}}
results = {}
for btype in ("3連複", "3連単"):
    results[btype] = {n: {"invest": 0, "returns": 0, "hits": 0,
                          "tickets_total": 0} for n in COL3_RANGES}

race_logs = []

print("データ取得中...")
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

    num2name, name2pop, wide_payouts, trio_info, tri3_info = fetch_all_payouts(race_id)
    if not name2pop:
        print(f"  {race_name}: 取得失敗")
        continue
    name2num = {v: k for k, v in num2name.items()}

    # 軸選定
    popular = [(name2pop[n], p, a, n) for a, p, n in horses if n in name2pop and name2pop[n] <= 3]
    if not popular:
        continue
    anchor_pop, anchor_pred, anchor_actual, anchor_name = min(popular, key=lambda x: x[1])

    # 実際の1〜3着
    actual_top3_names = [n for a, p, n in sorted(horses, key=lambda x: x[0]) if a <= 3]
    # 実際の1着・2着・3着（順序あり）
    place = {a: n for a, p, n in horses if a <= 3}
    actual_1st = place.get(1, "")
    actual_2nd = place.get(2, "")
    actual_3rd = place.get(3, "")

    # 馬番での実際の1〜3着
    actual_trio_nums = tuple(sorted(
        [name2num.get(n, "") for n in actual_top3_names if name2num.get(n, "")],
        key=lambda x: int(x) if x.isdigit() else 99
    ))
    actual_tri3_nums = tuple(filter(None, [
        name2num.get(actual_1st, ""), name2num.get(actual_2nd, ""), name2num.get(actual_3rd, "")
    ]))

    race_log = {"race": race_name, "anchor": anchor_name,
                "anchor_pop": anchor_pop, "anchor_actual": anchor_actual,
                "trio": {}, "tri3": {}}

    for col3_n in COL3_RANGES:
        # 2列目: 予想TOP5から軸除く（固定4頭）
        col2 = [n for a, p, n in horses if 2 <= p <= 5 and n != anchor_name][:4]
        # 3列目: 予想TOP col3_n から軸除く
        col3 = [n for a, p, n in sorted(horses, key=lambda x: x[1]) if p <= col3_n and n != anchor_name]

        # ── 3連複 ──
        # 購入セット: {軸, x, y} x∈col2, y∈col3, x≠y の全ユニーク組み合わせ
        purchased_trio = set()
        for x in col2:
            for y in col3:
                if x != y:
                    key = frozenset([anchor_name, x, y])
                    purchased_trio.add(key)
        trio_tickets = len(purchased_trio)

        # 的中確認
        actual_set = frozenset(actual_top3_names)
        trio_hit = actual_set in purchased_trio
        trio_pay = trio_info[1] if (trio_hit and trio_info[1]) else 0

        results["3連複"][col3_n]["invest"]        += trio_tickets * 100
        results["3連複"][col3_n]["returns"]       += trio_pay
        results["3連複"][col3_n]["hits"]          += int(trio_hit)
        results["3連複"][col3_n]["tickets_total"] += trio_tickets
        race_log["trio"][col3_n] = (trio_tickets, trio_hit, trio_pay)

        # ── 3連単 ──
        # 購入: (軸, x, y) x∈col2, y∈col3, x≠y の全順序組み合わせ
        purchased_tri3 = set()
        for x in col2:
            for y in col3:
                if x != y:
                    purchased_tri3.add((anchor_name, x, y))
        tri3_tickets = len(purchased_tri3)

        # 的中確認（1着=軸, 2着∈col2, 3着∈col3）
        tri3_hit = (actual_1st == anchor_name and
                    actual_2nd in col2 and
                    actual_3rd in col3 and
                    actual_2nd != actual_3rd)
        tri3_pay = tri3_info[1] if (tri3_hit and tri3_info[1]) else 0

        results["3連単"][col3_n]["invest"]        += tri3_tickets * 100
        results["3連単"][col3_n]["returns"]       += tri3_pay
        results["3連単"][col3_n]["hits"]          += int(tri3_hit)
        results["3連単"][col3_n]["tickets_total"] += tri3_tickets
        race_log["tri3"][col3_n] = (tri3_tickets, tri3_hit, tri3_pay)

    race_logs.append(race_log)
    print(f"  {race_name}: 軸={anchor_name}(人気{anchor_pop}位/実{anchor_actual}着) "
          f"3連複的中={'○' if race_log['trio'][5][1] else '×'} "
          f"3連単的中={'○' if race_log['tri3'][5][1] else '×'}")

n_races = len(race_logs)
print()

# ── サマリー表 ──
for btype in ("3連複", "3連単"):
    print(f"\n{'='*75}")
    print(f"【{btype}】軸(人気TOP3×システム最上位) - 2列目:予想TOP5(4頭) - 3列目:予想TOPN")
    print(f"{'='*75}")
    print(f"  {'3列目':>6} {'点数/R':>7} {'総点数':>7} {'的中':>6} {'総投資':>8} {'総払戻':>8} {'回収率':>7} {'収支':>8}")
    print(f"  {'-'*65}")
    for n in COL3_RANGES:
        r = results[btype][n]
        avg_t = r["tickets_total"] // n_races if n_races else 0
        roi = r["returns"] / r["invest"] * 100 if r["invest"] else 0
        diff = r["returns"] - r["invest"]
        print(f"  TOP{n:>2}   {avg_t:>6}点  {r['tickets_total']:>6}点  "
              f"{r['hits']:>3}/{n_races}回  {r['invest']:>7}円  {r['returns']:>7}円  "
              f"{roi:>6.1f}%  {diff:>+8}円")

# ── 的中レース詳細 ──
print(f"\n{'='*75}")
print("【的中レース詳細】（3列目=TOP5 基準）")
print(f"{'='*75}")
for log in race_logs:
    trio5 = log["trio"][5]
    tri35 = log["tri3"][5]
    trio_str = f"3連複○{trio5[2]}円" if trio5[1] else "3連複×"
    tri3_str = f"3連単○{tri35[2]}円" if tri35[1] else "3連単×"
    print(f"  {log['race']:<18} 軸:{log['anchor']}(人気{log['anchor_pop']}/実{log['anchor_actual']}着)"
          f"  {trio_str}  {tri3_str}")

# 参考: ワイド軸流しとの比較
print(f"\n{'='*75}")
print("【参考】ワイド軸流し(4点/R) vs 3連複/3連単 比較")
print(f"{'='*75}")
print(f"  ワイド軸流し(4点):  投資3,600円 → 払戻6,220円  回収率172.8%  収支+2,620円")
for btype in ("3連複", "3連単"):
    r5 = results[btype][5]
    r7 = results[btype][7]
    roi5 = r5["returns"] / r5["invest"] * 100 if r5["invest"] else 0
    roi7 = r7["returns"] / r7["invest"] * 100 if r7["invest"] else 0
    avg5 = r5["tickets_total"] // n_races
    avg7 = r7["tickets_total"] // n_races
    print(f"  {btype}TOP5({avg5}点):  投資{r5['invest']}円 → 払戻{r5['returns']}円  "
          f"回収率{roi5:.1f}%  収支{r5['returns']-r5['invest']:+}円")
    print(f"  {btype}TOP7({avg7}点):  投資{r7['invest']}円 → 払戻{r7['returns']}円  "
          f"回収率{roi7:.1f}%  収支{r7['returns']-r7['invest']:+}円")
