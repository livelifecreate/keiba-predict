"""
競馬予想採点システム（拡張版）

自動採点:
  +5: 前走G2以上で0.2秒差以内の惜敗 or 勝利
  +4: 前走上がり3FがメンバーWで最速（タイ含む）
  +4: 近4戦以内に同コース（同競馬場・同距離・同芝ダ）で1着
  +3: 前走G2以上で0.2〜0.5秒差の惜敗
  +1: 叩き2戦目（2走前から前走が2ヶ月以上空きの休み明け）
  -2/-3/-5: 初ダート or 初の芝（未勝利-2 / 1勝クラス-3 / 2勝以上-5）
  -2/-3/-5: 距離延長1ハロン(200m)以上（未勝利-2 / 1勝クラス-3 / 2勝以上-5、前走G1勝ち→0免除）
  -4: 昇級初戦（前走1着 かつ 今回がクラスアップ）
  -4: 前走が特殊条件（障害戦 / 海外競馬）
  -4: 前走がローカル競馬場
  -3: 6ヶ月以上の休み明け
  枠番補正（芝1600m: 4枠+0.5/1枠-0.5、芝1400m: 5・6枠+0.5/2・7枠-0.5、ダ1600m以下内枠-2.0）
  -3: トップハンデ斤量（出走馬中最重量）
  -2: 急坂コース（中山・阪神・中京）で好走歴なし
  -2: 馬体重±15kg以上変動（前走 vs 2走前）
  -1: 今回の回り方向（右回り/左回り）で好走歴なし
  -1: 冬（12〜2月）の牝馬 / 夏（7〜9月）の牡馬・せん

手動チェック（出力に表示）:
  +5: コースマイスタージョッキー（騎手のコース勝率50%以上）
  +3: 調教最終追い切りで自己ベスト更新 or 併せ馬一蹴
  +3: 内枠（1〜3枠）の先行馬 ← 枠番は自動検出・脚質は要手動確認
  -5: 前走逃げて好走
  -5: ダートで前走牝馬限定戦
"""

import re
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# -------------------------------------------------------------------
# 定数
# -------------------------------------------------------------------
CENTRAL = {"東京", "中山", "京都", "阪神", "中京"}
LOCAL   = {"福島", "新潟", "小倉", "函館", "札幌"}
ALL_VENUES = CENTRAL | LOCAL

STEEP_COURSES  = {"中山", "阪神", "中京"}
LEFT_TURN      = {"東京", "中京", "新潟", "函館"}
RIGHT_TURN     = {"中山", "阪神", "京都", "福島", "小倉", "札幌"}

SPECIAL_KEYWORDS = {"障害", "ハードル", "障碍"}  # 特殊条件レース

WINTER_MONTHS = {12, 1, 2}
SUMMER_MONTHS = {7, 8, 9}

CLASS_RANK = {
    "未勝利": 0,
    "1勝クラス": 1, "500万下": 1,
    "2勝クラス": 2, "1000万下": 2,
    "3勝クラス": 3, "1600万下": 3,
    "オープン": 4, "リステッド": 4,
    "G3": 5, "GⅢ": 5,
    "G2": 6, "GⅡ": 6,
    "G1": 7, "GⅠ": 7,
}

# JRAレース名には grade 表記が含まれないため、名称から grade を引く
RACE_GRADE_MAP: dict[str, int] = {
    # G1 (7)
    "天皇賞": 7, "安田記念": 7, "宝塚記念": 7, "有馬記念": 7, "大阪杯": 7,
    "皐月賞": 7, "日本ダービー": 7, "東京優駿": 7, "菊花賞": 7,
    "秋華賞": 7, "エリザベス女王杯": 7, "ジャパンカップ": 7, "ジャパンC": 7,
    "スプリンターズS": 7, "スプリンターズステークス": 7,
    "マイルCS": 7, "マイルチャンピオンシップ": 7,
    "NHKマイルC": 7, "NHKマイルカップ": 7,
    "ヴィクトリアマイル": 7, "フェブラリーS": 7, "フェブラリーステークス": 7,
    "チャンピオンズC": 7, "チャンピオンズカップ": 7,
    "ジャパンダートC": 7, "ジャパンダートクラシック": 7,
    "朝日杯FS": 7, "朝日杯フューチュリティS": 7,
    "阪神JF": 7, "阪神ジュベナイルF": 7,
    "ホープフルS": 7, "ホープフルステークス": 7,
    "高松宮記念": 7, "桜花賞": 7, "オークス": 7,
    "優駿牝馬": 7,
    # G2 (6)
    "中山記念": 6, "金鯱賞": 6, "京都記念": 6, "阪神大賞典": 6,
    "日経新春杯": 6, "日経賞": 6,
    "AJCC": 6, "アメリカジョッキークラブカップ": 6, "アメリカJCC": 6,
    "毎日王冠": 6, "オールカマー": 6, "神戸新聞杯": 6, "セントライト記念": 6,
    "富士S": 6, "富士ステークス": 6,
    "フローラS": 6, "青葉賞": 6, "京都新聞杯": 6,
    "マイラーズC": 6, "マイラーズカップ": 6,
    "エプソムC": 6, "エプソムカップ": 6,
    "鳴尾記念": 6, "マーメイドS": 6,
    "デイリー杯": 6, "東京新聞杯": 6,
    "ダービー卿CT": 6, "ダービーCT": 6,
    "新潟大賞典": 6, "函館記念": 6, "小倉記念": 6,
    "札幌記念": 6, "関屋記念": 6, "新潟記念": 6,
    "中京記念": 6,
    "スワンS": 6, "スプリングS": 6, "弥生賞": 6,
    "ローズS": 6, "紫苑S": 6,
    "チャレンジC": 6, "チャレンジカップ": 6,
    "京阪杯": 6,
    "目黒記念": 6, "ユニコーンS": 6,
    "府中牝馬S": 6, "京王杯SC": 6, "京王杯スプリングC": 6,
    "東京スポーツ杯": 6, "ニュージーランドT": 6,
    # G3 (5)
    "中山金杯": 5, "京都金杯": 5, "ニューイヤーS": 5,
    "シンザン記念": 5, "京成杯": 5,
    "きさらぎ賞": 5, "クイーンC": 5, "共同通信杯": 5,
    "アーリントンC": 5, "ファルコンS": 5, "フラワーC": 5,
    "アンタレスS": 5,
    "福島牝馬S": 5,
    "葵S": 5,
    "巴賞": 5, "七夕賞": 5, "プロキオンS": 5,
    "小倉2歳S": 5, "北九州記念": 5, "レパードS": 5,
    "エルムS": 5, "カペラS": 5, "シリウスS": 5, "マリーンC": 5,
    "キーンランドC": 5, "札幌2歳S": 5,
    "エニフS": 5,
    "ラジオNIKKEI賞": 5,
    "アルテミスS": 5,
    "カシオペアS": 5,
    "京都2歳S": 5, "ターコイズS": 5,
    "クイーンS": 5,
}

HIGH_GRADE_MIN = 6  # G2以上を「ハイレベル重賞」とする


# -------------------------------------------------------------------
# データクラス
# -------------------------------------------------------------------
@dataclass
class PastRace:
    date: str
    venue: str
    race_name: str
    position: int        # 着順（0=不明）
    field_size: int
    distance: str        # "1600m" 形式
    surface: str         # "芝" or "ダ"
    last_3f: float       # 上がり3F秒（0=不明）
    race_class: int      # CLASS_RANK の値
    margin: float        # 勝ち馬との差（1着の場合は2着への着差）秒
    horse_weight: int    # 馬体重 kg（0=不明）
    is_overseas: bool    # 海外競馬フラグ
    first_corner: int    # 1コーナー通過順位（0=不明）
    last_corner: int = 0 # 最終コーナー通過順位（0=不明）


