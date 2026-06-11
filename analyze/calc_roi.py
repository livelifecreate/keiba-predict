"""
人気TOP3×システム最上位を軸 → 予想TOP5流しワイド の実際の回収率計算
- 各レースの払戻しをnetkeibaから取得
- 既存CSVにワイド払戻しセクションを追記
- 全レース合計でROI算出
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv, glob, re, time, requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
TICKET_PRICE = 100  # 1点あたり

def fetch_race_data(race_id: str):
    """馬番→馬名マップ、人気マップ、ワイド払戻しを一括取得"""
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    time.sleep(0.6)
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return {}, {}, {}

    num2name = {}  # 馬番(str) → 馬名
    name2pop = {}  # 馬名 → 人気
    for row in tables[0].find_all("tr")[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 10:
            continue
        try:
            num2name[cells[2]] = cells[3]
            name2pop[cells[3]] = int(cells[9])
        except (ValueError, IndexError):
            continue

    # ワイド払戻し: {(馬番1, 馬番2): 払戻し金額(int)}
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
        payouts_raw = [p.strip().replace("円", "").replace(",", "")
                       for p in payout_td.get_text(separator="\n").split("\n") if "円" in p]
        for combo, pay_str in zip(combos, payouts_raw):
            try:
                wide_payouts[combo] = int(pay_str)
            except ValueError:
                pass
        break

    return num2name, name2pop, wide_payouts


csv_files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "results", "prediction_*_最終.csv")))

total_invest = 0
total_return = 0
summary_rows = []

print(f"{'レース名':<20} {'軸馬':<16} {'投資':>5} {'払戻':>6} {'回収率':>7}  {'的中組合せ'}")
print("-" * 90)

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

    # netkeibaから人気・ワイド払戻しを取得
    num2name, name2pop, wide_payouts = fetch_race_data(race_id)

    if not name2pop:
        print(f"  {race_name:<20}  データ取得失敗")
        continue

    # 人気TOP3の中でシステム最上位を軸に選定
    popular_horses = [(name2pop[n], p, a, n)
                      for a, p, n in horses if n in name2pop and name2pop[n] <= 3]
    if not popular_horses:
        continue
    anchor = min(popular_horses, key=lambda x: x[1])
    anchor_pop, anchor_pred, anchor_actual, anchor_name = anchor

    # 予想TOP5の相手4頭
    partners = [(a, p, n) for a, p, n in horses if p <= 5 and n != anchor_name]

    invest = len(partners) * TICKET_PRICE  # 4点×100円 = 400円

    # name→馬番 逆引きマップ
    name2num = {v: k for k, v in num2name.items()}

    # 的中したワイド組合せと払戻しを特定
    actual_top3_names = {n for a, p, n in horses if a <= 3}
    anchor_in_top3 = anchor_actual <= 3
    hit_details = []
    race_return = 0

    if anchor_in_top3:
        anchor_num = name2num.get(anchor_name, "")
        for a, p, partner_name in partners:
            if partner_name in actual_top3_names:
                partner_num = name2num.get(partner_name, "")
                # ワイドは小さい馬番が先
                combo = tuple(sorted([anchor_num, partner_num], key=lambda x: int(x) if x.isdigit() else 99))
                payout = wide_payouts.get(combo, 0)
                race_return += payout
                hit_details.append(f"{anchor_name}-{partner_name}:{payout}円")

    total_invest += invest
    total_return += race_return
    roi = race_return / invest * 100 if invest > 0 else 0

    hit_str = "  ".join(hit_details) if hit_details else "ハズレ"
    print(f"  {race_name:<20} {anchor_name:<16} {invest:>5}円 {race_return:>6}円 {roi:>6.0f}%  {hit_str}")

    summary_rows.append({
        "race": race_name, "race_id": race_id,
        "anchor": anchor_name, "anchor_pop": anchor_pop,
        "invest": invest, "return": race_return,
        "hits": hit_details,
    })

    # CSVにワイド払戻しセクションを追記
    # 既存セクションがあれば上書きしない（重複防止）
    with open(path, encoding="utf-8-sig") as f:
        existing = f.read()
    if "ワイド払戻し" not in existing:
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([])
            writer.writerow(["ワイド払戻し（人気TOP3×システム最上位軸→予想TOP5流し）"])
            writer.writerow(["軸馬", "軸人気", "軸実結果", "相手馬", "払戻し(円)", "的中"])
            anchor_num = name2num.get(anchor_name, "")
            for a, p, partner_name in partners:
                partner_num = name2num.get(partner_name, "")
                combo = tuple(sorted([anchor_num, partner_num], key=lambda x: int(x) if x.isdigit() else 99))
                payout = wide_payouts.get(combo, 0) if anchor_in_top3 and partner_name in actual_top3_names else 0
                hit_flag = "○" if payout > 0 else "×"
                writer.writerow([anchor_name, anchor_pop, anchor_actual, partner_name, payout, hit_flag])
            writer.writerow(["投資合計", "", "", "", invest, ""])
            writer.writerow(["払戻合計", "", "", "", race_return, ""])
            writer.writerow(["回収率", "", "", "", f"{race_return/invest*100:.1f}%" if invest else "—", ""])

print()
print("=" * 90)
roi_total = total_return / total_invest * 100 if total_invest > 0 else 0
print(f"  {'合計 ' + str(len(summary_rows)) + 'レース':<38} {total_invest:>5}円 {total_return:>6}円 {roi_total:>6.0f}%")
print()
print(f"  総投資額:  {total_invest}円")
print(f"  総払戻額:  {total_return}円")
print(f"  回収率:    {roi_total:.1f}%")
print(f"  収支:      {total_return - total_invest:+}円")
