---
name: feedback-training-data-check
description: 予想・バックテスト実行時に調教データURLが未提供の場合は確認を求める
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b23056f6-f310-486b-91d3-6429bb0d2ff5
---

予想やバックテストを実行する際、調教データのURLが提供されていない場合は、実行前に「調教データを追加しますか？」と確認する。

**Why:** 調教データは予想精度に影響するため、ユーザーが貼り忘れた場合に自動で確認することで精度を保つ。

**How to apply:** backtest.py や scorer.py を実行する前に training_url が未指定であれば確認を求める。ユーザーが「なし」と言った場合は調教なしで進める。
