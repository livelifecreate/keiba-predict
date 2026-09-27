#!/bin/zsh
# 当日の馬場傾向を更新して push（launchd: com.keiba.trackbias から土日の昼に30分おきに起動）
#   予想CSVが無い日（開催なし・予想未実行）は何もしない
MAIN="/Users/du/Documents/競馬予想システム"
PY="/usr/local/bin/python3"
mkdir -p "$MAIN/cache/logs"
exec >>"$MAIN/cache/logs/track_bias.log" 2>&1
cd "$MAIN" || exit 1
TODAY=$(date '+%Y-%m-%d')
ls results/"$TODAY"/*/*.csv >/dev/null 2>&1 || exit 0

LOCK="$MAIN/cache/logs/weekend_job.lock"        # 予想・結果ジョブと同時に git を触らない
mkdir "$LOCK" 2>/dev/null || { echo "$(date '+%H:%M') 別ジョブ実行中のため今回は見送り"; exit 0; }
trap 'rmdir "$LOCK"' EXIT

echo "===== $(date '+%Y-%m-%d %H:%M') ====="
"$PY" -u track_bias.py --date "$TODAY"
git add "results/$TODAY/track_bias.json"
if ! git diff --cached --quiet; then
  git commit -q -m "$TODAY 馬場傾向を更新（自動実行）

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push -q origin main && echo "push 完了" || echo "⚠ push 失敗"
fi