@dataclass
class ScoreBreakdown:
    # 加点
    prev_high_grade_close:  float = 0.0  # +5 or +3（前走G2以上惜敗/勝利）
    prev2_high_grade_close: float = 0.0  # +3 or +2（前々走G2以上惜敗/勝利）
    fastest_3f:             float = 0.0  # +4/+2（前走3F最速：3着以内→+4、3着外→+2）
    same_course:            float = 0.0  # +4
    training_rank:          float = 0.0  # +3（調教A評価）
    second_start:           float = 0.0  # +1
    rising_trend:           float = 0.0  # +1（直近3走で着順連続改善）
    distance_drop:          float = 0.0  # +1（前走より200m以上距離短縮）
    prev_run_bonus:         float = 0.0  # +2/+1（前走好走ボーナス：G2未満1着→+2、2着→+1）
    prev2_run_bonus:        float = 0.0  # +1/+0.5（前々走好走ボーナス：G2未満1着→+1、2着→+0.5）
    grade_history:          float = 0.0  # +1〜+3（3・4走前G1〜OP 1・2着）
    bloodline_distance:     float = 0.0  # -1.5〜+1.5（血統距離適性）
    # 減点（合計上限 -5.0）
    first_surface:         float = 0.0  # -5
    distance_up:           float = 0.0  # -5
    promotion:             float = 0.0  # -2
    special_condition:     float = 0.0  # -4
    local_prev:            float = 0.0  # -3/-1/0
    long_rest:             float = 0.0  # -3
    post_surface:          float = 0.0  # 枠番補正（実データ基準）芝1400/1600は±0.5、ダ内枠-2.0
    inner_post_senko:      float = 0.0  # +3 内枠先行ボーナス（脚質自動検出）
    light_weight:          float = 0.0  # +1
    place_consistency:     float = 0.0  # +2/+3（直近5走で3着以内3回以上）
    no_steep_win:          float = 0.0  # -2
    weight_change:         float = 0.0  # -2
    wrong_direction:       float = 0.0  # -1
    seasonal_sex:          float = 0.0  # -1
    track_condition:       float = 0.0  # -2〜+2（道悪適性）
    # 手動チェック用（自動採点には含めない）
    manual_inner_post: bool = False  # 内枠（1〜3枠）→ 先行確認要

    @property
    def total(self) -> float:
        positives = (
            self.prev_high_grade_close
            + self.prev2_high_grade_close
            + self.fastest_3f
            + self.same_course
            + self.training_rank
            + self.second_start
            + self.rising_trend
            + self.distance_drop
            + self.prev_run_bonus
            + self.prev2_run_bonus
            + self.grade_history
            + self.inner_post_senko
            + max(self.bloodline_distance, 0.0)
            + max(self.track_condition, 0.0)
        )
        negatives = (
            self.first_surface
            + self.distance_up
            + self.promotion
            + self.special_condition
            + self.local_prev
            + self.long_rest
            + self.post_surface
            + self.light_weight
            + self.place_consistency
            + self.no_steep_win
            + self.weight_change
            + self.wrong_direction
            + self.seasonal_sex
            + min(self.bloodline_distance, 0.0)
            + min(self.track_condition, 0.0)
        )
        return positives + max(negatives, -5.0)


# -------------------------------------------------------------------
# パース関数
# -------------------------------------------------------------------
def parse_race_class(race_name: str) -> int:
    import unicodedata
    name = unicodedata.normalize("NFKC", race_name)  # 全角→半角正規化
    # 固有レース名を先に判定（netkeibaのGIII/GII付きレース名より正確）
    for key, rank in RACE_GRADE_MAP.items():
        if key in name:
            return rank
    if name.endswith("GIII"): return 5
    if name.endswith("GII"):  return 6
    if name.endswith("GI"):   return 7
    for key, rank in CLASS_RANK.items():
        if key in name:
            return rank
    return 4  # 不明はオープン扱い


def parse_date(date_str: str) -> Optional[datetime]:
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def is_overseas(text: str) -> bool:
    """海外競馬かどうか判定（国内競馬場名が見つからない場合）"""
    return not any(v in text for v in ALL_VENUES)


def parse_past_race(text: str) -> Optional[PastRace]:
    if not text:
        return None

    overseas = is_overseas(text)

    # 競馬場
    venue_match = re.search(r"(東京|中山|阪神|京都|中京|新潟|福島|小倉|札幌|函館)", text)
    venue = venue_match.group(1) if venue_match else ""

    # 日付
    date_match = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", text)
    date = date_match.group(1) if date_match else ""

    # レース名（競馬場の直後〜着順表記の直前）
    # 例: "東京スポーツ杯2歳SGII1着..." → "東京スポーツ杯2歳SGII"
    race_name = ""
    if venue_match:
        after_venue = text[venue_match.end():]
        rn_match = re.match(r"(.+?)(?=\d+着)", after_venue)
        if not rn_match:
            rn_match = re.match(r"([^\d]+)", after_venue)
        race_name = rn_match.group(1).strip() if rn_match else ""

    # 特殊条件チェック
    is_special = any(kw in race_name for kw in SPECIAL_KEYWORDS)

    # 着順
    # フォーマット1: "1:46.310着" → 時刻末尾1桁 + 着順1〜2桁
    # フォーマット2: "GI6着15頭" → 非数字の直後の1〜2桁
    time_pos = re.search(r"\d:\d{2}\.\d(\d{1,2})着", text)
    if time_pos:
        position = int(time_pos.group(1))
    else:
        pos_match = re.search(r"(?<!\d)(\d{1,2})着", text)
        position = int(pos_match.group(1)) if pos_match else 0

    # 頭数
    field_match = re.search(r"(\d+)頭", text)
    field_size = int(field_match.group(1)) if field_match else 0

    # 距離・馬場（"2000芝" と "芝1800(外)" の両フォーマット対応）
    dist_surf_match = re.search(r"(\d{3,4})(芝|ダ)", text)
    surf_dist_match = re.search(r"(芝|ダ)(\d{3,4})", text)
    if dist_surf_match:
        distance = dist_surf_match.group(1) + "m"
        surface = dist_surf_match.group(2)
    elif surf_dist_match:
        surface = surf_dist_match.group(1)
        distance = surf_dist_match.group(2) + "m"
    else:
        distance = ""
        surface = ""

    # 上がり3F
    last3f_match = re.search(r"3F\s+([\d.]+)", text)
    last_3f = float(last3f_match.group(1)) if last3f_match else 0.0

    # 馬体重（例: 492kg）
    hw_match = re.search(r"(\d{3,4})kg", text)
    horse_weight = int(hw_match.group(1)) if hw_match else 0

    # 勝ち馬との差（テキスト末尾の括弧内数値）
    margin_match = re.search(r"\(([\d.]+)\)\s*$", text.strip())
    margin = float(margin_match.group(1)) if margin_match else 0.0

    # コーナー通過順位
    corner_m = re.search(r"1角:(\d+)", text)
    first_corner = int(corner_m.group(1)) if corner_m else 0
    last_corner_m = re.search(r"4角:(\d+)", text)
    last_corner = int(last_corner_m.group(1)) if last_corner_m else 0

    return PastRace(
        date=date,
        venue=venue,
        race_name=race_name,
        position=position,
        field_size=field_size,
        distance=distance,
        surface=surface,
        last_3f=last_3f,
        race_class=parse_race_class(race_name),
        margin=margin,
        horse_weight=horse_weight,
        is_overseas=overseas,
        first_corner=first_corner,
        last_corner=last_corner,
    )


# -------------------------------------------------------------------
# 個別採点関数
# -------------------------------------------------------------------
def check_prev_high_grade(recent: list[PastRace]) -> int:
    """前走G2以上での惜敗 or 勝利
    前走G1で近差なし（ただし2.0秒以内）→ 2走前のG2+実績も評価（G1試走パターン）
    """
    if not recent:
        return 0
    p = recent[0]
    if p.race_class < HIGH_GRADE_MIN:
        return 0
    if p.position == 1:
        return 5
    if 0 < p.margin <= 0.2:
        return 5
    if 0.2 < p.margin <= 0.5:
        return 3
    # 前走G1で大差（margin>0.5）だが0.5以下ではない → 2走前G2+を減額評価
    if p.race_class >= 7 and p.margin <= 2.0 and len(recent) > 1:
        p2 = recent[1]
        if p2.race_class >= HIGH_GRADE_MIN:
            if p2.position == 1:
                return 3   # 前々走G2+勝ち（皐月賞試走→ダービー など）
            if 0 < p2.margin <= 0.2:
                return 3
            if 0.2 < p2.margin <= 0.5:
                return 2
    return 0


