# 採点システム 完全仕様書

## 概要

採点システムは、競馬レースの馬を**23個の独立した項目**で採点し、合計スコアを計算します。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `scorer_turf.py` | 芝コース採点ロジック（メイン） |
| `scorer_dart.py` | ダートコース採点ロジック |
| `jockey_form.py` | 騎手フォームボーナス |
| `training_form.py` | 調教スコア |

## 採点フロー

```
weekend_predict.py
  ↓
  各レースの出馬表を取得
  ↓
  for each 馬:
    ├─ scorer_turf.score_all() or scorer_dart.score_all()
    │  ├─ 23項目を個別計算
    │  ├─ jockey_form.get_jockey_form_bonus() を呼出
    │  ├─ training_form.get_training_score() を呼出
    │  └─ 合計スコアを集計
    │
    └─ スコア結果を CSV に出力
```

## 採点の23項目（実装順序）

### 基礎項目（過去走からの計算）

1. **同コース実績** (`same_course`)
   - 同じ競馬場・同じ距離・同じ馬場種別での過去の成績
   - 1着経験あり: +2
   - 経験あり: +1
   - 経験なし: 0

2. **前走重賞近差** (`prev_grade_margin`)
   - 前走がG1/G2/G3で0.2秒差以内の惜敗: +5
   - 前走がG1/G2/G3で0.2～0.5秒差の惜敗: +3

3. **前々走重賞近差** (`prev_prev_grade_margin`)
   - 2走前の重賞での近差: 同上

4. **前走3F最速** (`prev_last_3f`)
   - 前走の上がり3Fがメンバー最速: +4

5. **叩き2戦目** (`kick_2nd_start`)
   - 2走前から2ヶ月以上空いての2戦目: +1

6. **近走上昇傾向** (`recent_rise`)
   - 直近3走で着順が良くなっている傾向

7. **距離短縮** (`distance_down`)
   - 前走比で200m以上の短縮: 条件による加点

8. **前走好走** (`prev_good`)
   - 前走で好走した痕跡

9. **前々走好走** (`prev_prev_good`)
   - 2走前で好走した痕跡

### 条件・クラス関連

10. **グレード実績（3-4走前）** (`grade_history`)
    - 3～4走前のグレード成績

11. **血統距離適性** (`bloodline_distance`)
    - 血統から見た距離への適性

12. **初馬場種別** (`first_surface`)
    - 初めての芝またはダート走行: -2～-5

13. **距離延長** (`distance_up`)
    - 前走比で200m以上の延長: -2～-5

14. **昇級初戦** (`promotion`)
    - 前走1着でのクラスアップ: -4

15. **特殊条件** (`special_condition`)
    - 障害戦・海外競馬など: -4

16. **前走ローカル** (`local_prev`)
    - 前走がローカル競馬場: -4

17. **長期休養明け** (`long_rest`)
    - 6ヶ月以上の休み明け: -3

### 枠・斤量関連

18. **枠番補正** (`post_surface`)
    - コース・距離別の枠番有利不利: ±0.5～-2.0

19. **内枠先行** (`inner_post_senko`)
    - 内枠の先行馬: +3

20. **軽量馬加点** (`light_weight`)
    - ハンデ戦で平均より1.5kg以上軽い: +1

### ボーナス・特殊スコア

21. **複勝安定ボーナス** (`place_consistency`)
    - 直近5走で3着以内が4回以上: +3
    - 直近5走で3着以内が3回: +2

22. **勝利数ボーナス** (`win_count`)
    - 直近5走で2勝以上: +2.0
    - 直近5走で1勝: +1.0

23. **内容評価スコア** (`content_score`)
    - 過去走の着差・上がり・脚質・人気乖離を複合評価
    - 直近3走の加重平均で計算

### 追加スコア（別途実装）

- **騎手ボーナス（重賞）** (`jockey_bonus`)
  - 重賞で指定された7騎手のみ: ±0～+2

