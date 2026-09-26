#!/bin/zsh
# 週末の自動実行（launchd: com.keiba.weekend から起動）
#   予想モード  : 予想を実行 → RACE_LOG.md に追記 → コミット＆push
#   結果モード  : レース結果を取得 → RACE_LOG.md の結果欄を埋める → コミット＆push
# 使い方: zsh tools/run_weekend_job.sh predict sun    /  zsh tools/run_weekend_job.sh results
MAIN="/Users/du/Documents/競馬予想システム"
PY="/usr/local/bin/python3"
MODE="${1:-predict}"
DAY="${2:-sun}"          # sat / sun（predictのとき使用）

mkdir -p "$MAIN/cache/logs"
LOG="$MAIN/cache/logs/weekend_job.log"
exec >>"$LOG" 2>&1
echo "\n===== $(date '+%Y-%m-%d %H:%M:%S') 開始 (mode=$MODE day=$DAY) ====="
cd "$MAIN" || { echo "cd 失敗"; exit 1; }

LOCK="$MAIN/cache/logs/weekend_job.lock"
if ! mkdir "$LOCK" 2>/dev/null; then echo "別のジョブが実行中のため終了"; exit 0; fi
trap 'rmdir "$LOCK"' EXIT

TODAY=$(date '+%Y-%m-%d')

if [[ "$MODE" == "predict" ]]; then
  if [[ "$DAY" == "sat" ]]; then "$PY" -u saturday_predict.py; else "$PY" -u sunday_predict.py; fi
  echo "----- $(date '+%H:%M:%S') 予想完了 → RACE_LOG.md に追記 -----"
  "$PY" -u tools/update_race_log.py --predict --date "$TODAY"
  MSG="$TODAY 予想（自動実行）"
else
  echo "----- $(date '+%H:%M:%S') 結果を取得 -----"
  "$PY" -u tools/update_race_log.py --results --date "$TODAY"
  MSG="$TODAY 結果を記録（自動実行）"
fi

# 予想CSVと記録をコミットして push（変更が無ければ何もしない）
git add "results/$TODAY" RACE_LOG.md 2>/dev/null
if git diff --cached --quiet; then
  echo "変更なし（コミットせず）"
else
  git commit -q -m "$MSG

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>" && echo "コミット: $(git log --oneline -1)"
  git push origin main && echo "push 完了" || echo "⚠ push 失敗"
fi
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 終了 ====="
