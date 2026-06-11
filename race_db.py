"""
競馬予想システム SQLiteデータベース管理

テーブル:
  races       - レース情報
  predictions - 予想+採点結果+着順+オッズ（1行=1馬×1レース）
  payouts     - 払戻金（1行=1券種×1組み合わせ）

使い方:
  from race_db import RaceDB
  db = RaceDB()
  db.save_race(race_info)
  db.save_predictions(race_id, entries, scored, rank_map, odds_map)
  db.update_results(race_id, rank_map)
  db.update_odds_final(race_id, odds_map)
  db.save_payouts(race_id, payouts)
  db.export_csv(race_id, "result.csv")
  db.get_horse_history(horse_id)
"""

import sqlite3
import csv
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "data" / "keiba.db"

# ScoreBreakdown の全フィールド（manual_inner_post は除外）
SCORE_COLS = [
    "prev_high_grade_close",
    "prev2_high_grade_close",
    "fastest_3f",
    "same_course",
    "training_rank",
    "second_start",
    "rising_trend",
    "distance_drop",
    "prev_run_bonus",
    "prev2_run_bonus",
    "grade_history",
    "bloodline_distance",
    "first_surface",
    "distance_up",
    "promotion",
    "special_condition",
    "local_prev",
    "long_rest",
    "post_surface",
    "inner_post_senko",
    "light_weight",
    "no_steep_win",
    "weight_change",
    "wrong_direction",
    "seasonal_sex",
    "track_condition",
]

DDL = """
CREATE TABLE IF NOT EXISTS races (
    race_id    TEXT PRIMARY KEY,
    date       TEXT,
    venue      TEXT,
    race_name  TEXT,
    race_class TEXT,
    surface    TEXT,
    distance   TEXT,
    conditions TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id                 TEXT    NOT NULL REFERENCES races(race_id),
    horse_id                TEXT,
    horse_name              TEXT,
    horse_num               TEXT,
    frame                   TEXT,
    age_sex                 TEXT,
    weight_carried          TEXT,
    jockey                  TEXT,
    predicted_rank          INTEGER,
    total_score             REAL,
    -- ScoreBreakdown
    prev_high_grade_close   REAL DEFAULT 0,
    prev2_high_grade_close  REAL DEFAULT 0,
    fastest_3f              REAL DEFAULT 0,
    same_course             REAL DEFAULT 0,
    training_rank           REAL DEFAULT 0,
    second_start            REAL DEFAULT 0,
    rising_trend            REAL DEFAULT 0,
    distance_drop           REAL DEFAULT 0,
    prev_run_bonus          REAL DEFAULT 0,
    prev2_run_bonus         REAL DEFAULT 0,
    grade_history           REAL DEFAULT 0,
    bloodline_distance      REAL DEFAULT 0,
    first_surface           REAL DEFAULT 0,
    distance_up             REAL DEFAULT 0,
    promotion               REAL DEFAULT 0,
    special_condition       REAL DEFAULT 0,
    local_prev              REAL DEFAULT 0,
    long_rest               REAL DEFAULT 0,
    post_surface            REAL DEFAULT 0,
    inner_post_senko        REAL DEFAULT 0,
    light_weight            REAL DEFAULT 0,
    no_steep_win            REAL DEFAULT 0,
    weight_change           REAL DEFAULT 0,
    wrong_direction         REAL DEFAULT 0,
    seasonal_sex            REAL DEFAULT 0,
    track_condition         REAL DEFAULT 0,
    -- 結果（レース後に更新）
    actual_rank             INTEGER,
    scratch_status          INTEGER DEFAULT 0,  -- 0=出走 1=取消 2=除外
    -- オッズ
    odds_tansho_pre         REAL,   -- 単勝・直前
    odds_fukusho_pre        REAL,   -- 複勝・直前
    odds_tansho_final       REAL,   -- 単勝・確定
    odds_fukusho_final      REAL,   -- 複勝・確定
    created_at              TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_predictions_race    ON predictions(race_id);
CREATE INDEX IF NOT EXISTS idx_predictions_horse   ON predictions(horse_id);
CREATE INDEX IF NOT EXISTS idx_predictions_scratch ON predictions(scratch_status);

CREATE TABLE IF NOT EXISTS payouts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id     TEXT    NOT NULL REFERENCES races(race_id),
    bet_type    TEXT,   -- 単勝/複勝/馬連/馬単/ワイド/3連複/3連単
    combination TEXT,   -- "1" / "3-7" / "1-3-7"
    payout      INTEGER -- 円
);

CREATE INDEX IF NOT EXISTS idx_payouts_race ON payouts(race_id);
"""


