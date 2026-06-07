"""
umasiru.com の追い切り評価ページからスコアを自動取得するスクレイパー。

対応URL例: https://umasiru.com/archives/XXXXX

取得データ:
  - 評価ランク（S/A/B/C/D/E）
  - 最終追い切りラップ（4F/3F/1F または 6F/3F/1F）
  - 脚色（馬なり / 末強め / 一杯 など）
  - コメント（「一蹴」「遅れ」などのキーワードを抽出）

スコア変換:
  - 状態スコア（1-5）: 評価ランク + コメントキーワード
  - 時計スコア（1-5）: ラップ加速・脚色で判定
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 全角英字 → 半角に正規化
FULLWIDTH_MAP = {ord(f): ord(h) for f, h in zip("ＡＢＣＤＥＳ", "ABCDES")}

# 評価ランク → 状態スコア基礎値
RANK_TO_COND = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "E": 1}

# コメント内キーワードによる状態スコア補正
BOOST_KEYWORDS  = ["一蹴", "置き去り", "圧倒", "抜群", "最高", "完璧", "一気"]
REDUCE_KEYWORDS = ["遅れ", "見劣り", "気性難", "頭を上げ", "モタれ", "太め", "ガタガタ", "気勢欠"]

# 脚色ラベル → 時計スコア補正値
KISEI_ADJUST = {
    "馬なり": +1,
    "末強め": 0,
    "強め":   0,
    "一杯":   -1,
}


@dataclass
class UmasiruEntry:
    horse_name: str
    rank: str               # S/A/B/C/D/E
    last1f: float           # ラスト1Fタイム（秒）
    last3f: float           # ラスト3Fタイム（秒）
    kisei: str              # 脚色
    comment: str            # コメント全文
    time_score: int         # 算出済み時計スコア (1-5)
    cond_score: int         # 算出済み状態スコア (1-5)
    keywords_found: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.time_score + self.cond_score

    @property
    def converted_score(self) -> int:
        t = self.total
        if t >= 9:  return 3
        if t >= 7:  return 2
        if t >= 5:  return 1
        if t >= 3:  return 0
        return -1


def _normalize(text: str) -> str:
    return text.translate(FULLWIDTH_MAP).strip()


def _calc_time_score(last1f: float, last3f: float, kisei: str) -> int:
    """
    時計スコア（1-5）を算出する。

    ラップ加速判定:
      2F分の時間 = 3F - 1F
      2F平均 = (3F - 1F) / 2
      1F < 2F平均 → 加速ラップ → +1
      1F > 2F平均 → 失速ラップ → -1
    """
    if last1f <= 0 or last3f <= 0:
        return 3  # データなし → 標準

    two_f = last3f - last1f          # 直前2Fにかかった秒数
    two_f_avg = two_f / 2            # 2F平均（1F換算）

    if last1f < two_f_avg - 0.2:    # 明確な加速
        lap_bonus = 1
    elif last1f > two_f_avg + 0.3:  # 明確な失速
        lap_bonus = -1
    else:
        lap_bonus = 0

    kisei_bonus = KISEI_ADJUST.get(kisei, 0)

    base = 3 + lap_bonus + kisei_bonus
    return max(1, min(5, base))


def _calc_cond_score(rank: str, comment: str) -> tuple[int, list[str]]:
    """
    状態スコア（1-5）とヒットしたキーワードリストを返す。
    """
    base = RANK_TO_COND.get(rank, 3)
    found = []

    for kw in BOOST_KEYWORDS:
        if kw in comment:
            base = min(5, base + 1)
            found.append(f"+{kw}")
            break  # 加点は1回まで

    for kw in REDUCE_KEYWORDS:
        if kw in comment:
            base = max(1, base - 1)
            found.append(f"-{kw}")
            break  # 減点は1回まで

    return base, found


def scrape(url: str) -> dict[str, UmasiruEntry]:
    """
    umasiru.com の追い切りページをスクレイプして {馬名: UmasiruEntry} を返す。
    """
    time.sleep(0.5)
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.content, "lxml")

    results = {}

    for h3 in soup.find_all("h3"):
        horse_name = h3.get_text(strip=True)
        if "取消" in horse_name or "除外" in horse_name:
            continue

        # テーブルを取得
        table = h3.find_next("figure", class_="wp-block-table")
        if not table:
            continue

        cells = [_normalize(td.get_text(strip=True)) for td in table.find_all(["td", "th"])]

        # 評価ランクを抽出（先頭セルに "評価X" 形式）
        rank = "B"
        for cell in cells[:3]:
            m = re.search(r"評価([SABCDE])", cell)
            if m:
                rank = m.group(1)
                break

        # 最終追い切り行のラップを取得
        last1f = last3f = 0.0
        kisei  = "馬なり"
        for i, cell in enumerate(cells):
            if cell == "最終追切":
                row = cells[i: i + 10]
                # 数値セルを集める
                nums = []
                for c in row[1:]:
                    try:
                        nums.append(float(c))
                    except ValueError:
                        pass
                if nums:
                    last1f = nums[-1]
                    last3f = nums[-2] if len(nums) >= 2 else 0.0
                # 脚色（数値でないセルのうち既知ラベルを探す）
                for c in row:
                    for label in KISEI_ADJUST:
                        if label in c:
                            kisei = label
                            break
                break

        # コメント（p タグ全結合）
        comment_parts = []
        for sib in h3.find_next_siblings():
            if sib.name == "h3":
                break
            if sib.name == "p":
                comment_parts.append(sib.get_text(strip=True))
        comment = " ".join(comment_parts)

        time_score = _calc_time_score(last1f, last3f, kisei)
        cond_score, kw_found = _calc_cond_score(rank, comment)

        results[horse_name] = UmasiruEntry(
            horse_name     = horse_name,
            rank           = rank,
            last1f         = last1f,
            last3f         = last3f,
            kisei          = kisei,
            comment        = comment[:200],
            time_score     = time_score,
            cond_score     = cond_score,
            keywords_found = kw_found,
        )

    return results


def print_results(results: dict[str, UmasiruEntry]):
    print(f"\n{'馬名':<16} {'評価':>3} {'脚色':<6} {'1F':>5} {'3F':>6} "
          f"{'時計':>4} {'状態':>4} {'合計':>4} {'→':>3}  {'備考'}")
    print("-" * 75)
    for name, e in sorted(results.items(), key=lambda x: -x[1].total):
        kw = " ".join(e.keywords_found)
        print(
            f"{name:<16} {e.rank:>3}  {e.kisei:<6} {e.last1f:>5.1f} {e.last3f:>6.1f} "
            f"{e.time_score:>4} {e.cond_score:>4} {e.total:>4} {e.converted_score:>+3}  {kw}"
        )


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "https://umasiru.com/archives/20215"
    print(f"取得中: {url}")
    results = scrape(url)
    print_results(results)