def check_fastest_3f(my_3f: float, all_3f: list[float], prev_pos: int = 0) -> int:
    """前走上がり3F最速：3着以内→+4、3着外→+2"""
    valid = [t for t in all_3f if t > 0]
    if valid and my_3f > 0 and my_3f == min(valid):
        return 4 if (prev_pos > 0 and prev_pos <= 3) else 2
    return 0


def check_same_course(recent: list[PastRace], venue: str, distance: str, surface: str) -> int:
    """近4戦以内に同コース1着（同距離+4 / 距離差400m以内+2）"""
    try:
        dist_m = int(distance.replace("m", ""))
    except ValueError:
        dist_m = 0
    nearby = 0
    for p in recent[:4]:
        if p.position != 1 or p.venue != venue or p.surface != surface:
            continue
        if p.distance == distance:
            return 4
        if dist_m:
            try:
                p_dist = int(p.distance.replace("m", ""))
                if abs(p_dist - dist_m) <= 400:
                    nearby = 2
            except ValueError:
                pass
    return nearby


def check_second_start(recent: list[PastRace]) -> int:
    """叩き2戦目（2走前→前走が2ヶ月以上空き）"""
    if len(recent) < 2:
        return 0
    d_prev  = parse_date(recent[0].date)
    d_prev2 = parse_date(recent[1].date)
    if d_prev and d_prev2:
        gap = (d_prev - d_prev2).days
        if gap >= 60:
            return 1
    return 0


def check_first_surface(recent: list[PastRace], race_surface: str, race_class: int = 4) -> int:
    """初ダート or 初の芝（クラス別ペナルティ）
    未勝利(0)  : 0（適距離未確定のため免除）
    1勝クラス(1): -3
    2勝クラス以上(2+): -5
    """
    if not recent:
        return 0
    if race_class <= 0:
        return 0
    past_surfaces = {p.surface for p in recent if p.surface}
    if race_surface and race_surface not in past_surfaces:
        if race_class == 1:
            return -3
        else:
            return -5
    return 0


def check_distance_up(recent: list[PastRace], race_distance: str, race_class: int = 4) -> int:
    """距離延長1ハロン(200m)以上（クラス別ペナルティ）
    2勝クラス以下: 免除（適距離が定まっていない段階のため）
    3勝クラス(3): 前走1着→-1 / 前走3着以内近差→-2 / その他→-3
    OP以上(4+):   前走1着→-2 / 前走3着以内近差→-3 / その他→-5
    ※前走G1勝ちは全クラス免除
    """
    if not recent or not race_distance:
        return 0
    if race_class <= 2:
        return 0
    prev = recent[0]
    if not prev.distance:
        return 0
    curr_m = int(race_distance.replace("m", ""))
    prev_m = int(prev.distance.replace("m", ""))
    if curr_m - prev_m < 200:
        return 0
    # 前走G1勝ちは免除
    if prev.race_class >= 7 and prev.position == 1:
        return 0

    # クラス別ペナルティ係数（3勝クラス以上のみ到達）
    if race_class == 3:    # 3勝クラス
        p_win, p_close, p_base = -1, -2, -3
    else:                  # OP以上(4+)
        p_win, p_close, p_base = -2, -3, -5

    # OP以上のみ重賞実績で緩和
    if race_class >= 4:
        for p in recent[:3]:
            if p.race_class >= 7 and p.margin <= 1.0:
                return -2
            if p.race_class == 6 and (p.position == 1 or p.margin <= 0.5):
                return -2
            if p.race_class == 5 and (p.position == 1 or p.margin <= 0.3):
                return -3

    if prev.position == 1:
        return p_win
    if prev.position <= 3 and prev.margin <= 0.2:
        return p_close
    return p_base


def check_promotion(recent: list[PastRace], race_class: int) -> int:
    """昇級初戦ペナルティ廃止。
    昇級はポジティブな事象（前走1着の証明）。
    距離延長ペナルティは check_distance_up で別途評価。
    """
    return 0


def check_special_condition(recent: list[PastRace]) -> int:
    """前走が特殊条件（障害のみ）※海外遠征ペナルティは撤廃"""
    if not recent:
        return 0
    p = recent[0]
    if any(kw in p.race_name for kw in SPECIAL_KEYWORDS):
        return -4
    return 0


def check_local_prev(recent: list[PastRace], race_distance: str = "", race_surface: str = "",
                     race_class: int = 4) -> int:
    """前走がローカル競馬場（クラス別ペナルティ）
    2着以内 → 0（好走免除）
    3着以下 かつ 同距離・同馬場で過去3着以内実績あり → 0（免除）
    3着以下 かつ 実績なし:
      未勝利(0)  : 0
      1勝クラス(1): -1
      2勝・3勝(2-3): -2
      OP以上(4+) : -3
    """
    if not recent:
        return 0
    p = recent[0]
    if p.venue not in LOCAL:
        return 0
    if p.position <= 2:
        return 0
    if race_distance and race_surface:
        for past in recent[:5]:
            if (past.distance == race_distance and
                    past.surface == race_surface and
                    1 <= past.position <= 3):
                return 0
    if race_class <= 0:
        return 0
    elif race_class == 1:
        return -1
    elif race_class <= 3:
        return -2
    else:
        return -3


def check_long_rest(recent: list[PastRace], race_date_str: str) -> int:
    """6ヶ月以上の休み明け（前走→今回が180日以上）"""
    if not recent:
        return 0
    today = parse_date(race_date_str)
    prev_date = parse_date(recent[0].date)
    if today and prev_date:
        gap = (today - prev_date).days
        if gap >= 180:
            return -3
    return 0


def check_post_surface(frame_num: str, race_surface: str, race_distance: str = "") -> float:
    """枠番補正（2025年 東京・阪神・京都 実データ基準、全芝距離対応）

    芝1200m: 2・3枠+0.5 / 4枠-0.5
    芝1400m: 5・6枠+0.5 / 2・7枠-0.5
    芝1600m: 4枠+0.5 / 1枠-0.5
    芝1800m: 4・5・6枠+0.5 / 2・7・8枠-0.5
    芝2000m: 1枠+1.0 / 4枠+0.5 / 2・3枠-0.5
    芝2200m: 1枠+1.0 / 2枠-0.5（21レース・参考値）
    芝2400m: 1・2枠+0.5 / 5枠-0.5
    芝2500m以上: 0（データ不足）
    ダート内枠（1・2枠）1600m以下: -2.0（砂被り不利）
    ダート内枠（1・2枠）1800m以上: 0
    """
    try:
        fn = int(frame_num)
    except (ValueError, TypeError):
        return 0.0

    try:
        dist_m = int(race_distance.replace("m", ""))
    except (ValueError, AttributeError):
        dist_m = 0

    if race_surface == "芝":
        if dist_m == 1200:
            if fn in (2, 3): return  0.5
            if fn == 4:      return -0.5
        elif dist_m == 1400:
            if fn in (5, 6): return  0.5
            if fn in (2, 7): return -0.5
        elif dist_m == 1600:
            if fn == 4:      return  0.5
            if fn == 1:      return -0.5
        elif dist_m == 1800:
            if fn in (4, 5, 6): return  0.5
            if fn in (2, 7, 8): return -0.5
        elif dist_m == 2000:
            if fn == 1:      return  1.0
            if fn == 4:      return  0.5
            if fn in (2, 3): return -0.5
        elif dist_m == 2200:
            if fn == 1:      return  1.0
            if fn == 2:      return -0.5
        elif dist_m == 2400:
            if fn in (1, 2): return  0.5
            if fn == 5:      return -0.5
        return 0.0

    if race_surface == "ダ" and fn <= 2:
        if dist_m >= 1800:
            return 0.0
        return -2.0

    return 0.0


