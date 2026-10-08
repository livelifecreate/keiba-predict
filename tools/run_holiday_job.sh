#!/bin/zsh
# 祝日（月曜など土日以外）開催の自動実行（launchd: com.keiba.holiday から起動・1日限り）
#   14時より前に起動 → 予想（run_weekend_job.sh predict auto → 土日以外なので当日の日付で予想）
#   14時以降に起動   → 結果の記録。終わったら予約を解除して plist を削除する
MAIN="/Users/du/Documents/競馬予想システム"
PLIST="$HOME/Library/LaunchAgents/com.keiba.holiday.plist"
if (( $(date +%H) < 14 )); then
  /bin/zsh "$MAIN/tools/run_weekend_job.sh" predict auto
else
  /bin/zsh "$MAIN/tools/run_weekend_job.sh" results
  echo "祝日ジョブの予約を解除します" >> "$MAIN/cache/logs/weekend_job.log"
  rm -f "$PLIST"
  launchctl remove com.keiba.holiday 2>/dev/null
fi
