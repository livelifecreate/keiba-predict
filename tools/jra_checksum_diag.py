"""
JRAチェックサム自動診断・自動修正スクリプト

【いつ使うか】
  python3 weekend_predict.py で [オッズ] 取得失敗 が複数レースで連続して出た時。
  特に「パラメータエラー JRA」が返っている場合はチェックサム式が変更された可能性大。

【使い方】
  python3 tools/jra_checksum_diag.py          # 診断のみ
  python3 tools/jra_checksum_diag.py --fix    # 差異があればjra_scraper.pyを自動更新

【仕組み】
  1. JRAトップ (www.jra.go.jp) から今週の出馬表URLを収集
  2. 現在のコードで計算したチェックサムと比較
  3. 不一致なら連立方程式で係数を逆算
  4. --fix 指定時は jra_scraper.py を自動書き換え
"""

import argparse
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

JRA_URL = "https://www.jra.go.jp"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
CNAME_RE = re.compile(r'pw01dde01(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})/([0-9A-Fa-f]{2})')


def fetch_jra_urls() -> list[dict]:
    """JRAトップページから今週の出馬表URLを全収集する"""
    urls = []
    seen = set()
    pages = ["/", "/keiba/thisweek/"]
    for path in pages:
        try:
            r = requests.get(JRA_URL + path, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.content, "html.parser", from_encoding="shift_jis")
            for a in soup.find_all("a", href=True):
                m = CNAME_RE.search(a["href"])
                if not m:
                    continue
                venue, year, kai, nichi, race, date, cs_hex = m.groups()
                key = (venue, year, kai, nichi, race)
                if key in seen:
                    continue
                seen.add(key)
                urls.append({
                    "venue": int(venue), "year": int(year), "kai": int(kai),
                    "nichi": int(nichi), "race": int(race), "date": date,
                    "cs_actual": int(cs_hex, 16),
                })
        except Exception as e:
            print(f"  [fetch] {path}: {e}")
    return urls


def calc_checksum(venue: int, kai: int, nichi: int, race: int,
                  I0: int, v_coeff: int, k_coeff: int, n_coeff: int) -> int:
    race_contrib = ((race - 1) * 181 + (64 if race >= 10 else 0)) % 256
    base = (I0 + venue * v_coeff + kai * k_coeff + nichi * n_coeff) % 256
    return (base + race_contrib) % 256


def load_current_coeffs() -> tuple[int, int, int, int]:
    """jra_scraper.py から現在の係数を読み取る"""
    scraper = BASE_DIR / "jra_scraper.py"
    text = scraper.read_text()

    m_rc = re.search(r'race_contrib\s*=\s*\((.+?)\)\s*%\s*256', text)
    m_base = re.search(r'base\s*=\s*\((.+?)\)\s*%\s*256', text)

    if not m_rc or not m_base:
        print("[ERROR] jra_scraper.py から係数を読み取れませんでした")
        sys.exit(1)

    base_expr = m_base.group(1)

    nums = re.findall(r'\b(\d+)\b', base_expr)
    nums = [int(n) for n in nums]

    # "20 + venue*157 + kai*210 + nichi*48" のような形式
    # venue*, kai*, nichi* の係数を抽出
    I0 = int(re.search(r'^(\d+)\s*\+', base_expr).group(1)) if re.match(r'^\d+\s*\+', base_expr) else 0
    v = int(re.search(r'venue\s*\*\s*(\d+)', base_expr).group(1))
    k = int(re.search(r'kai\s*\*\s*(\d+)', base_expr).group(1))
    n = int(re.search(r'nichi\s*\*\s*(\d+)', base_expr).group(1))
    return I0, v, k, n