# 種牡馬距離適性テーブル（1=Sprint/2=Mile/3=Middle/4=Long/5=Stayer）
SIRE_TABLE: dict[str, int] = {
    # ── Sprint (~1200m) ──
    "ロードカナロア": 1, "ビッグアーサー": 1, "キンシャサノキセキ": 1,
    "サクラバクシンオー": 1, "タワーオブロンドン": 1, "ミスターメロディ": 1,
    "ドレフォン": 1, "アインシュタイン": 1, "ナムラクレア": 1,
    # ── Mile (~1600m) ──
    "ダイワメジャー": 2, "モーリス": 2, "インディチャンプ": 2,
    "アドマイヤマーズ": 2, "イスラボニータ": 2, "ミッキーアイル": 2,
    "グランアレグリア": 2, "サングレーザー": 2, "ペルシアンナイト": 2,
    "アルアイン": 2, "フランケル": 2, "タイキシャトル": 2,
    "クロフネ": 2, "ジョーカプチーノ": 2, "サリオス": 2,
    "モズアスコット": 2, "スワーヴリチャード": 2, "リアルスティール": 2,
    "ダノンキングリー": 2, "シュネルマイスター": 2,
    # ── Middle (~2000m) ──
    "ディープインパクト": 3, "キングカメハメハ": 3, "エピファネイア": 3,
    "ドゥラメンテ": 3, "リオンディーズ": 3, "コントレイル": 3,
    "ジャスタウェイ": 3, "ルーラーシップ": 3, "ヴィクトワールピサ": 3,
    "ブラックタイド": 3, "キズナ": 3, "レイデオロ": 3,
    "マカヒキ": 3, "ワグネリアン": 3, "サトノアラジン": 3,
    "エフフォーリア": 3, "ダノンベルーガ": 3, "イクイノックス": 3,
    "パンサラッサ": 3, "ジャックドール": 3, "ソールオリエンス": 3,
    "タスティエーラ": 3, "ドウデュース": 3, "ベラジオオペラ": 3,
    "ロジャーバローズ": 3, "ゴールドアクター": 3,
    # ── Long (~2400m) ──
    "ハービンジャー": 4, "ステイゴールド": 4, "ゴールドシップ": 4,
    "オルフェーヴル": 4, "キタサンブラック": 4, "サトノダイヤモンド": 4,
    "ワールドプレミア": 4, "ディープボンド": 4, "タイトルホルダー": 4,
    "シュヴァルグラン": 4, "アリストテレス": 4, "ハーツクライ": 4,
    "ブラストワンピース": 4, "クロノジェネシス": 4,
    # ── Stayer (~3000m+) ──
    "フェノーメノ": 5, "マリアライト": 5,
}

# レース距離 → カテゴリ変換
def _dist_cat(dist_m: int) -> int:
    if dist_m <= 1400: return 1
    if dist_m <= 1800: return 2
    if dist_m <= 2200: return 3
    if dist_m <= 2600: return 4
    return 5

# カテゴリ差 → スコア
_DIST_SCORE = {0: 1.5, 1: 0.5, 2: -0.5, 3: -1.0, 4: -1.5}

def check_bloodline_distance(sire: str, bms: str, race_distance: str) -> float:
    """父・母父の距離適性から -1.5〜+1.5 を返す（父60%・母父40%加重平均）"""
    if not race_distance:
        return 0.0
    try:
        dist_m = int(race_distance.replace("m", ""))
    except ValueError:
        return 0.0
    race_cat = _dist_cat(dist_m)
    scores = []
    for horse, weight in [(sire, 0.6), (bms, 0.4)]:
        cat = SIRE_TABLE.get(horse)
        if cat is not None:
            diff = abs(cat - race_cat)
            scores.append(_DIST_SCORE.get(diff, -1.5) * weight)
    if not scores:
        return 0.0
    # 0.5刻みに丸め（重み付き合計をそのまま使用）
    return round(sum(scores) * 2) / 2


def check_prev_run_bonus(recent: list[PastRace]) -> float:
    """前走好走ボーナス（G2未満の場合のみ）：1着→+2、2着→+1
    前走重賞近差（prev_high_grade_close）が付く馬には加算しない。
    """
    if not recent:
        return 0.0
    p = recent[0]
    if p.race_class >= 6:  # G2以上は prev_high_grade_close で評価済み
        return 0.0
    if p.position == 1:
        return 2.0
    if p.position == 2:
        return 1.0
    return 0.0


def check_prev2_high_grade(recent: list[PastRace]) -> float:
    """前々走G2以上での惜敗 or 勝利（前走の約半分のスコア）
    勝利/0.2差以内→+3、0.2-0.5差→+2
    """
    if len(recent) < 2:
        return 0.0
    p2 = recent[1]
    if p2.race_class < HIGH_GRADE_MIN:
        return 0.0
    if p2.position == 1 or (0 < p2.margin <= 0.2):
        return 3.0
    if 0.2 < p2.margin <= 0.5:
        return 2.0
    return 0.0


def check_prev2_run_bonus(recent: list[PastRace]) -> float:
    """前々走好走ボーナス（G2未満）：1着→+1、2着→+0.5
    前々走G2以上の場合は prev2_high_grade_close で評価済みのため加算しない。
    """
    if len(recent) < 2:
        return 0.0
    p2 = recent[1]
    if p2.race_class >= 6:
        return 0.0
    if p2.position == 1:
        return 1.0
    if p2.position == 2:
        return 0.5
    return 0.0


def check_grade_history(recent: list[PastRace]) -> float:
    """3・4走前のG1〜OP 1・2着にボーナス加点（前走・前々走は別評価のため除外）
    G1 1・2着→+3 / G2→+2 / G3→+1.5 / OP→+1
    """
    score = 0.0
    for p in recent[2:4]:
        if p.position > 2:
            continue
        if p.race_class >= 7:
            score = max(score, 3.0)
        elif p.race_class >= 6:
            score = max(score, 2.0)
        elif p.race_class >= 5:
            score = max(score, 1.5)
        elif p.race_class >= 4:
            score = max(score, 1.0)
    return score


def check_rising_trend(recent: list[PastRace]) -> float:
    """直近3走で着順が連続改善（例: 5→3→1着）の場合 +1"""
    if len(recent) < 3:
        return 0.0
    p1, p2, p3 = recent[0], recent[1], recent[2]
    if p1.position > 0 and p2.position > 0 and p3.position > 0:
        if p1.position < p2.position < p3.position:
            return 1.0
    return 0.0


def check_distance_drop(recent: list[PastRace], race_distance: str) -> float:
    """前走より200m以上の距離短縮の場合 +1"""
    if not recent or not race_distance:
        return 0.0
    prev = recent[0]
    if not prev.distance:
        return 0.0
    try:
        curr_m = int(race_distance.replace("m", ""))
        prev_m = int(prev.distance.replace("m", ""))
    except ValueError:
        return 0.0
    if prev_m - curr_m >= 200:
        return 1.0
    return 0.0


def check_place_consistency(recent: list) -> float:
    """直近5走の3着以内回数に応じてボーナス。
    4回以上 → +3、3回 → +2
    """
    if not recent:
        return 0.0
    top3 = sum(1 for p in recent[:5] if getattr(p, "position", 99) in (1, 2, 3))
    if top3 >= 4:
        return 3.0
    if top3 >= 3:
        return 2.0
    return 0.0


def check_light_weight(weight_str: str, all_weights: list[str], race_conditions: str = "") -> int:
    """軽量馬加点（ハンデ戦のみ適用・平均より1.5kg以上軽い場合のみ+1）
    定量戦・別定戦の牝馬2kg減等は規定斤量差でありハンデではないため対象外。
    トップハンデは能力の証明でもあるため減点しない。
    """
    if "ハンデ" not in race_conditions:
        return 0
    try:
        my_w = float(weight_str.replace("kg", ""))
    except (ValueError, AttributeError):
        return 0
    valid = []
    for w in all_weights:
        try:
            valid.append(float(w.replace("kg", "")))
        except (ValueError, AttributeError):
            pass
    if not valid:
        return 0
    avg_w = sum(valid) / len(valid)
    if avg_w - my_w >= 1.5:
        return 1
    return 0