- **騎手フォーム** (`jockey_form`)
  - 騎手の通算複勝率ベースの加点: -2.0～+2.0
  - 3勝クラスでは常に+0

- **急坂パワー** (`steep_power`)
  - 中山・阪神・中京での好走歴なし: -2

- **馬体重変動** (`weight_change`)
  - 前走比±15kg以上の変動: -2

- **回り不適** (`wrong_direction`)
  - 右回り/左回りで好走歴なし: -1

- **季節×性別** (`seasonal_sex`)
  - 冬の牝馬・夏の牡馬・せん: -1

- **道悪適性** (`track_condition`)
  - 稍重/重/不良での実績に基づく加点・減点

- **ペース適性** (`pace_fit`)
  - 前走のペース設定への適応度

### 調教スコア（2026-07-12実装）

**training_form.py** から追加：

- **調教評価** (`training_rank`)
  - コメント文言の実績複勝率ベース
  - 35%以上: +3
  - 25～35%: +2
  - 15～25%: +1
  - 8～15%: 0
  - 8%未満: -1
  - 母数<30件: 従来のA/B/C/D評価にフォールバック

## スコア計算の流れ

```python
# scorer_turf.score_all() の内部フロー

total_score = 0

# 1. 基礎スコア（23項目）を個別計算
for item in [same_course, prev_grade_margin, ..., pace_fit]:
    score = calculate_item_score(item, entry, race_info)
    total_score += score

# 2. 調教スコアを追加（training_form.py）
training_score = training_form.get_training_score(
    horse_name=entry.horse_name,
    venue=race_info.venue,
    race_class=race_info.race_class,
    distance_m=race_info.distance_m,
    surface=race_info.surface
)
total_score += training_score

# 3. 騎手フォームボーナスを追加（jockey_form.py）
jockey_bonus = jockey_form.get_jockey_form_bonus(
    jockey=entry.jockey,
    race_class=race_info.race_class
)
total_score += jockey_bonus

# 4. 場所・季節別の補正（小倉夏などで実装予定）
if venue == '小倉' and date.month in [7, 8]:
    summer_adjust = KOKURA_SUMMER_JOCKEY.get(entry.jockey, 0)
    total_score += summer_adjust

return total_score
```

## 市場との情報格差（2026-07-18確認）

### 採点システムが持っている情報
- ✅ 過去走履歴（netkeiba）
- ✅ 調教情報（netkeiba・当日朝まで）
- ✅ 騎手実績（通算）
- ✅ 血統・距離適性
- ✅ 枠番

### 採点システムが持っていない情報
- ❌ 当日朝のパドック情報
- ❌ 当日朝の馬体重速報
- ❌ 当日朝のニュース
- ❌ 騎手の「月別・場所別成績」
- ❌ クラス・フィールドサイズによる「波乱度」統計

## 改善予定（優先度順）

### 優先度1: 騎手の月別・場所別成績
- **データ**: キャッシュから集計可能
- **実装先**: jockey_form.py の `get_jockey_form_bonus()` 拡張
- **期待効果**: +1.5pt（市場精度に接近）

### 優先度2: 当日朝の馬体重・ニュース
- **データ**: JRA公式から自動取得 + Yahoo競馬スクレイピング
- **実装先**: weekend_predict.py の「朝の再計算」機能
- **期待効果**: +1.5pt

### 優先度3: パドック情報の定量化
- **データ**: 目視判定（人間が動画を見て5段階評価）
- **実装先**: 当日朝の手動入力フロー
- **期待効果**: +1.5pt

### 優先度4: 波乱度統計
- **データ**: キャッシュから集計可能
- **実装先**: scorer_turf/dart.py に新規関数追加
- **期待効果**: +0.5pt

## 参考資料

- `CLAUDE.md` - 基準値・バックテスト結果
- `SUMMER_FIX_PLAN.md` - 夏競馬対策の詳細
- `market_dependency_analysis.txt` - 市場との情報格差分析
