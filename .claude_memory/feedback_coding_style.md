---
name: feedback-coding-style
description: Bashコマンドの書き方とツール実行の安全警告削減ルール
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b23056f6-f310-486b-91d3-6429bb0d2ff5
---

長い Bash コマンド・python3 -c・ヒアドキュメントは使わない。

**Why:** Claude Codeの安全警告が頻発してユーザー体験が悪くなるため。

**How to apply:**
- Pythonコードは必ず .py ファイルとして保存し `python3 ファイル名.py` で実行する
- 競馬予想システム内（/Users/du/Documents/競馬予想システム/）での以下は通常作業として扱う（確認不要）:
  - requests / BeautifulSoup によるスクレイピング
  - pandas / CSV 入出力
  - .py ファイルの作成・編集・実行
- 以下は引き続き確認を求める:
  - rm（ファイル削除）
  - sudo
  - git push / git reset --hard
  - プロジェクト外のファイル変更