def solve_coeffs(data: list[dict]) -> tuple[int, int, int, int] | None:
    """
    データ点から係数を逆算する。
    race間の差分 = 181 (race>=10で+64) は固定なので、
    base = (I0 + venue*v + kai*k + nichi*n) の係数を求める。

    手順:
    1. 同じrace番号のデータ点間で nichi差→nichi係数を確定
    2. venue係数・kai係数をモジュラー逆算
    3. 初期値 I0 を計算
    """
    if len(data) < 3:
        print(f"  [solver] データ点が不足 ({len(data)}件, 最低3件必要)")
        return None

    # race_contrib を除いた「baseのみ」の値を求める
    def base_from(d: dict, v: int, k: int, n: int, I0: int) -> int:
        rc = ((d["race"] - 1) * 181 + (64 if d["race"] >= 10 else 0)) % 256
        return (d["cs_actual"] - rc) % 256

    # nichi係数: 同venue・同kai・race同じで nichi違いのペアを探す
    n_coeff = None
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            a, b = data[i], data[j]
            if a["venue"] == b["venue"] and a["kai"] == b["kai"] and a["race"] == b["race"] and a["nichi"] != b["nichi"]:
                rc_a = ((a["race"] - 1) * 181 + (64 if a["race"] >= 10 else 0)) % 256
                rc_b = ((b["race"] - 1) * 181 + (64 if b["race"] >= 10 else 0)) % 256
                diff_cs = (b["cs_actual"] - rc_b - (a["cs_actual"] - rc_a)) % 256
                diff_n = (b["nichi"] - a["nichi"]) % 256
                if diff_n == 0:
                    continue
                # diff_cs = n_coeff * diff_n  (mod 256)
                inv = pow(diff_n, -1, 256)
                n_coeff = (diff_cs * inv) % 256
                break
        if n_coeff is not None:
            break

    if n_coeff is None:
        n_coeff = 48  # デフォルト（不変であることが多い）
        print(f"  [solver] nichi係数: デフォルト48を使用")
    else:
        print(f"  [solver] nichi係数: {n_coeff}")

    # venue係数: 同kai・同nichi・同raceでvenueが異なるペアが理想だが、
    # 通常 同kaiで同nichiのペアは取れないため kai差・nichi差を含むペアも使う
    v_coeff = None

    # まず理想的なペア（kai・nichi・race全て同じ）を探す
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            a, b = data[i], data[j]
            if a["kai"] == b["kai"] and a["nichi"] == b["nichi"] and a["race"] == b["race"] and a["venue"] != b["venue"]:
                rc = ((a["race"] - 1) * 181 + (64 if a["race"] >= 10 else 0)) % 256
                base_a = (a["cs_actual"] - rc) % 256
                base_b = (b["cs_actual"] - rc) % 256
                diff_base = (base_b - base_a) % 256
                diff_v = (b["venue"] - a["venue"]) % 256
                if diff_v == 0:
                    continue
                inv = pow(diff_v, -1, 256)
                v_coeff = (diff_base * inv) % 256
                break
        if v_coeff is not None:
            break

    if v_coeff is None:
        print(f"  [solver] venue係数: 算出不可（同kai同nichiでvenueが異なるペアなし）")
        return None
    print(f"  [solver] venue係数: {v_coeff}")

    # kai係数: venue係数が既知なので、差分からvenueとnichの寄与を除いてkaiを求める
    # base_diff = v_coeff*(Δvenue) + k_coeff*(Δkai) + n_coeff*(Δnichi)
    # k_coeff*(Δkai) = base_diff - v_coeff*(Δvenue) - n_coeff*(Δnichi)
    k_coeff = None
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            a, b = data[i], data[j]
            if a["race"] == b["race"] and a["kai"] != b["kai"]:
                rc = ((a["race"] - 1) * 181 + (64 if a["race"] >= 10 else 0)) % 256
                base_a = (a["cs_actual"] - rc) % 256
                base_b = (b["cs_actual"] - rc) % 256
                diff_base = (base_b - base_a) % 256
                diff_v_contrib = (v_coeff * (b["venue"] - a["venue"])) % 256
                diff_n_contrib = (n_coeff * (b["nichi"] - a["nichi"])) % 256
                diff_k = (b["kai"] - a["kai"]) % 256
                if diff_k == 0:
                    continue
                remaining = (diff_base - diff_v_contrib - diff_n_contrib) % 256
                inv = pow(diff_k, -1, 256)
                k_coeff = (remaining * inv) % 256
                break
        if k_coeff is not None:
            break

    if k_coeff is None:
        print(f"  [solver] kai係数: 算出不可（kaiが異なるペアなし）")
        return None
    print(f"  [solver] kai係数: {k_coeff}")

    # I0 の計算（任意のデータ点から）
    d = data[0]
    rc = ((d["race"] - 1) * 181 + (64 if d["race"] >= 10 else 0)) % 256
    base_val = (d["cs_actual"] - rc) % 256
    I0 = (base_val - d["venue"] * v_coeff - d["kai"] * k_coeff - d["nichi"] * n_coeff) % 256
    print(f"  [solver] I0: {I0}")

    return I0, v_coeff, k_coeff, n_coeff