class RaceDB:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._conn() as conn:
            conn.executescript(DDL)

    # ────────────────────────────────────────────────
    # 保存
    # ────────────────────────────────────────────────
    def save_race(self, race_info) -> None:
        """RaceInfo を races テーブルに保存（重複は無視）"""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO races
                   (race_id, date, venue, race_name, race_class, surface, distance, conditions)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    _race_id_from_url(race_info.url) or race_info.url,
                    race_info.date,
                    race_info.venue,
                    race_info.name,
                    "",           # race_class は外から渡す想定（verify_batch側で判定済み）
                    race_info.surface,
                    race_info.distance,
                    race_info.conditions,
                ),
            )

    def save_race_full(self, race_id: str, date: str, venue: str, race_name: str,
                       race_class: str, surface: str, distance: str, conditions: str) -> None:
        """races テーブルに保存（クラス指定あり版）"""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO races
                   (race_id, date, venue, race_name, race_class, surface, distance, conditions)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (race_id, date, venue, race_name, race_class, surface, distance, conditions),
            )

    def save_predictions(
        self,
        race_id: str,
        scored: list,          # score_all の戻り値 [(HorseEntry, ScoreBreakdown), ...]
        rank_map: dict,        # {horse_name: actual_rank}（未確定なら空dict）
        odds_map: dict = None, # {horse_num: odds_tansho}（直前オッズ）
        horse_id_map: dict = None,  # {horse_name: horse_id}
    ) -> None:
        """予想結果を predictions テーブルに保存"""
        odds_map     = odds_map or {}
        horse_id_map = horse_id_map or {}

        rows = []
        for rank, (entry, bd) in enumerate(scored, 1):
            score_vals = [getattr(bd, col, 0.0) for col in SCORE_COLS]
            actual_rank = rank_map.get(entry.horse_name)
            o_pre = odds_map.get(entry.horse_number) or odds_map.get(entry.horse_name)
            hid = horse_id_map.get(entry.horse_name, "")

            rows.append((
                race_id,
                hid,
                entry.horse_name,
                entry.horse_number,
                entry.frame_number,
                entry.age_sex,
                entry.weight_carried,
                entry.jockey,
                rank,
                bd.total,
                *score_vals,
                actual_rank,
                0,      # scratch_status
                o_pre,  # odds_tansho_pre
                None,   # odds_fukusho_pre
                None,   # odds_tansho_final
                None,   # odds_fukusho_final
            ))

        placeholders = ",".join(["?"] * (10 + len(SCORE_COLS) + 6))
        cols = (
            "race_id,horse_id,horse_name,horse_num,frame,age_sex,"
            "weight_carried,jockey,predicted_rank,total_score,"
            + ",".join(SCORE_COLS)
            + ",actual_rank,scratch_status,"
            "odds_tansho_pre,odds_fukusho_pre,odds_tansho_final,odds_fukusho_final"
        )
        with self._conn() as conn:
            conn.executemany(
                f"INSERT INTO predictions ({cols}) VALUES ({placeholders})", rows
            )

    def save_payouts(self, race_id: str, payouts: list[dict]) -> None:
        """
        payouts: [{"bet_type": "3連複", "combination": "1-3-7", "payout": 12340}, ...]
        """
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO payouts (race_id, bet_type, combination, payout) VALUES (?,?,?,?)",
                [(race_id, p["bet_type"], p["combination"], p["payout"]) for p in payouts],
            )

    # ────────────────────────────────────────────────
    # 更新
    # ────────────────────────────────────────────────
    def update_results(self, race_id: str, rank_map: dict) -> None:
        """レース後に着順を更新。rank_map = {horse_name: actual_rank}"""
        with self._conn() as conn:
            for name, rank in rank_map.items():
                conn.execute(
                    "UPDATE predictions SET actual_rank=? WHERE race_id=? AND horse_name=?",
                    (rank, race_id, name),
                )

    def update_odds_final(self, race_id: str, odds_map: dict) -> None:
        """確定単勝オッズを更新。odds_map = {horse_num: odds}"""
        with self._conn() as conn:
            for horse_num, odds in odds_map.items():
                conn.execute(
                    "UPDATE predictions SET odds_tansho_final=? WHERE race_id=? AND horse_num=?",
                    (odds, race_id, str(horse_num)),
                )

    def update_scratch(self, race_id: str, horse_num: str, status: int) -> None:
        """出走取消(1)・除外(2)を記録"""
        with self._conn() as conn:
            conn.execute(
                "UPDATE predictions SET scratch_status=? WHERE race_id=? AND horse_num=?",
                (status, race_id, str(horse_num)),
            )

    # ────────────────────────────────────────────────
    # 参照
    # ────────────────────────────────────────────────
    def get_horse_history(self, horse_id: str, limit: int = 20) -> list[sqlite3.Row]:
        """馬別の採点履歴を返す（直近limit件）"""
        with self._conn() as conn:
            return conn.execute(
                """SELECT r.date, r.venue, r.race_name, r.race_class,
                          r.surface, r.distance,
                          p.predicted_rank, p.actual_rank, p.total_score,
                          p.same_course, p.fastest_3f, p.training_rank,
                          p.prev_high_grade_close, p.prev_run_bonus,
                          p.inner_post_senko, p.post_surface,
                          p.odds_tansho_pre, p.odds_tansho_final
                   FROM predictions p JOIN races r USING(race_id)
                   WHERE p.horse_id = ? AND p.scratch_status = 0
                   ORDER BY r.date DESC
                   LIMIT ?""",
                (horse_id, limit),
            ).fetchall()

    def get_race_summary(self, race_id: str) -> list[sqlite3.Row]:
        """1レースの全馬スコアを予想順に返す"""
        with self._conn() as conn:
            return conn.execute(
                """SELECT p.predicted_rank, p.actual_rank, p.frame, p.horse_num,
                          p.horse_name, p.total_score, p.scratch_status,
                          p.odds_tansho_pre, p.odds_tansho_final,
                          """
                + ", ".join(f"p.{c}" for c in SCORE_COLS)
                + """ FROM predictions p
                   WHERE p.race_id = ?
                   ORDER BY p.predicted_rank""",
                (race_id,),
            ).fetchall()

    def get_payouts(self, race_id: str) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT bet_type, combination, payout FROM payouts WHERE race_id=? ORDER BY bet_type",
                (race_id,),
            ).fetchall()

    def accuracy_by_class(self, surface: str = "芝") -> list[tuple]:
        """クラス別的中率サマリーを返す"""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT r.race_class,
                          COUNT(DISTINCT r.race_id)                          AS races,
                          SUM(CASE WHEN p.predicted_rank=1 AND p.actual_rank=1 THEN 1 ELSE 0 END) AS tan,
                          SUM(CASE WHEN p.predicted_rank=1 AND p.actual_rank<=3 THEN 1 ELSE 0 END) AS fuku,
                          SUM(CASE WHEN EXISTS(
                              SELECT 1 FROM predictions p2
                              WHERE p2.race_id=p.race_id AND p2.predicted_rank<=2
                                AND p2.actual_rank=1
                          ) AND EXISTS(
                              SELECT 1 FROM predictions p3
                              WHERE p3.race_id=p.race_id AND p3.predicted_rank<=2
                                AND p3.actual_rank=2
                          ) THEN 1 ELSE 0 END) AS umaren_race
                   FROM predictions p JOIN races r USING(race_id)
                   WHERE r.surface=? AND p.predicted_rank=1 AND p.scratch_status=0
                   GROUP BY r.race_class
                   ORDER BY races DESC""",
                (surface,),
            ).fetchall()
            return rows

    # ────────────────────────────────────────────────
    # CSV出力
    # ────────────────────────────────────────────────
    def export_csv(self, race_id: str, path: str) -> None:
        """既存のverify_*.pyと同形式のCSVを出力"""
        rows = self.get_race_summary(race_id)
        payouts = self.get_payouts(race_id)
        if not rows:
            print(f"[DB] {race_id} のデータがありません")
            return

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = [
                "予想順位", "実際着順", "枠", "馬番", "馬名",
                "合計スコア", "scratch",
                "単勝オッズ(直前)", "単勝オッズ(確定)",
            ] + SCORE_COLS
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    "予想順位":       r["predicted_rank"],
                    "実際着順":       r["actual_rank"] or "",
                    "枠":            r["frame"],
                    "馬番":          r["horse_num"],
                    "馬名":          r["horse_name"],
                    "合計スコア":     r["total_score"],
                    "scratch":       r["scratch_status"],
                    "単勝オッズ(直前)": r["odds_tansho_pre"] or "",
                    "単勝オッズ(確定)": r["odds_tansho_final"] or "",
                    **{c: r[c] for c in SCORE_COLS},
                })

            if payouts:
                f.write("\n払戻金\n")
                f.write("券種,組み合わせ,払戻金(円)\n")
                for p in payouts:
                    f.write(f"{p['bet_type']},{p['combination']},{p['payout']}\n")

        print(f"[DB] CSV出力: {path}")

    def print_horse_history(self, horse_id: str) -> None:
        """馬別履歴をコンソール表示"""
        rows = self.get_horse_history(horse_id)
        if not rows:
            print(f"horse_id={horse_id} のデータなし")
            return
        name = rows[0]["horse_name"] if "horse_name" in rows[0].keys() else horse_id
        print(f"\n── {horse_id} の採点履歴 ──")
        print(f"{'日付':<12} {'競馬場':<4} {'レース名':<16} {'クラス':<8} "
              f"{'予':<3} {'実':<3} {'計':>5}  主な加点")
        print("-" * 80)
        for r in rows:
            main_plus = []
            if r["same_course"]:      main_plus.append(f"同コース+{r['same_course']:.1f}")
            if r["fastest_3f"]:       main_plus.append(f"3F+{r['fastest_3f']:.1f}")
            if r["training_rank"]:    main_plus.append(f"調教+{r['training_rank']:.1f}")
            if r["prev_run_bonus"]:   main_plus.append(f"前走好走+{r['prev_run_bonus']:.1f}")
            if r["inner_post_senko"]: main_plus.append(f"内枠先行+{r['inner_post_senko']:.1f}")
            print(
                f"{r['date']:<12} {r['venue']:<4} {r['race_name']:<16} {r['race_class']:<8} "
                f"{r['predicted_rank'] or '-':<3} {r['actual_rank'] or '-':<3} "
                f"{r['total_score']:>+5.1f}  {' / '.join(main_plus)}"
            )


# ────────────────────────────────────────────────────────────
# ユーティリティ
# ────────────────────────────────────────────────────────────
def _race_id_from_url(url: str) -> Optional[str]:
    import re
    m = re.search(r"race_id=(\d{12})", url)
    return m.group(1) if m else None


# ────────────────────────────────────────────────────────────
# CLI（簡易確認用）
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    db = RaceDB()

    if len(sys.argv) < 2:
        print("使い方:")
        print("  python3 race_db.py summary <race_id>")
        print("  python3 race_db.py horse   <horse_id>")
        print("  python3 race_db.py csv     <race_id> [output.csv]")
        print("  python3 race_db.py accuracy")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "summary" and len(sys.argv) >= 3:
        race_id = sys.argv[2]
        rows = db.get_race_summary(race_id)
        print(f"{'予':>3} {'実':>3} {'枠':>2} {'馬番':>3} {'馬名':<16} {'計':>5}  単勝")
        print("-" * 60)
        for r in rows:
            scratch = " [取消]" if r["scratch_status"] == 1 else (" [除外]" if r["scratch_status"] == 2 else "")
            print(f"{r['predicted_rank']:>3} {r['actual_rank'] or '-':>3} {r['frame']:>2} "
                  f"{r['horse_num']:>3} {r['horse_name']:<16} {r['total_score']:>+5.1f}  "
                  f"{r['odds_tansho_pre'] or '-'}{scratch}")
        payouts = db.get_payouts(race_id)
        if payouts:
            print("\n払戻金:")
            for p in payouts:
                print(f"  {p['bet_type']:6s} {p['combination']:10s} {p['payout']:,}円")

    elif cmd == "horse" and len(sys.argv) >= 3:
        db.print_horse_history(sys.argv[2])

    elif cmd == "csv" and len(sys.argv) >= 3:
        race_id = sys.argv[2]
        path = sys.argv[3] if len(sys.argv) >= 4 else f"export_{race_id}.csv"
        db.export_csv(race_id, path)

    elif cmd == "accuracy":
        print("\nクラス別的中率（芝）")
        print(f"{'クラス':<10} {'レース数':>6}  単勝  複勝")
        print("-" * 40)
        for row in db.accuracy_by_class("芝"):
            n = row["races"]
            print(f"{row['race_class']:<10} {n:>6}  "
                  f"{row['tan']}/{n}({row['tan']/n*100:.0f}%)  "
                  f"{row['fuku']}/{n}({row['fuku']/n*100:.0f}%)")
