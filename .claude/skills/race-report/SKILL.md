# race-report

**「〇〇Rのレポートを出して」「〇〇競馬場〇〇Rについてレポートして」などと言われたら、このスキルに従ってHTMLレースレポートを生成する。**

---

## トリガー条件

- 「レポートを出して」「レポートして」「レースレポート」
- 「〇〇競馬場の〇〇Rを分析して」
- 個別レース名（例：「バーデンバーデンカップのレポート」）

---

## Step 1: レースデータ収集

### 1-1. 予想CSVを確認（スコア・加減点）

```bash
ls results/$(date +%Y-%m-%d)/{会場}/score_*_{R番号}R_*.csv
```

CSVが存在しない場合は weekend_predict.py を実行してから続行:
```bash
python3 weekend_predict.py --sat --venue {会場}   # または --sun
```

### 1-2. race_id の特定

netkeibaのレース一覧から race_id を取得:
```
https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={YYYYMMDD}
```

場コード（福島=03, 札幌=01, 函館=02, 新潟=04, 東京=05, 中山=06, 中京=07, 京都=08, 阪神=09, 小倉=10）

### 1-3. 調教データ取得

```python
import sys
sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
from netkeiba_scraper import fetch_training_data
training = fetch_training_data(race_id)
# training[horse_name] = {'rank': 'A'/'B'/'C'/'D', 'comment': '...'}
```

### 1-4. 脚質逆算（CSVのペース適性値から）

CSV列 `ペース適性` の値:
- `+1.5` → 好位差し
- `-1.0` → 先行
- `-2.0` → 逃げ
- `+2.5` or `+3.0` → 差し・追込

ペース予測:
- 逃げ+先行比率 ≥ 35% → ハイペース
- 逃げ+先行比率 ≤ 22% → スローペース
- それ以外 → 平均ペース

---

## Step 2: バックテスト収支を取得

CLAUDE.md の「バックテスト基準値」セクションから該当クラス×芝ダートの数値を参照。  
または `python3 verify/bet_metrics_standard.py` を実行して最新値を取得。

**3勝クラス×芝 n=48 の標準値:**
- 単勝: 的中率 20.8%, ROI 112.1%
- 馬連1-2: 的中率 8.3%, ROI 294.2%
- 三連複4頭BOX: ROI 466%
- 三連単A+B: ROI 241%, ヒット率 24%

---

## Step 3: HTMLレポートを生成

### 出力ファイルパス

```
results/{YYYY-MM-DD}/{会場}/report_{R番号}R_{レース名}.html
```

### デザイン仕様（必須）

**カラーパレット（芝レース）:**
```css
:root {
    --turf:    #1A3A20;   /* メイン背景 */
    --turf2:   #1F4326;   /* セカンダリ背景 */
    --turf3:   #254D2C;   /* カード背景 */
    --turf4:   #2A5831;   /* ホバー・アクセント */
    --gold:    #C9A227;   /* ゴールド（強調） */
    --gold2:   #E6C060;   /* ゴールドライト */
    --cream:   #F2EDE4;   /* テキスト */
    --muted:   #9ABE9E;   /* サブテキスト */
}
```

**カラーパレット（ダートレース）:**
```css
:root {
    --turf:    #2A1F0E;   /* ダート茶系背景 */
    --turf2:   #352610;
    --turf3:   #3D2C12;
    --turf4:   #473215;
    --gold:    #C9A227;
    --gold2:   #E6C060;
    --cream:   #F2EDE4;
    --muted:   #B8A88E;
}
```

**枠番カラー（必須）:**
```css
.waku-1 { background: #FFFFFF; color: #000; }  /* 白 */
.waku-2 { background: #000000; color: #FFF; }  /* 黒 */
.waku-3 { background: #CC0000; color: #FFF; }  /* 赤 */
.waku-4 { background: #0000CC; color: #FFF; }  /* 青 */
.waku-5 { background: #CCCC00; color: #000; }  /* 黄 */
.waku-6 { background: #00AA00; color: #FFF; }  /* 緑 */
.waku-7 { background: #FF8800; color: #FFF; }  /* 橙 */
.waku-8 { background: #FF69B4; color: #000; }  /* 桃 */
```

### セクション構成（この順序で必ず含める）

1. **HERO**: レース名・場・距離・クラス・賞金・推奨買い目（三連単A+B or 馬連等）
2. **INFO STRIP**: 天候・馬場状態・コース形態・ペース予測・スコア乖離・頭数
3. **バックテスト収支パネル**: 6〜8カラムのグリッド（ROI・的中率・n数）
4. **採点ランキング**: 全馬を採点順に表示（スコアバーアニメーション付き）
   - 枠番バッジ・馬番・馬名・スコア・人気・オッズを横並び
5. **調教データ表**: rank-A/B/C/Dバッジ + netkeibaコメント無加工
6. **レース展開予測**: 脚質バー可視化 + 展開シナリオ文 + 鍵を握る馬
7. **加減点ブレークダウン**: 全馬の主な加点・減点項目
8. **買い目フォーメーション**: 三連単A・三連単B・三連複各BOX

### アニメーション

```css
/* スコアバー */
@keyframes fillBar {
    from { width: 0% }
    to   { width: var(--pct) }
}
.score-bar { animation: fillBar 1.2s ease-out forwards; }

/* フェードイン */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(20px); }
    to   { opacity: 1; transform: translateY(0); }
}
```

---

## Step 4: ブラウザで開く

```bash
open results/{YYYY-MM-DD}/{会場}/report_{R番号}R_{レース名}.html
```

---

## 禁止事項

- 調教コメントを要約・改変しない（必ず無加工で掲載）
- バックテスト数値を省略しない（n数・的中率・ROI すべて記載）
- 調教データが取得できない場合は「調教データ未取得」と明記してスキップ（捏造禁止）
- 脚質が不明な馬は「不明」と表示（推測で埋めない）

---

## 参考: 生成済みレポート

- `results/2026-06-27/福島/report_11R_バーデンバーデンC.html` — 第2版（標準テンプレート）
