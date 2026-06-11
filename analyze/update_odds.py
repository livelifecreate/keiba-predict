"""
予想CSVのオッズ更新 + 買いサイン再表示

使い方:
  python3 update_odds.py <race_id>
  python3 update_odds.py prediction_202606010811_安田記念_最終.csv

race_id指定の場合:
  - prediction_{race_id}_*.csv を自動検索
  - オッズを自動取得してCSVを更新
  - 買いサインをコンソールに表示

CSVファイル指定の場合:
  - ファイル名から race_id を抽出して同上
"""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re, csv, glob

def find_csv(race_id: str) -> str | None:
    pattern = os.path.join(os.path.dirname(__file__), "..", "results", f"prediction_{race_id}_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    # _最終.csv を優先
    for f in files:
        if "_最終" in f:
            return f
    return files[-1]


def update_csv_with_odds(csv_path: str, odds_map: dict[str, float]) -> None:
    """CSVに単勝オッズ・人気列を追加/更新して上書き保存"""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    if len(rows) < 3:
        print("  [!] CSVが短すぎます")
        return

    # ヘッダー行を探す（「予想順位」か「馬名」が含まれる行）
    header_idx = None
    for i, row in enumerate(rows):
        if "馬名" in row or "予想順位" in row:
            header_idx = i
            break
    if header_idx is None:
        print("  [!] ヘッダー行が見つかりません")
        return

    header = rows[header_idx]

    # 「単勝オッズ」「人気」列の位置を確認・追加
    if "単勝オッズ" not in header:
        # 「合計」または「合計スコア」の直後に挿入
        insert_after = next((i for i, h in enumerate(header)
                             if "合計" in h or "スコア" in h), len(header) - 1)
        header.insert(insert_after + 1, "単勝オッズ")
        header.insert(insert_after + 2, "人気")
        # データ行にも空列を挿入
        for row in rows[header_idx + 1:]:
            if len(row) >= insert_after + 1:
                row.insert(insert_after + 1, "")
                row.insert(insert_after + 2, "")

    odds_col  = header.index("単勝オッズ")
    pop_col   = header.index("人気")
    name_col  = next((i for i, h in enumerate(header) if h == "馬名"), None)
    num_col   = next((i for i, h in enumerate(header) if h in ("馬番", "番")), None)

    # オッズ降順で人気を付ける（馬名キーに変換済みのodds_mapを想定）
    sorted_odds = sorted(odds_map.items(), key=lambda x: x[1])
    popularity  = {name: rank + 1 for rank, (name, _) in enumerate(sorted_odds)}

    updated = 0
    for row in rows[header_idx + 1:]:
        if not row:
            continue
        horse_name = row[name_col].strip() if name_col is not None and len(row) > name_col else ""
        horse_num  = row[num_col].strip()  if num_col  is not None and len(row) > num_col  else ""

        odds_val = odds_map.get(horse_name) or odds_map.get(horse_num)
        if odds_val:
            while len(row) <= max(odds_col, pop_col):
                row.append("")
            row[odds_col] = str(odds_val)
            row[pop_col]  = f"{popularity.get(horse_name, '')}人気"
            updated += 1

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)

    print(f"  [CSV更新] {os.path.basename(csv_path)}  ({updated}頭のオッズを更新)")


