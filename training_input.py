"""
調教スコア入力モジュール。

【使い方】
1. scorer.py を実行すると training_YYYYMMDD_レース名.csv が自動生成される
2. 他サイト（スポーツ紙・競馬ラボなど）で調教内容を確認しながら CSV を埋める
3. 再度 scorer.py を実行すると調教スコア込みで採点される

【CSVフォーマット】
馬名,時計スコア(1-5),状態スコア(1-5),メモ
レーベンスティール,5,5,先週ウッドで自己ベスト+加速ラップ
ロングラン,3,3,単走サラッと
...

【採点基準】
■ 時計スコア（1-5）
  5: 自己ベスト（またはそれに準ずる好時計）＋ラスト加速ラップ
  4: 好時計 ＋ 加速 or ハイレベルな同速（減速なし）
  3: 平均的（失速なし）
  2: 失速ラップあり（ラスト1Fで明確に減速）
  1: 遅い時計＋終いもバテている

■ 状態スコア（1-5）
  5: 格上/同クラスを一蹴・置き去り。圧倒的なフットワーク＋勝負気配
  4: 併せ馬で手応え優勢のまま先着。上積みがフットワークに現れている
  3: 単走サラッと、または併せ馬で普通に併入。状態キープ
  2: 併せ馬で見劣り・遅れる（毎回の癖なら3点）。気性難あり
  1: 馬体太い or ガタガタ。走る気勢を著しく欠く

■ 合計スコア → 採点システムへの変換
  合計 9-10点 → +3点（自己ベスト水準・一蹴）
  合計 7-8点  → +2点（高水準）
  合計 5-6点  → +1点（標準以上）
  合計 3-4点  →  0点（標準）
  合計 2点    → -1点（不満）
"""

import csv
import os
import re
from dataclasses import dataclass


@dataclass
class TrainingInput:
    horse_name: str
    time_score: int    # 1-5
    cond_score: int    # 1-5
    memo: str = ""

    @property
    def total(self) -> int:
        return self.time_score + self.cond_score

    @property
    def converted_score(self) -> int:
        """10点満点スコア → 採点システムの加減点に変換"""
        t = self.total
        if t >= 9:
            return 3
        elif t >= 7:
            return 2
        elif t >= 5:
            return 1
        elif t >= 3:
            return 0
        else:
            return -1


def _csv_path(race_info) -> str:
    date = re.sub(r"[年月]", "", race_info.date).replace("日", "")
    name = re.sub(r"[\s　/\\:*?\"<>|]", "_", race_info.name)
    return os.path.join(
        os.path.dirname(__file__),
        f"training_{date}_{name}.csv",
    )


def generate_template(entries: list, race_info) -> str:
    """
    出走馬リストから入力用CSVテンプレートを生成する。
    既にファイルが存在する場合は上書きしない（入力済みデータを保護）。
    """
    path = _csv_path(race_info)

    if os.path.exists(path):
        print(f"  [調教入力] 既存ファイルを使用: {os.path.basename(path)}")
        return path

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["馬名", "時計スコア(1-5)", "状態スコア(1-5)", "メモ"])
        for entry in entries:
            writer.writerow([entry.horse_name, "", "", ""])

    print(f"  [調教入力] テンプレート生成: {os.path.basename(path)}")
    print(f"            → 他サイトで調教確認後、スコアを記入して再実行してください")
    return path


def load_training_input(race_info) -> dict[str, TrainingInput]:
    """
    CSVファイルからスコア入力済みデータを読み込む。
    未入力（空欄）の馬はスキップ（スコア 0 扱い）。
    """
    path = _csv_path(race_info)

    if not os.path.exists(path):
        return {}

    result = {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            horse = row.get("馬名", "").strip()
            t_raw = row.get("時計スコア(1-5)", "").strip()
            c_raw = row.get("状態スコア(1-5)", "").strip()

            if not horse or not t_raw or not c_raw:
                continue  # 未入力はスキップ

            try:
                t = max(1, min(5, int(t_raw)))
                c = max(1, min(5, int(c_raw)))
            except ValueError:
                continue

            result[horse] = TrainingInput(
                horse_name=horse,
                time_score=t,
                cond_score=c,
                memo=row.get("メモ", ""),
            )

    filled = len(result)
    if filled > 0:
        print(f"  [調教入力] {filled}頭分のスコアを読み込みました")
    else:
        print(f"  [調教入力] スコア未入力 → 調教採点をスキップ")

    return result