def update_scraper(I0: int, v: int, k: int, n: int) -> bool:
    """jra_scraper.py のチェックサム行を書き換える"""
    scraper = BASE_DIR / "jra_scraper.py"
    text = scraper.read_text()

    old_rc = re.search(r'    race_contrib = .+\n', text)
    old_base = re.search(r'    base = .+\n', text)
    if not old_rc or not old_base:
        print("[ERROR] 書き換え対象行が見つかりません")
        return False

    new_rc = f"    race_contrib = ((race - 1) * 181 + (64 if race >= 10 else 0)) % 256\n"
    new_base = f"    base = ({I0} + venue * {v} + kai * {k} + nichi * {n}) % 256\n"

    text2 = text.replace(old_rc.group(0), new_rc, 1)
    text2 = text2.replace(old_base.group(0), new_base, 1)

    if text2 == text:
        print("[INFO] 変更なし（既に最新の式）")
        return False

    scraper.write_text(text2)
    print(f"[OK] jra_scraper.py を更新しました")
    print(f"     race_contrib = ((race - 1) * 181 + (64 if race >= 10 else 0)) % 256")
    print(f"     base = ({I0} + venue * {v} + kai * {k} + nichi * {n}) % 256")
    return True


def main():
    parser = argparse.ArgumentParser(description="JRAチェックサム自動診断・自動修正")
    parser.add_argument("--fix", action="store_true", help="不一致があれば jra_scraper.py を自動更新")
    args = parser.parse_args()

    print("=== JRAチェックサム診断 ===\n")

    # Step1: JRAから実URLを収集
    print("Step1: JRAトップから出馬表URLを収集中...")
    data = fetch_jra_urls()
    if not data:
        print("[ERROR] URLが1件も取得できませんでした。JRAサイトへのアクセスを確認してください。")
        sys.exit(1)
    print(f"  {len(data)}件のURLを取得")

    # Step2: 現在の係数で計算して比較
    print("\nStep2: 現在の係数でチェックサム検証...")
    I0_cur, v_cur, k_cur, n_cur = load_current_coeffs()
    print(f"  現在の式: ({I0_cur} + venue*{v_cur} + kai*{k_cur} + nichi*{n_cur}) + race_contrib")

    mismatches = []
    for d in data:
        calc = calc_checksum(d["venue"], d["kai"], d["nichi"], d["race"], I0_cur, v_cur, k_cur, n_cur)
        if calc != d["cs_actual"]:
            mismatches.append(d)

    if not mismatches:
        print(f"  [OK] 全{len(data)}件一致。チェックサム式に問題なし。")
        return

    print(f"  [NG] {len(mismatches)}/{len(data)}件で不一致！")
    print("\n  不一致の例:")
    for d in mismatches[:4]:
        calc = calc_checksum(d["venue"], d["kai"], d["nichi"], d["race"], I0_cur, v_cur, k_cur, n_cur)
        print(f"    venue={d['venue']:2d} kai={d['kai']} nichi={d['nichi']} race={d['race']:2d}: "
              f"計算=0x{calc:02X} 実際=0x{d['cs_actual']:02X}")

    # Step3: 新しい係数を逆算
    print("\nStep3: 新しい係数を逆算中...")
    result = solve_coeffs(data)
    if result is None:
        print("\n[ERROR] 係数逆算に失敗しました。データが不足しています。")
        print("  JRAトップに複数会場・複数日のリンクが出るタイミング（金曜以降）に再実行してください。")
        sys.exit(1)

    I0_new, v_new, k_new, n_new = result

    # Step4: 新係数で全データ検証
    print("\nStep4: 新しい係数で全データ検証...")
    errors = 0
    for d in data:
        calc = calc_checksum(d["venue"], d["kai"], d["nichi"], d["race"], I0_new, v_new, k_new, n_new)
        if calc != d["cs_actual"]:
            errors += 1
    print(f"  {len(data) - errors}/{len(data)}件一致" + (" [OK]" if errors == 0 else f" [{errors}件不一致]"))

    if errors > 0:
        print("[WARN] 新しい係数でも不一致が残ります。手動確認が必要です。")
        sys.exit(1)

    # Step5: 自動修正
    if args.fix:
        print("\nStep5: jra_scraper.py を自動更新...")
        update_scraper(I0_new, v_new, k_new, n_new)
        print("\n完了。saturday_predict.py を再実行してオッズが取得できるか確認してください。")
    else:
        print(f"\n--fix を指定すると jra_scraper.py を自動更新します:")
        print(f"  python3 tools/jra_checksum_diag.py --fix")


if __name__ == "__main__":
    main()
