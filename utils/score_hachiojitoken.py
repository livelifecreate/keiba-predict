"""
八王子特別 2026/6/7 東京10R ダート1400m 2勝クラス
競馬ブックPDFの調教データのみで採点（netkeiba不要版）
"""
import csv
import os

RACE_NAME = "八王子特別"
RACE_DATE = "2026年6月7日"
VENUE = "東京"
SURFACE = "ダ"
DISTANCE = 1400

# 出走馬（枠番・馬番・馬名）PDFより
ENTRIES = [
    (1, 1, "リリージェーン"),
    (1, 2, "フクチャントウメイ"),
    (2, 3, "エムティエスターテ"),
    (2, 4, "メッエフアパラ"),
    (3, 5, "ケープアグラス"),
    (3, 6, "ポッドベル"),
    (4, 7, "シホノベルフェット"),
    (4, 8, "レイアポポ"),
    (5, 9, "レヴィテーション"),
    (5, 10, "マジッククッキー"),
    (6, 11, "クインズシフォン"),
    (6, 12, "ミスエル"),
    (7, 13, "キョウエイカンセ"),
    (7, 14, "ホウオウプレミア"),
    (8, 15, "プチブール"),
    (8, 16, "ライジンマル"),
]

# 攻め解説（PDFから抽出）
ATOME = {
    "リリージェーン":     "水を含んだ馬場は応えた感じも機敏な脚捌き。気配良好",
    "フクチャントウメイ":  "先行でも持ったまま。気合十分で素軽さもある。整った",
    "エムティエスターテ": "中1週でも大きく追走してビシッと。反動は見られない",
    "メッエフアパラ":      "時計は馬場を考えれば上々。前向きでパワフル。好気配",
    "ケープアグラス":      "体は仕上がっているが、追われてからの反応が物足りず",
    "ポッドベル":          "気性を考慮して日・水に分けて軽く追い切る。疲れなし",
    "シホノベルフェット":  "大幅先行だが、OP馬に楽に食い下がる。良化は窺える",
    "レイアポポ":          "間隔が詰まるので火曜日に軽く登坂。これで十分だろう",
    "レヴィテーション":    "内から追いついて好時計を出した。体もすっきりしてる",
    "マジッククッキー":    "3頭併せの内で追われると、力強い脚捌きで追いついた",
    "クインズシフォン":    "先週の反応は今ひとつだったが、今週は動き切れていた",
    "ミスエル":            "ここにきて集中力を増して、追われると反応良く伸びる",
    "キョウエイカンセ":    "馬なりで11秒5。中2週続きでも活気は十分。好調維持",
    "ホウオウプレミア":    "やれば動くタイプ。集中力十分で推進力にも溢れている",
    "プチブール":          "コンスタントに使われながらも疲れを見せずに元気一杯",
    "ライジンマル":        "荒れた馬場でもグイグイ加速。力強さ満点で気合も上々",
}

# 脚質ヒント（攻め解説より）
STLE_HINT = {
    "フクチャントウメイ": "先行",
    "シホノベルフェット": "先行",
}


def load_training(csv_path: str) -> dict:
    data = {}
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["馬名"].strip()
            try:
                ts = int(row["時計スコア(1-5)"])
                cs = int(row["状態スコア(1-5)"])
            except (ValueError, KeyError):
                ts, cs = 0, 0
            data[name] = (ts, cs, row.get("メモ", ""))
    return data


def training_score(ts: int, cs: int) -> float:
    total = ts + cs
    if total >= 9:
        return 3.0
    elif total >= 7:
        return 2.0
    elif total >= 5:
        return 1.0
    elif total >= 3:
        return 0.0
    else:
        return -1.0


def frame_correction(frame: int, surface: str, distance: int) -> float:
    """ダート内枠（1・2枠）1600m以下: -2.0"""
    if surface == "ダ" and frame <= 2 and distance <= 1600:
        return -2.0
    return 0.0


def main():
    csv_path = os.path.join(
        os.path.dirname(__file__),
        "training_202667_八王子特別.csv"
    )
    training = load_training(csv_path)

    results = []
    for frame, num, name in ENTRIES:
        ts, cs, memo = training.get(name, (0, 0, ""))
        t_score = training_score(ts, cs)
        f_score = frame_correction(frame, SURFACE, DISTANCE)
        total = t_score + f_score

        results.append({
            "frame": frame,
            "num": num,
            "name": name,
            "t_score": t_score,
            "f_score": f_score,
            "total": total,
            "ts": ts,
            "cs": cs,
            "memo": memo,
        })

    results.sort(key=lambda x: (-x["total"], -x["ts"], -x["cs"]))

    print(f"\n{'='*72}")
    print(f"  {RACE_NAME}  {RACE_DATE}  {VENUE}  {SURFACE}{DISTANCE}m  2勝クラス")
    print(f"  ※ 調教データ（競馬ブックPDF）+ 枠番補正のみ（近走成績データなし）")
    print(f"{'='*72}")
    print(f"{'順位':>3}  {'枠':>2}{'馬番':>3}  {'馬名':<14}  {'合計':>5}  {'調教':>4}  {'枠補':>4}  短評")
    print("-" * 72)
    for rank, r in enumerate(results, 1):
        star = "★" if rank <= 5 else "  "
        print(f"{star}{rank:2}.  {r['frame']:1}枠{r['num']:2}番  {r['name']:<14}  "
              f"{r['total']:+5.1f}  {r['t_score']:+4.1f}  {r['f_score']:+4.1f}  "
              f"[時{r['ts']}状{r['cs']}] {r['memo'][:20]}")

    print(f"\n{'─'*72}")
    print("■ 攻め解説（keibabook）")
    for rank, r in enumerate(results[:8], 1):
        print(f"  {r['num']:2}番 {r['name']}: {ATOME.get(r['name'], '')}")

    print(f"\n{'─'*72}")
    print("■ 注目馬（調教評価）")
    print(f"  ◎ キョウエイカンセ(13番) … 馬なりで3F36.9、1F11.5。2週続き中間でも活気十分")
    print(f"  ○ エムティエスターテ(3番) … 強めで3F36.7最速水準。ただし2枠でダート内枠-2補正")
    print(f"  ▲ ホウオウプレミア(14番)  … 馬なりで38.4、推進力溢れる。ライジンマルも37.5")
    print(f"  △ ライジンマル(16番)     … 荒れた馬場でグイグイ、気合・力強さ満点")
    print(f"\n  ！ ダート内枠補正: 1枠(1・2番)・2枠(3・4番)は -2.0点適用")
    print(f"     近走成績データなし（netkeiba IPブロック中）のため訓練データのみの予備ランキング")
    save_csv(results)


def save_csv(results: list):
    import csv as _csv
    filename = f"score_202667_八王子特別.csv"
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.writer(f)
        writer.writerow(["順位", "枠", "馬番", "馬名", "合計スコア", "調教", "枠番補正", "時計スコア", "状態スコア", "メモ"])
        for rank, r in enumerate(results, 1):
            writer.writerow([rank, r["frame"], r["num"], r["name"],
                             f"{r['total']:+.1f}", f"{r['t_score']:+.1f}", f"{r['f_score']:+.1f}",
                             r["ts"], r["cs"], r["memo"]])
    print(f"\n  [CSV出力] {filename}")


if __name__ == "__main__":
    main()
