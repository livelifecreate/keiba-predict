---
name: feedback-jra-url
description: JRAスクレイピングはPC版URL（pw01dde01）のみ使用。スマホ版URLは使わない
metadata: 
  node_type: memory
  type: feedback
  originSessionId: b23056f6-f310-486b-91d3-6429bb0d2ff5
---

JRAの出走表取得は必ずPC版URL（`pw01dde01`プレフィックス）を使う。スマホ版URL（`sw01dde10`/`sw01sde10`）は使用禁止。

**Why:** スマホ版HTMLは近走データの構造がPC版と異なり（1テキストに集約）、「同コース実績」「前走好走」「叩き2戦目」などの加点が全て計算できなくなる。また全馬に「-5.0初馬場種別」が誤付与されるなど予想スコアが大幅に変わってしまった実害があった。

**How to apply:**
- 出走表URL → `https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde01{venue}{year}{kai:02d}{nichi:02d}{race:02d}{YYYYMMDD}/{checksum}`
- 結果ページURL（`sw01sde10`）は着順・払戻金の取得のみに使う（スクレイピング対象として渡さない）
- スマホ版URLを渡されても予想には使わず、PC版URLを別途探す
