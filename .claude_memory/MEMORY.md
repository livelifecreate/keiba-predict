# Memory Index

- [User Language Preference](feedback_language.md) — 常に日本語で返答する
- [競馬予想システム 採点ロジック](project_keiba_logic.md) — 「予想して」と言われたら参照。4軸採点（同コース+4/最速3F+4/昇級-4/ローカル-4）
- [承認ポリシー](feedback_approval_policy.md) — データ取得・分析は承認省略。rm/sudo/git push等は要確認
- [予想出力フロー](feedback_prediction_flow.md) — 予想結果を先に出してから分析・改善を行う
- [調教データ確認](feedback_training_data_check.md) — 予想・バックテスト時に調教URLが未提供なら「追加しますか？」と確認
- [調教データソース](feedback_training_data_source.md) — PDFを渡してもらえばタイム読み取り→CSV入力まで自動化。主にトラックマン、他紙も対応
- [コーディングスタイル](feedback_coding_style.md) — Pythonは.pyファイル保存→python3実行。requests/BS4/pandas/CSVは確認不要。rm/sudo/git pushは確認必須
- [ランキング出力フォーマット](feedback_ranking_output_format.md) — 予想後は全頭・人気順・オッズ込みの表を必ず出す
- [JRA URL方針](feedback_jra_url.md) — 出走表取得はPC版URL（pw01dde01）のみ。スマホ版URL（sw01dde10等）は予想に使わない
