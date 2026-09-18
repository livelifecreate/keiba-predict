#!/bin/zsh
# 通算成績の取得 → スピード指数検証 の夜間ジョブ（launchd: com.keiba.speedindex から起動）
#   9/21 01:00 と 9/22 01:00 の2回に分けて取得（1回2500頭・通信制限の再発防止）。
#   ログ: cache/logs/speed_index_job.log
#   手動実行: zsh tools/run_speed_index_job.sh          自己診断のみ: zsh tools/run_speed_index_job.sh --selftest
MAIN="/Users/du/Documents/競馬予想システム"
WT="$MAIN/.claude/worktrees/new-info-sources"
PY="/usr/local/bin/python3"
PLIST="$HOME/Library/LaunchAgents/com.keiba.speedindex.plist"

# 作業ツリーが残っていればそちら（タイム列対応版）、無ければ main（マージ済み前提）
if [[ -f "$WT/analyze/speed_index.py" ]]; then DIR="$WT"; else DIR="$MAIN"; fi
mkdir -p "$MAIN/cache/logs"
LOG="$MAIN/cache/logs/speed_index_job.log"
exec >>"$LOG" 2>&1
echo "\n===== $(date '+%Y-%m-%d %H:%M:%S') 開始 (dir=$DIR args=$*) ====="
cd "$DIR" || { echo "cd 失敗"; exit 1; }

if [[ ! -f analyze/speed_index.py ]] || ! grep -q '"time"' fetch_missing_history.py; then
  echo "❌ スピード指数対応のコードが見つかりません（feature/new-info-sources を main にマージしてください）"; exit 1
fi

if [[ "$1" == "--selftest" ]]; then
  echo "race_result: $(ls cache/race_result | wc -l) 件 / horse_full_history: $(ls cache/horse_full_history 2>/dev/null | wc -l) 件"
  "$PY" -c "import requests, bs4, lxml, numpy, pandas; print('python modules OK')"
  echo "selftest 完了"; exit 0
fi

LOCK="$MAIN/cache/logs/speed_index_job.lock"
if ! mkdir "$LOCK" 2>/dev/null; then echo "別のジョブが実行中のため終了"; exit 0; fi
trap 'rmdir "$LOCK"' EXIT

"$PY" -u fetch_full_career.py --run --limit 2500
echo "----- $(date '+%H:%M:%S') 取得終了 → スピード指数検証 -----"
"$PY" -u analyze/speed_index.py
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 終了 ====="

# 2回目（9/22）以降の実行が済んだら予約を解除（毎年同日に再実行されないように）
if [[ "$(date '+%Y%m%d')" -ge 20260922 ]]; then
  rm -f "$PLIST"
  launchctl bootout "gui/$(id -u)/com.keiba.speedindex" 2>/dev/null
fi