def print_buy_signs_from_csv(csv_path: str, odds_map: dict[str, float]) -> None:
    """CSVとオッズから買いサインを計算して表示"""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    # メタ情報行（1行目）
    meta = rows[0] if rows else []
    race_name = meta[0] if len(meta) > 0 else ""
    race_date = meta[1] if len(meta) > 1 else ""
    race_venue = meta[2] if len(meta) > 2 else ""

    # ヘッダー行
    header_idx = None
    for i, row in enumerate(rows):
        if "馬名" in row:
            header_idx = i
            break
    if header_idx is None:
        return

    header   = rows[header_idx]
    name_col = next((i for i, h in enumerate(header) if h == "馬名"), None)
    score_col = next((i for i, h in enumerate(header)
                      if "合計" in h or "スコア" in h), None)
    num_col  = next((i for i, h in enumerate(header) if h in ("馬番", "番")), None)

    if name_col is None or score_col is None:
        print("  [!] 馬名/スコア列が見つかりません")
        return

    # データ行を収集してスコア順にソート
    data_rows = []
    for row in rows[header_idx + 1:]:
        if not row or not any(row):
            continue
        name  = row[name_col].strip() if len(row) > name_col else ""
        num   = row[num_col].strip()  if num_col is not None and len(row) > num_col else ""
        try:
            score = float(row[score_col].replace("+", ""))
        except (ValueError, IndexError):
            continue
        if name:
            data_rows.append({"name": name, "num": num, "score": score})

    if len(data_rows) < 2:
        return

    sorted_rows = sorted(data_rows, key=lambda x: x["score"], reverse=True)
    top  = sorted_rows[0]
    sec  = sorted_rows[1]
    gap  = top["score"] - sec["score"]
    n    = len(data_rows)

    # オッズはnum_mapまたはname_mapで引く
    name_to_odds = odds_map  # 馬番→floatのodds_mapも考慮
    odds1 = name_to_odds.get(top["name"]) or name_to_odds.get(top["num"]) or 0

    skips = []
    buys  = []

    if odds1 and odds1 >= 8:
        skips.append(f"軸({top['name']})が{odds1:.1f}倍 → 8倍以上の軸は命中率0%")
    if n >= 14:
        skips.append(f"{n}頭立て → 14頭以上は命中率7%")
    if 3 <= gap < 5:
        skips.append(f"1〜2位スコア差{gap:.1f}pt（3〜5ptゾーン）→ 命中率9%")

    if gap >= 5:
        buys.append(f"スコア乖離{gap:.1f}pt（5pt以上）→ ROI112%ゾーン")
    if odds1 and 2 <= odds1 < 8:
        buys.append(f"軸({top['name']})オッズ{odds1:.1f}倍（2〜7倍台）")
    if n <= 9:
        buys.append(f"少頭数({n}頭) → 命中率34%")

    if odds1:
        top_sign = gap >= 5 and 2 <= odds1 < 8 and n <= 13
    else:
        top_sign = gap >= 5 and n <= 13

    print(f"\n{'='*60}")
    print(f"  {race_name}  {race_date}  {race_venue}")
    print(f"  1位: {top['name']} ({top['score']:+.1f}pt)  "
          f"2位: {sec['name']} ({sec['score']:+.1f}pt)  "
          f"乖離: {gap:.1f}pt  {n}頭立て"
          + (f"  軸オッズ: {odds1:.1f}倍" if odds1 else ""))
    print(f"{'─'*60}")
    print("─ 買い判断サイン ─")
    if top_sign:
        print("  🎯 最強買いサイン: 全条件クリア → ROI193%ゾーン（フォームB全力）")
    if skips:
        for s in skips:
            print(f"  ⚠  見送り推奨: {s}")
    if buys:
        for b in buys:
            print(f"  ✅ 買いサイン: {b}")
    if not skips and not buys and not top_sign:
        print("  ─ 特記なし（ベースライン ROI44%）")


def main():
    if len(sys.argv) < 2:
        print("使い方: python3 update_odds.py <race_id または CSVファイルパス>")
        sys.exit(1)

    arg = sys.argv[1]

    # race_id or CSVパスの判定
    if arg.endswith(".csv"):
        csv_path = arg
        m = re.search(r"prediction_(\d{12})", os.path.basename(csv_path))
        race_id = m.group(1) if m else None
    else:
        race_id = arg
        csv_path = find_csv(race_id)
        if not csv_path:
            # 直近の予想CSVを全検索
            pattern = os.path.join(os.path.dirname(__file__), f"prediction_*.csv")
            all_csvs = sorted(glob.glob(pattern))
            if all_csvs:
                csv_path = all_csvs[-1]
                print(f"  [CSV] 直近のCSVを使用: {os.path.basename(csv_path)}")
            else:
                print(f"  [!] prediction_{race_id}_*.csv が見つかりません")
                sys.exit(1)

    print(f"\n[オッズ更新] race_id={race_id}  CSV={os.path.basename(csv_path)}")

    # オッズ取得
    if not race_id:
        print("  [!] race_idが特定できないためオッズ自動取得をスキップします")
        odds_map = {}
    else:
        from netkeiba_race_scraper import fetch_odds
        print("  netkeibaからオッズ取得中...")
        odds_num = fetch_odds(race_id)  # {馬番: オッズ}
        if not odds_num:
            print("  [!] オッズを取得できませんでした（発走前のみ有効）")
            sys.exit(1)
        print(f"  {len(odds_num)}頭分のオッズを取得: "
              + "  ".join(f"{k}番={v:.1f}倍" for k, v in sorted(odds_num.items(), key=lambda x: int(x[0]))))
        odds_map = odds_num  # 馬番→オッズ

    # CSV更新（馬番→オッズで更新）
    update_csv_with_odds(csv_path, odds_map)

    # 買いサイン表示（馬番キーのodds_mapを渡す）
    print_buy_signs_from_csv(csv_path, odds_map)


if __name__ == "__main__":
    main()