def check_no_steep_win(recent: list[PastRace], race_venue: str, race_surface: str = "",
                       race_class: int = 4) -> int:
    """急坂コース（中山・阪神・中京）で好走歴なし（3着以内）
    2勝クラス以下は適距離・実績が固まりきっておらず急坂経験が少ないのが普通のため対象外。
    3勝クラス以上: 芝 -2 / ダート -1
    """
    if race_class <= 2:
        return 0
    if race_venue not in STEEP_COURSES:
        return 0
    for p in recent:
        if p.venue in STEEP_COURSES and 1 <= p.position <= 3:
            return 0
    return -1 if race_surface == "ダ" else -2


def check_weight_change(recent: list[PastRace], current_weight: int = 0,
                        manual_diff: int = 0) -> int:
    """馬体重±15kg以上変動
    manual_diff: CLIから直接変動量を指定（例: -28）。指定時は優先。
    current_weight>0: 今走 vs 前走で計算。
    どちらも未指定: 採点しない（0を返す）
    """
    if manual_diff != 0:
        return -2 if abs(manual_diff) >= 15 else 0
    if current_weight <= 0:
        return 0
    if not recent or recent[0].horse_weight <= 0:
        return 0
    if abs(current_weight - recent[0].horse_weight) >= 15:
        return -2
    return 0


def fetch_horse_ids(race_id: str) -> dict[str, str]:
    """netkeibaの出馬表ページから {馬名: horse_id} を取得"""
    import time as _time
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(r.content, "lxml")
    except Exception:
        return {}
    result = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "db.netkeiba.com/horse/" in href and "top" not in href and "bookmark" not in href:
            m = re.search(r"/horse/(\d+)", href)
            if m:
                name = a.get_text(strip=True)
                if name:
                    result[name] = m.group(1)
    return result


def fetch_past_track_conditions(horse_id: str) -> list[tuple[str, int]]:
    """db.netkeiba.com/horse/result/{id}/ から近走の (馬場状態, 着順) リストを取得"""
    import time as _time
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    try:
        _time.sleep(0.5)
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.content, "lxml")
    except Exception:
        return []
    table = soup.find("table")
    if not table:
        return []
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    try:
        cond_idx = headers.index("馬場")
        pos_idx  = headers.index("着順")
    except ValueError:
        return []
    result = []
    for row in rows[1:11]:  # 直近10走
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) <= max(cond_idx, pos_idx):
            continue
        cond = cells[cond_idx]
        try:
            pos = int(cells[pos_idx])
        except ValueError:
            continue
        if cond in ("良", "稍重", "重", "不良"):
            result.append((cond, pos))
    return result


def check_track_condition(past_conds: list[tuple[str, int]], current_condition: str) -> float:
    """
    道悪適性スコア（案C）
      稍重: 稍重以上3着以内→+0.5 / 稍重以上着外2回以上→-0.5
      重  : 重/不良3着以内→+2 / 稍重3着以内→+1 / 重/不良着外のみ→-1
      不良: 不良3着以内→+2 / 重/不良3着以内→+1 / 重/不良着外2回以上→-2 / 道悪実績なし→-1
      良  : 0（採点なし）
    """
    if not current_condition or current_condition == "良":
        return 0.0

    if current_condition == "稍重":
        wet_good = [p for c, p in past_conds if c in ("稍重", "重", "不良") and 1 <= p <= 3]
        wet_bad  = [p for c, p in past_conds if c in ("稍重", "重", "不良") and p > 3]
        if wet_good:
            return 0.5
        if len(wet_bad) >= 2:
            return -0.5
        return 0.0

    if current_condition == "重":
        heavy_good = [p for c, p in past_conds if c in ("重", "不良") and 1 <= p <= 3]
        heavy_bad  = [p for c, p in past_conds if c in ("重", "不良") and p > 3]
        wet_good   = [p for c, p in past_conds if c == "稍重" and 1 <= p <= 3]
        if heavy_good:
            return 2.0
        if wet_good and not heavy_bad:
            return 1.0
        if heavy_bad and not heavy_good:
            return -1.0
        return 0.0

    if current_condition == "不良":
        foul_good  = [p for c, p in past_conds if c == "不良" and 1 <= p <= 3]
        heavy_good = [p for c, p in past_conds if c in ("重", "不良") and 1 <= p <= 3]
        heavy_bad  = [p for c, p in past_conds if c in ("重", "不良") and p > 3]
        wet_any    = [p for c, p in past_conds if c in ("稍重", "重", "不良")]
        if foul_good:
            return 2.0
        if heavy_good:
            return 1.0
        if len(heavy_bad) >= 2:
            return -2.0
        if not wet_any:
            return -1.0
        return 0.0

    return 0.0


def check_wrong_direction(recent: list[PastRace], race_venue: str) -> int:
    """廃止：近走5走以内しか参照できず4走以前の実績を見落とすため精度が低い"""
    return 0


def check_seasonal_sex(age_sex: str, race_date_str: str) -> int:
    """冬の牝馬 / 夏の牡馬・せん"""
    d = parse_date(race_date_str)
    if not d:
        return 0
    month = d.month
    if "牝" in age_sex and month in WINTER_MONTHS:
        return -1
    if ("牡" in age_sex or "せん" in age_sex) and month in SUMMER_MONTHS:
        return -1
    return 0


def detect_running_style(recent: list) -> str:
    """近走のコーナー通過順位（頭数比）から脚質を推定する。
    最終コーナー(4角)を優先し、なければ1角で代用。
    データなし → '不明'（手動確認フラグを表示）
    平均比率 ≤ 0.35 → '先行'（≒頭数の35%以内）
    平均比率 ≤ 0.60 → '好位'
    それ以上        → '差し'
    """
    ratios = []
    for p in recent:
        corner = p.last_corner if p.last_corner > 0 else p.first_corner
        if corner > 0 and p.field_size > 0:
            ratios.append(corner / p.field_size)
    if not ratios:
        return "不明"
    avg_ratio = sum(ratios) / len(ratios)
    if avg_ratio <= 0.35:
        return "先行"
    if avg_ratio <= 0.60:
        return "好位"
    return "差し"


def check_inner_post(frame_num: str, recent: list = None,
                     force_senko: bool = False) -> tuple[bool, float]:
    """内枠（1〜3枠）かつ先行タイプなら +3 を自動適用。
    戻り値: (手動確認フラグ, 自動ボーナス点)
    - force_senko=True     → (False, +3.0) if 内枠 else (False, 0.0)
    - 脚質データあり＆先行 → (False, +3.0)
    - 脚質データなし       → (True,   0.0)  ★先行確認を表示
    - 脚質データあり＆非先行 → (False,  0.0)
    """
    try:
        fn = int(frame_num)
    except (ValueError, TypeError):
        return False, 0.0
    if fn > 3:
        return False, 0.0
    if force_senko:
        return False, 3.0
    style = detect_running_style(recent or [])
    if style == "先行":
        return False, 3.0
    if style == "不明":
        return True, 0.0   # 手動確認が必要
    return False, 0.0


