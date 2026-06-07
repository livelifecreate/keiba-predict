---
name: feedback-prediction-flow
description: 予想システムの出力フロー：分析前に予想結果を先に出す
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b23056f6-f310-486b-91d3-6429bb0d2ff5
---

予想結果は必ず先に出してから、比較・分析・改善を行う。

**Why:** バックテストや検証の際、スコア改善の試行錯誤で結果が後回しになりがちだが、ユーザーは先に予想ランキングを見てから議論したい。

**How to apply:** scorer.py や backtest.py 実行後、まず全頭の予想順位・スコアを出力してから「問題点の分析」「採点改善」を行う。採点ロジックの修正は予想を確認した後に提案する。
