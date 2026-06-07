---
name: feedback_training_data_source
description: 調教データのソースと入力フロー。PDFを渡してもらえば自動でCSV入力まで行う。
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b23056f6-f310-486b-91d3-6429bb0d2ff5
---

調教データは競馬新聞のPDF（主にトラックマン）から取得する。買えない場合は別紙になることもある。

**フロー:**
PDF添付 → タイム＋コメント読み取り → 時計スコア(1-5)・状態スコア(1-5)を評価 → CSV自動入力 → scorer.py実行

**Why:** 毎回手動入力の手間を省くため。PDFさえあれば調教評価まで自動化できる。

**How to apply:**
- PDFが添付されたら自分でタイムとコメントを読み取り、CSVに記入してからscorer.pyを実行する
- 新聞フォーマットが違っても（トラックマン/競馬ブック/スポーツ紙）、タイム列とコメント列を探して対応する
- 読み取り困難な箇所があればユーザーに確認する

**Related:** [[feedback_training_data_check]]