# -------------------------------------------------------------------
# 全馬採点
# -------------------------------------------------------------------
def score_all(entries: list, race_info, training_data: dict = None,
              track_condition: str = "", horse_ids: dict = None,
              weight_diffs: dict = None, senko_list: list = None) -> list[tuple]:
    """
    entries       : HorseEntry のリスト
    race_info     : RaceInfo
    training_data : {馬名: TrainingData} netkeiba から取得済みのデータ（省略可）
    """
    race_venue    = race_info.venue
    race_distance = race_info.distance
    race_surface  = race_info.surface
    race_class    = parse_race_class(race_info.conditions)
    race_date     = race_info.date
    training_data = training_data or {}
    horse_ids     = horse_ids or {}
    senko_set     = set(senko_list or [])

    # 道悪: 各馬の過去track conditionをキャッシュ
    track_cond_cache: dict[str, list[tuple[str, int]]] = {}
    if track_condition and track_condition != "良":
        print(f"  [馬場] {track_condition} — 各馬の道悪実績を取得中...")
        for entry in entries:
            hid = horse_ids.get(entry.horse_name, "")
            if hid:
                track_cond_cache[entry.horse_name] = fetch_past_track_conditions(hid)
            else:
                track_cond_cache[entry.horse_name] = []

    # 全馬の前走3F・斤量を先に収集
    all_last3f = []
    all_weights = [e.weight_carried for e in entries]

    for entry in entries:
        pasts = [parse_past_race(r) for r in (entry.recent_races or []) if r]
        pasts = [p for p in pasts if p]
        all_last3f.append(pasts[0].last_3f if pasts else 0.0)

    results = []
    for i, entry in enumerate(entries):
        recent = [parse_past_race(r) for r in (entry.recent_races or []) if r]
        recent = [p for p in recent if p]
        my_3f = all_last3f[i]

        # 調教スコア（手動入力 CSV 優先、なければ netkeiba A/B/C/D）
        td = training_data.get(entry.horse_name)
        t_score = td.score if td else 0

        # 昇級+距離延長の重複ペナルティ軽減：両方発動時に各1点緩和
        promo   = check_promotion(recent, race_class)
        dist_up = check_distance_up(recent, race_distance, race_class)
        if promo < 0 and dist_up < 0:
            promo   += 1  # -2 → -1
            dist_up += 1  # -2 → -1 / -3 → -2 / -5 → -4

        # 前走3F最速 かつ 距離延長 → ペナルティ半減（実力馬の距離適応力を評価）
        f3f = check_fastest_3f(my_3f, all_last3f, recent[0].position if recent else 0)
        if f3f >= 2 and dist_up < 0:
            dist_up = -(abs(dist_up) // 2)  # -5→-2, -3→-1, -2→-1

        d = ScoreBreakdown(
            prev_high_grade_close  = check_prev_high_grade(recent),
            prev2_high_grade_close = check_prev2_high_grade(recent),
            fastest_3f             = check_fastest_3f(my_3f, all_last3f, recent[0].position if recent else 0),
            same_course            = check_same_course(recent, race_venue, race_distance, race_surface),
            training_rank          = t_score,
            second_start           = check_second_start(recent),
            rising_trend           = 0.0,   # ダート: 逆効果のため無効
            distance_drop          = check_distance_drop(recent, race_distance),
            prev_run_bonus         = check_prev_run_bonus(recent),
            prev2_run_bonus        = check_prev2_run_bonus(recent),
            grade_history          = check_grade_history(recent),
            bloodline_distance     = check_bloodline_distance(entry.sire, entry.bms, race_distance),
            first_surface          = check_first_surface(recent, race_surface, race_class),
            distance_up            = dist_up,
            promotion              = promo,
            special_condition      = check_special_condition(recent),
            local_prev             = check_local_prev(recent, race_distance, race_surface, race_class),
            long_rest              = round(check_long_rest(recent, race_date) * 0.5),  # ダート: ペナルティ半減
            post_surface           = check_post_surface(entry.frame_number, race_surface, race_distance),
            light_weight           = 0.0,   # ダート: 逆効果のため無効
            place_consistency      = check_place_consistency(recent),
            no_steep_win           = check_no_steep_win(recent, race_venue, race_surface, race_class),
            weight_change          = check_weight_change(recent, getattr(entry, "horse_weight", 0),
                                       manual_diff=(weight_diffs or {}).get(entry.horse_name, 0)),
            wrong_direction        = check_wrong_direction(recent, race_venue),
            seasonal_sex           = check_seasonal_sex(entry.age_sex, race_date),
            track_condition        = check_track_condition(
                track_cond_cache.get(entry.horse_name, []), track_condition
            ),
            **dict(zip(
                ("manual_inner_post", "inner_post_senko"),
                check_inner_post(entry.frame_number, recent,
                                 force_senko=(entry.horse_name in senko_set))
            )),
        )
        results.append((entry, d))

    return results


# -------------------------------------------------------------------
# 出力
# -------------------------------------------------------------------
SCORE_LABELS = {
    "prev_high_grade_close":  "前走重賞近差",
    "prev2_high_grade_close": "前々走重賞近差",
    "fastest_3f":             "前走3F最速",
    "same_course":            "同コース実績",  # +4=同距離 / +2=近距離（表示はget_labelで分岐）
    "training_rank":          "調教A評価",
    "second_start":           "叩き2戦目",
    "rising_trend":           "近走上昇傾向",
    "distance_drop":          "距離短縮",
    "prev_run_bonus":         "前走好走",
    "prev2_run_bonus":        "前々走好走",
    "grade_history":          "グレード実績(3-4走前)",
    "bloodline_distance":     "血統距離適性",
    "first_surface":          "初馬場種別",
    "distance_up":            "距離延長",
    "promotion":              "昇級初戦",
    "special_condition":      "特殊条件",
    "local_prev":             "前走ローカル",
    "long_rest":              "長期休養明け",
    "post_surface":           "枠番補正",
    "inner_post_senko":       "内枠先行",
    "light_weight":           "軽量馬加点",
    "place_consistency":      "複勝安定ボーナス",
    "no_steep_win":           "急坂好走なし",
    "weight_change":          "馬体重変動",
    "wrong_direction":        "回り不適",
    "seasonal_sex":           "季節×性別",
    "track_condition":        "道悪適性",
}


def _get_label(key: str, value: float) -> str:
    """ラベル取得（same_courseはスコア値で同距離/近距離を区別）"""
    if key == "same_course":
        return "同コース近距離実績" if abs(value) == 2 else "同コース実績"
    return SCORE_LABELS.get(key, key)


def _dist_comment(entry, race_distance: str, race_surface: str, race_venue: str) -> str:
    """距離適性コメントを生成（同距離勝利 > 同距離経験 > 近距離経験 > 実績なし）"""
    pasts = [parse_past_race(r) for r in (entry.recent_races or []) if r]
    pasts = [p for p in pasts if p]

    same_win = [p for p in pasts if p.distance == race_distance and p.surface == race_surface and p.position == 1]
    if same_win:
        return f"{race_venue}{race_distance}勝利実績"

    same = [p for p in pasts if p.distance == race_distance and p.surface == race_surface]
    if same:
        best = min(p.position for p in same if p.position > 0)
        return f"{race_distance}最高{best}着"

    try:
        base = int(race_distance.replace("m", ""))
        close = [p for p in pasts if p.surface == race_surface and abs(int(p.distance.replace("m", "")) - base) <= 200]
        if close:
            best = min(p.position for p in close if p.position > 0)
            return f"近距離{race_surface}最高{best}着"
    except (ValueError, AttributeError):
        pass

    return f"{race_distance}実績なし"


def _record_comment(entry) -> str:
    """前走・重賞実績コメントを生成"""
    pasts = [parse_past_race(r) for r in (entry.recent_races or []) if r]
    pasts = [p for p in pasts if p]

    g1_wins   = [p for p in pasts if p.race_class >= 7 and p.position == 1]
    g1_placed = [p for p in pasts if p.race_class >= 7 and 1 <= p.position <= 3]
    g2_wins   = [p for p in pasts if p.race_class == 6 and p.position == 1]

    if g1_wins:
        return f"G1勝ち馬({g1_wins[0].race_name})"
    if g1_placed:
        return f"G1{g1_placed[0].position}着({g1_placed[0].race_name})"
    if g2_wins:
        return f"G2勝ち馬({g2_wins[0].race_name})"

    if pasts:
        p = pasts[0]
        grade = {7: "G1", 6: "G2", 5: "G3"}.get(p.race_class, "")
        head = f"{p.field_size}頭" if p.field_size > 0 else ""
        return f"前走{grade}{p.race_name}{p.position}着/{head}"

    return "実績不明"


def save_csv(results: list[tuple], race_info, odds_map: dict = None, training_data: dict = None, sign_tag: str = None, eval_comment: list = None):
    import csv as _csv, re
    from pathlib import Path
    date_str = race_info.date.replace("年", "").replace("月", "").replace("日", "")
    venue = getattr(race_info, "venue", "") or ""
    race_num = getattr(race_info, "race_num", 0)
    rnum = f"{race_num}R" if race_num else ""
    race_name = race_info.name.replace(" ", "_")
    surface_raw = getattr(race_info, "surface", "") or ""
    distance_raw = getattr(race_info, "distance", "") or ""
    surface_full = {"芝": "芝", "ダ": "ダート", "障": "障害"}.get(surface_raw, surface_raw)
    surface_label = f"{surface_full}{distance_raw}" if surface_full else ""
    parts = [p for p in [date_str, venue, rnum, surface_label, race_name] if p]
    if sign_tag:
        parts.append(sign_tag)
    filename = f"score_{'_'.join(parts)}.csv"
    dm = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', race_info.date)
    date_dir = f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else "不明"
    save_dir = Path(__file__).parent / "results" / date_dir / (venue or "不明")
    save_dir.mkdir(parents=True, exist_ok=True)
    # 同レースの旧バージョン（芝/ダート追加前・サインタグ違い）を削除
    base_new = "score_" + "_".join([p for p in [date_str, venue, rnum, surface_label, race_name] if p])
    base_old = "score_" + "_".join([p for p in [date_str, venue, rnum, race_name] if p])
    for old_f in list(save_dir.glob(f"{base_new}*.csv")) + list(save_dir.glob(f"{base_old}*.csv")):
        if old_f.name != filename:
            old_f.unlink()
    filepath = save_dir / filename
    sorted_results = sorted(results, key=lambda x: x[1].total, reverse=True)
    training_data = training_data or {}

    popularity = {}
    if odds_map:
        sorted_by_odds = sorted(odds_map.items(), key=lambda x: x[1])
        popularity = {name: rank + 1 for rank, (name, _) in enumerate(sorted_by_odds)}

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.writer(f)
        if odds_map:
            writer.writerow(["順位", "枠", "馬番", "馬名", "合計スコア",
                             "単勝オッズ", "人気", "加点内訳", "減点内訳", "調教コメント"])
        else:
            writer.writerow(["順位", "枠", "馬番", "馬名", "合計スコア",
                             "加点内訳", "減点内訳", "調教コメント"])
        for rank, (entry, d) in enumerate(sorted_results, 1):
            plus_items  = [f"+{getattr(d,k):.1f}{_get_label(k,getattr(d,k))}" for k in SCORE_LABELS if getattr(d,k) > 0]
            minus_items = [f"{getattr(d,k):.1f}{_get_label(k,getattr(d,k))}" for k in SCORE_LABELS if getattr(d,k) < 0]
            td_obj = training_data.get(entry.horse_name)
            comment = td_obj.comment if td_obj else ""
            if odds_map:
                odds_val = odds_map.get(entry.horse_name, "")
                pop_val  = f"{popularity.get(entry.horse_name, '')}人気" if entry.horse_name in popularity else ""
                writer.writerow([rank, entry.frame_number, entry.horse_number,
                                 entry.horse_name, f"{d.total:+.1f}",
                                 odds_val, pop_val,
                                 " / ".join(plus_items), " / ".join(minus_items), comment])
            else:
                writer.writerow([rank, entry.frame_number, entry.horse_number,
                                 entry.horse_name, f"{d.total:+.1f}",
                                 " / ".join(plus_items), " / ".join(minus_items), comment])

        # レース情報行（芝/ダート/障害・距離）
        if surface_label:
            writer.writerow([])
            writer.writerow(["■レース情報", surface_label])

        # 買いサイン・買い目セクション
        if len(sorted_results) >= 2:
            top_entry, top_d = sorted_results[0]
            sec_entry, sec_d = sorted_results[1]
            gap   = top_d.total - sec_d.total
            odds1 = (odds_map or {}).get(top_entry.horse_name, 0)
            n     = len(sorted_results)
            has_sc = top_d.same_course >= 4

            skips = []
            if n == 18:
                skips.append("18頭フルゲート")
            if 3 <= gap < 5:
                skips.append(f"乖離{gap:.1f}pt（3〜5pt）")
            if has_sc:
                skips.append("同コース実績主因")
            if odds1 and 8 <= odds1 < 15:
                skips.append(f"軸{odds1:.1f}倍（8〜14倍）")

            if skips:
                sign = "見送り"
                sign_detail = " / ".join(skips)
            else:
                is_7pt = (gap >= 5 and n <= 13 and 2 <= odds1 < 8) if odds1 else (gap >= 5 and n <= 13)
                if is_7pt:
                    sign = "7pt推奨"
                    sign_detail = f"乖離{gap:.1f}pt + {n}頭" + (f" + 軸{odds1:.1f}倍" if odds1 else "")
                else:
                    notes = []
                    if gap < 1:
                        notes.append(f"乖離{gap:.1f}pt横並び→ROI222%")
                    if 14 <= n <= 17:
                        notes.append(f"{n}頭立て→ROI164%")
                    if odds1 and odds1 >= 15:
                        notes.append(f"穴軸{odds1:.1f}倍→ROI393%")
                    if odds1 and odds1 < 2:
                        notes.append(f"断然{odds1:.1f}倍→命中75%")
                    sign = "フォームB推奨" if notes else "フォームB（標準）"
                    sign_detail = " / ".join(notes) if notes else f"乖離{gap:.1f}pt {n}頭"

            nums = [e.horse_number for e, _ in sorted_results]

            def _sort_key(x):
                return int(x) if str(x).isdigit() else 99

            # 頭数に応じてフォームB相手範囲を調整
            if n <= 10:
                a_end, b_end = 4, 7   # A:2〜3位(3頭) B:2〜6位(6頭) → ~12点
            elif n <= 13:
                a_end, b_end = 5, 8   # A:2〜4位(4頭) B:2〜7位(7頭) → ~18点
            else:
                a_end, b_end = 5, 9   # A:2〜4位(4頭) B:2〜8位(8頭) → ~22点

            h1 = nums[0]
            formb = set()
            for a in nums[1:a_end]:
                for b in nums[1:b_end]:
                    if a != b:
                        formb.add(tuple(sorted([h1, a, b], key=_sort_key)))
            formb_list = sorted(formb, key=lambda c: tuple(_sort_key(x) for x in c))

            ax0, ax1 = nums[0], nums[1]
            form7 = set()
            for b in nums[2:9]:
                if b not in (ax0, ax1):
                    form7.add(tuple(sorted([ax0, ax1, b], key=_sort_key)))
            form7_list = sorted(form7, key=lambda c: tuple(_sort_key(x) for x in c))

            a_label = f"2〜{a_end - 1}位"
            b_label = f"2〜{b_end - 1}位"

            writer.writerow([])
            writer.writerow(["■買いサイン", sign, sign_detail])
            if eval_comment:
                writer.writerow([])
                writer.writerow(["■評価コメント"])
                for line in eval_comment:
                    writer.writerow(["", line])
            writer.writerow([])
            writer.writerow(["■三連複フォームB",
                             f"軸:{h1}番{top_entry.horse_name}",
                             f"相手A({a_label}):{','.join(nums[1:a_end])}",
                             f"相手B({b_label}):{','.join(nums[1:b_end])}",
                             f"{len(formb_list)}点"])
            for c in formb_list:
                writer.writerow(["", f"{c[0]}－{c[1]}－{c[2]}"])
            writer.writerow([])
            writer.writerow(["■三連複7点",
                             f"軸:{ax0}番{top_entry.horse_name}×{ax1}番{sec_entry.horse_name}",
                             f"相手(3〜9位):{','.join(nums[2:9])}",
                             f"{len(form7_list)}点"])
            for c in form7_list:
                writer.writerow(["", f"{c[0]}－{c[1]}－{c[2]}"])

    print(f"\n  [CSV出力] {filepath}")


def print_scores(results: list[tuple], race_info):
    race_dist    = race_info.distance
    race_surface = race_info.surface
    race_venue   = race_info.venue

    sorted_results = sorted(results, key=lambda x: x[1].total, reverse=True)

    header = f"  ★ 総合ランキング ★  {race_info.name}  {race_info.date}  {race_venue}  {race_dist}({race_surface})"
    print(f"\n{'='*110}")
    print(header)
    print(f"{'='*110}")
    print(f"{'順':>2}  {'枠':>2}{'馬番':>3}  {'馬名':<16}  {'合計':>6}  {'加点':<40}  {'減点':<32}  {'距離適性':<18}  実績")
    print("-" * 115)

    for rank, (entry, d) in enumerate(sorted_results, 1):
        plus_items  = [f"+{getattr(d, k):.1f}:{_get_label(k,getattr(d,k))}" for k in SCORE_LABELS if getattr(d, k) > 0]
        minus_items = [f"{getattr(d, k):.1f}:{_get_label(k,getattr(d,k))}" for k in SCORE_LABELS if getattr(d, k) < 0]
        plus_str  = " ".join(plus_items) or "—"
        minus_str = " ".join(minus_items) or "—"

        dist_c = _dist_comment(entry, race_dist, race_surface, race_venue)
        rec_c  = _record_comment(entry)
        manual = "  ★先行確認" if d.manual_inner_post else ""
        medal  = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, "  ")

        print(
            f"{rank:>2}{medal} {entry.frame_number:>2}{entry.horse_number:>3}  "
            f"{entry.horse_name:<16}  {d.total:>+6.1f}  {plus_str:<40}  {minus_str:<32}  "
            f"{dist_c:<18}  {rec_c}{manual}"
        )

    print()
    print("─ 手動確認が必要な項目（自動採点に含まれず）─")
    print("  +5: コースマイスタージョッキー（騎手のコース勝率50%以上）")
    print("  +3: 内枠（1〜3枠）の先行馬  ← ★先行確認 の馬を目視確認")
    print("  -5: 前走が逃げて好走 / -5: ダートで前走牝馬限定戦")


