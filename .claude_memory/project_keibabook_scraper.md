---
name: project_keibabook_scraper
description: 競馬ブックweb自動スクレイパーの完成状況と運用フロー
metadata: 
  node_type: memory
  type: project
  originSessionId: b23056f6-f310-486b-91d3-6429bb0d2ff5
---

競馬ブックwebの調教データ自動取得スクレイパーが完成・実用段階。

**Why:** PDFの手動読み取りより安価・自動化できるため。月額1,100円でサブスク済み（2026-06-06〜）。

**ファイル:**
- `keibabook_scraper.py`: メインスクレイパー
- `keibabook_cookie.txt`: ログインクッキー（期限切れ時はCopy as cURLで更新）

**運用フロー:**
1. 競馬ブックで調教ページを開いてURLコピー
2. `python3 keibabook_scraper.py <URL>` を実行
3. 自動でCSV保存 → scorer.pyが自動読み込み

**スコア計算:**
- 時計スコア: 最終追い切り1Fタイム（坂路/ウッドで基準分岐）
- 状態スコア: 矢印（↑↗→↘↓）+ 攻め解説キーワード分析

**実証結果（2026-06-06）:**
- 4レース全て上位6頭以内に1・2着が収まった
- 調教データなしより明確に精度向上

**How to apply:** 予想時は必ず調教URLを取得してから scorer.py を実行する。
