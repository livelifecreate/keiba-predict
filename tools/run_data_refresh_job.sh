#!/bin/zsh
# データ取り込み＋着差の取得・検証の夜間ジョブ（launchd: com.keiba.datarefresh から 2026-10-05 01:00 に1回起動）
#   1. レース結果 9/14〜10/4 を取り込み → 過去走 → 調教 → 払戻（CLAUDE.md 運用ルールの順）
#   2. 全出走馬の着差を取得（tools/fetch_race_margin.py）→ 着差入り能力指数の検証（analyze/ability_margin_test.py）
#   通信制限（連続失敗）を検知したら、調教・払戻・着差の取得は飛ばす（空ファイルの固定化を防ぐ）。
#   ログ: cache/logs/data_refresh_job.log
MAIN="/Users/du/Documents/競馬予想システム"
PY="/usr/local/bin/python3"
PLIST="$HOME/Library/LaunchAgents/com.keiba.datarefresh.plist"
mkdir -p "$MAIN/cache/logs"
LOG="$MAIN/cache/logs/data_refresh_job.log"
exec >>"$LOG" 2>&1
echo "\n===== $(date '+%Y-%m-%d %H:%M:%S') 開始 ====="
cd "$MAIN" || { echo "cd 失敗"; exit 1; }

LOCK="$MAIN/cache/logs/weekend_job.lock"           # 週末ジョブ・馬場傾向と同時に動かさない
if ! mkdir "$LOCK" 2>/dev/null; then echo "別のジョブが実行中のため終了"; exit 0; fi
trap 'rmdir "$LOCK"' EXIT

MARK="$MAIN/cache/logs/data_refresh_job.start"; touch "$MARK"   # このジョブ中に作られたファイルの目印
probe() {   # netkeibaが応答するか（HTTP 200かつ本文あり）
  local code size
  code=$(curl -s -o /tmp/keiba_probe.html -w '%{http_code}' -A 'Mozilla/5.0' "https://race.netkeiba.com/race/result.html?race_id=202605040109")
  size=$(wc -c < /tmp/keiba_probe.html 2>/dev/null || echo 0)
  [[ "$code" == "200" && "$size" -gt 1000 ]]
}

echo "----- $(date '+%H:%M:%S') 1-1 レース結果の取り込み（9/14〜10/4） -----"
"$PY" -u fetch_period.py --start 2026-09-14 --end 2026-10-04
echo "----- $(date '+%H:%M:%S') 1-2 過去走スナップショット -----"
"$PY" -u fetch_missing_history.py --run --max-fail 5
if probe; then
  echo "----- $(date '+%H:%M:%S') 1-3 調教 -----"
  "$PY" -u fetch_training_cache.py
  echo "----- $(date '+%H:%M:%S') 1-4 払戻 -----"
  "$PY" -u fetch_payout_cache.py
else
  echo "⚠ netkeibaが応答しないため調教・払戻の取得を飛ばしました（通信制限の可能性）"
fi
# 通信制限中に作られた空ファイル（{}）は「取得済み」と誤認されるので、このジョブ中に作られたものを消す
/usr/bin/find cache/netkeiba_training cache/payouts -type f -size -3c -newer "$MARK" -print -delete 2>/dev/null | sed 's/^/  空ファイルを削除: /'

if probe; then
  echo "----- $(date '+%H:%M:%S') 2-1 着差の取得 -----"
  for i in 1 2 3 4 5 6; do
    out=$("$PY" -u tools/fetch_race_margin.py --run --limit 1500 | tee /dev/stderr)
    echo "$out" | grep -q "中断" && { echo "⚠ 着差の取得を中断（通信制限の可能性）"; break; }
    echo "$out" | grep -q "残り 0R" && break
  done
  echo "----- $(date '+%H:%M:%S') 2-2 着差入り能力指数の検証 -----"
  "$PY" -u analyze/ability_margin_test.py
else
  echo "⚠ netkeibaが応答しないため着差の取得と検証を飛ばしました"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 終了 ====="
# 1回きりの予約なので解除（翌年同日に再実行されないように）
launchctl unload "$PLIST" 2>/dev/null && echo "予約を解除しました"