if __name__ == "__main__":
    import sys
    from netkeiba_scraper import TrainingData as TD

    args = sys.argv[1:]

    # --training-url オプション
    training_url = None
    if "--training-url" in args:
        idx = args.index("--training-url")
        if idx + 1 < len(args):
            training_url = args[idx + 1]

    # --race オプション（G1以外を指定する場合）
    race_keyword = None
    if "--race" in args:
        idx = args.index("--race")
        if idx + 1 < len(args):
            race_keyword = args[idx + 1]

    # --race-id オプション（race_idを直接指定）
    direct_race_id = None
    if "--race-id" in args:
        idx = args.index("--race-id")
        if idx + 1 < len(args):
            direct_race_id = args[idx + 1]

    # --jra-url オプション（JRA公式URLを直接指定）
    jra_url = None
    if "--jra-url" in args:
        idx = args.index("--jra-url")
        if idx + 1 < len(args):
            jra_url = args[idx + 1]

    # --track-condition オプション（良/稍重/重/不良）
    track_condition = ""
    if "--track-condition" in args:
        idx = args.index("--track-condition")
        if idx + 1 < len(args):
            track_condition = args[idx + 1]

    # --odds オプション（単勝オッズを馬番:倍率,... 形式で指定）
    odds_map = {}
    if "--odds" in args:
        idx = args.index("--odds")
        if idx + 1 < len(args):
            for item in args[idx + 1].split(","):
                if ":" in item:
                    num, val = item.split(":", 1)
                    try:
                        odds_map[num.strip()] = float(val.strip())
                    except ValueError:
                        pass

    senko_list = []
    if "--senko" in args:
        idx = args.index("--senko")
        if idx + 1 < len(args):
            senko_list = [n.strip() for n in args[idx + 1].split(",") if n.strip()]
            print(f"  [先行確認済み] {senko_list}")

    weight_diffs = {}
    if "--horse-weights" in args:
        idx = args.index("--horse-weights")
        if idx + 1 < len(args):
            for item in args[idx + 1].split(","):
                if ":" in item:
                    name, diff = item.rsplit(":", 1)
                    try:
                        weight_diffs[name.strip()] = int(diff.strip())
                    except ValueError:
                        pass

    # 出馬表の取得
    if jra_url:
        from jra_scraper import get_entry_list
        race_list = [("jra", jra_url)]
    elif direct_race_id:
        from netkeiba_race_scraper import get_entry_list_netkeiba
        race_list = [("netkeiba", direct_race_id)]
    elif race_keyword:
        from netkeiba_race_scraper import search_race, get_entry_list_netkeiba
        race_id = search_race(race_keyword)
        if not race_id:
            sys.exit(1)
        race_list = [("netkeiba", race_id)]
    else:
        from jra_scraper import get_thisweek_g1_urls, get_entry_list
        urls = get_thisweek_g1_urls()
        if not urls:
            print("今週のG1出馬表は見つかりませんでした。")
            sys.exit(0)
        race_list = [("jra", url) for url in urls]

    for source, key in race_list:
        if source == "netkeiba":
            race_info, entries = get_entry_list_netkeiba(key)
        else:
            race_info, entries = get_entry_list(key)

        def _load_kb_training(kb_url: str) -> dict:
            from keibabook_scraper import scrape as scrape_kb
            print(f"  [調教] {kb_url} からデータ取得中 (競馬ブック)...")
            kb_data = scrape_kb(kb_url)
            result = {
                r["馬名"]: TD(horse_name=r["馬名"], rank="KB",
                              comment=r.get("メモ", ""),
                              score=r["時計スコア(1-5)"] + r["状態スコア(1-5)"])
                for r in kb_data
            }
            for td_obj in result.values():
                t = td_obj.score
                td_obj.score = 3 if t >= 9 else 2 if t >= 7 else 1 if t >= 5 else 0 if t >= 3 else -1
            matched = sum(1 for e in entries if e.horse_name in result)
            print(f"  [調教] {matched}/{len(entries)}頭マッチ")
            return result

        if training_url and "keibabook" in training_url:
            training = _load_kb_training(training_url)
        elif training_url:
            from umasiru_scraper import scrape as scrape_umasiru
            print(f"  [調教] {training_url} からデータ取得中...")
            umasiru_data = scrape_umasiru(training_url)
            training = {
                name: TD(horse_name=name, rank=e.rank,
                         comment=f"1F{e.last1f} {e.kisei}", score=e.converted_score)
                for name, e in umasiru_data.items()
            }
            matched = sum(1 for e in entries if e.horse_name in training)
            print(f"  [調教] {matched}/{len(entries)}頭マッチ")
        else:
            # race_infoから競馬ブックIDを自動取得
            kb_url = None
            if race_info.race_num > 0 and race_info.venue and race_info.date:
                dm = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", race_info.date)
                if dm:
                    date_str = f"{dm.group(1)}{int(dm.group(2)):02d}{int(dm.group(3)):02d}"
                    from keibabook_scraper import find_kb_race_id
                    kb_id = find_kb_race_id(date_str, race_info.race_num, race_info.venue)
                    if kb_id:
                        kb_url = f"https://p.keibabook.co.jp/cyuou/cyokyo/0/0/{kb_id}"
            if kb_url:
                try:
                    training = _load_kb_training(kb_url)
                except SystemExit:
                    print("  [調教] 競馬ブックのクッキーが必要です。手動入力に切り替えます。")
                    from training_input import generate_template, load_training_input
                    generate_template(entries, race_info)
                    manual = load_training_input(race_info)
                    training = {
                        name: TD(horse_name=name, rank="手動", comment=ti.memo,
                                 score=ti.converted_score)
                        for name, ti in manual.items()
                    }
            else:
                from training_input import generate_template, load_training_input
                generate_template(entries, race_info)
                manual = load_training_input(race_info)
                training = {
                    name: TD(horse_name=name, rank="手動", comment=ti.memo,
                             score=ti.converted_score)
                    for name, ti in manual.items()
                }

        # 道悪適性: horse_idをnetkeibaから取得
        horse_ids = {}
        if track_condition and track_condition != "良":
            rid = direct_race_id or (race_id if (race_keyword or direct_race_id) else None)
            if rid:
                horse_ids = fetch_horse_ids(rid)
                print(f"  [馬場] horse_id取得: {len(horse_ids)}頭")

        results = score_all(entries, race_info, training_data=training,
                            track_condition=track_condition, horse_ids=horse_ids,
                            weight_diffs=weight_diffs, senko_list=senko_list)
        # odds_mapを馬番→馬名に変換
        horse_odds = {}
        if odds_map:
            num_to_name = {str(e.horse_number): e.horse_name for e in entries}
            horse_odds = {num_to_name[k]: v for k, v in odds_map.items() if k in num_to_name}
            print(f"  [オッズ] {len(horse_odds)}頭分を反映")
        print_scores(results, race_info)
        save_csv(results, race_info, odds_map=horse_odds if horse_odds else None)
