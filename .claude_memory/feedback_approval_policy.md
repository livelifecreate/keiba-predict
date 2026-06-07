---
name: feedback-approval-policy
description: 承認ポリシー：競馬システム開発での安全操作は承認省略、危険操作は必ず確認
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b23056f6-f310-486b-91d3-6429bb0d2ff5
---

承認不要（安全として扱う）操作:
- `python3 -c` によるデータ取得・解析
- requests, beautifulsoup4, pandas, numpy, json 処理
- テキストファイルの読み書き
- カレントプロジェクト（/Users/du/Documents/競馬予想システム/）内のファイル操作

**Why:** 競馬データ収集・分析スクリプトを頻繁に実行するため、通常のデータ取得処理で都度承認を求めない方針を優先。

必ず確認する操作:
- os.system(), subprocess, shell=True を含む処理
- rm, rmdir（削除系）
- sudo, chmod, chown（権限変更）
- git push, git reset --hard
- システムディレクトリへの書き込み
- プロジェクト外へのファイル変更

**How to apply:** スクリプト実行・ファイル編集・Webスクレイピングは黙って進める。上記の危険操作が必要になったときだけ確認を求める。
