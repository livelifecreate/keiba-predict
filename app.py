"""
競馬予想ビューア — Streamlit アプリ
"""
import csv
import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="競馬予想",
    page_icon="🏇",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── パスワード認証 ────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🏇 競馬予想システム")
    pwd = st.text_input("パスワード", type="password", placeholder="パスワードを入力")
    if st.button("ログイン", type="primary"):
        correct = st.secrets.get("password", "")
        if correct and pwd == correct:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    st.stop()
# ─────────────────────────────────────────────────────────────────────────────

RESULTS_DIR = Path(__file__).parent / "results"

SIGN_ORDER = {"★7pt推奨": 0, "★フォームB推奨": 1, "★フォームB": 2, "": 3}
SIGN_COLOR = {
    "★7pt推奨":    "#c0392b",
    "★フォームB推奨": "#e67e22",
    "★フォームB":   "#2980b9",
    "":            "#7f8c8d",
}
SIGN_LABEL = {
    "★7pt推奨":    "🎯 7pt推奨",
    "★フォームB推奨": "📋 フォームB推奨",
    "★フォームB":   "📋 フォームB",
    "":            "⚠ 見送り",
}


# ── CSV パーサー ──────────────────────────────────────────────────────────────

def parse_csv(path: Path) -> dict:
    """CSV を読んでレース情報を辞書で返す"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        raw = f.read()

    lines = raw.splitlines()
    horse_lines = []
    sign_type = sign_detail = ""
    formb_header = formb_combos = []
    form7_header = form7_combos = []
    eval_comments = []
    race_surface_dist = ""
    section = "horses"

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = next(csv.reader([line]))

        if parts[0] == "■買いサイン":
            sign_type   = parts[1] if len(parts) > 1 else ""
            sign_detail = parts[2] if len(parts) > 2 else ""
            section = "sign"
        elif parts[0] == "■レース情報":
            race_surface_dist = parts[1] if len(parts) > 1 else ""
            section = "raceinfo"
        elif parts[0] == "■評価コメント":
            eval_comments = []
            section = "eval"
        elif parts[0] == "■三連複フォームB":
            formb_header = parts[1:]
            formb_combos = []
            section = "formb"
        elif parts[0] == "■三連複7点":
            form7_header = parts[1:]
            form7_combos = []
            section = "form7"
        elif section == "horses" and not parts[0].startswith("■"):
            horse_lines.append(line)
        elif section == "eval" and parts[0] == "" and len(parts) > 1 and parts[1].strip():
            eval_comments.append(parts[1].strip())
        elif section == "formb" and parts[0] == "" and len(parts) > 1 and parts[1].strip():
            formb_combos.append(parts[1].strip())
        elif section == "form7" and parts[0] == "" and len(parts) > 1 and parts[1].strip():
            form7_combos.append(parts[1].strip())

    df = pd.read_csv(io.StringIO("\n".join(horse_lines))) if horse_lines else pd.DataFrame()

    return {
        "df": df,
        "sign_type": sign_type,
        "sign_detail": sign_detail,
        "eval_comments": eval_comments,
        "race_surface_dist": race_surface_dist,
        "formb_header": formb_header,
        "formb_combos": formb_combos,
        "form7_header": form7_header,
        "form7_combos": form7_combos,
    }


# ── ファイル一覧取得 ──────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_race_index() -> list[dict]:
    races = []
    for p in sorted(RESULTS_DIR.glob("*/*/score_*.csv"), reverse=True):
        fname = p.stem  # score_2026613_函館_11R_函館スプリントS_★フォームB
        date_dir = p.parent.parent.name   # 2026-06-13
        venue    = p.parent.name          # 函館

        # ★タグ抽出
        sign_tag = ""
        if "★" in fname:
            sign_tag = "★" + fname.split("★", 1)[1]

        # Rナンバー・馬場・レース名（新形式: _9R_芝1600m_日野特別 / 旧形式: _9R_日野特別）
        m_new = re.search(r'_(\d+)R_(芝\d+m|ダート\d+m|障害\d+m)_(.+?)(?:_★|$)', fname)
        m_old = re.search(r'_(\d+)R_(.+?)(?:_★|$)', fname)
        if m_new:
            race_num       = int(m_new.group(1))
            surface_dist   = m_new.group(2)
            race_name      = m_new.group(3).replace("_", " ")
        elif m_old:
            race_num       = int(m_old.group(1))
            surface_dist   = ""
            race_name      = m_old.group(2).replace("_", " ")
        else:
            race_num, surface_dist, race_name = 0, "", fname

        races.append({
            "date":          date_dir,
            "venue":         venue,
            "race_num":      race_num,
            "race_name":     race_name,
            "surface_dist":  surface_dist,
            "sign_tag":      sign_tag,
            "path":          p,
            "label":         f"{venue} {race_num}R {race_name}",
        })

    races.sort(key=lambda r: (
        r["date"],
        r["venue"],
        SIGN_ORDER.get(r["sign_tag"], 3),
        r["race_num"],
    ), reverse=True)
    return races


# ── サイドバー ────────────────────────────────────────────────────────────────

st.sidebar.title("🏇 競馬予想")

all_races = load_race_index()
if not all_races:
    st.warning("results/ にCSVが見つかりません。weekend_predict.py を実行してください。")
    st.stop()

dates = sorted({r["date"] for r in all_races}, reverse=True)
sel_date = st.sidebar.selectbox("📅 日付", dates)

day_races = [r for r in all_races if r["date"] == sel_date]

venues = sorted({r["venue"] for r in day_races})
sel_venues = st.sidebar.multiselect("🏟 会場", venues, default=venues)

sign_options = ["買いサインのみ", "全レース"]
sel_filter = st.sidebar.radio("フィルタ", sign_options, index=0)

filtered = [
    r for r in day_races
    if r["venue"] in sel_venues
    and (sel_filter == "全レース" or r["sign_tag"])
]

if not filtered:
    st.info("該当レースなし")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.markdown(f"**{len(filtered)} レース**")

labels = [f"{SIGN_LABEL.get(r['sign_tag'], '⚠')}  {r['label']}" for r in filtered]
sel_idx = st.sidebar.radio("レース選択", range(len(filtered)), format_func=lambda i: labels[i])

race = filtered[sel_idx]


# ── メイン画面 ────────────────────────────────────────────────────────────────

data = parse_csv(race["path"])
df   = data["df"]

sign_tag    = race["sign_tag"]
sign_color  = SIGN_COLOR.get(sign_tag, "#7f8c8d")
sign_label  = SIGN_LABEL.get(sign_tag, "⚠ 見送り")
sign_detail = data["sign_detail"]

# 馬場・距離（ファイル名優先、なければCSV内■レース情報から）
surface_dist = race.get("surface_dist") or data.get("race_surface_dist", "")
surface_badge = (
    f"<span style='background:#27ae60;color:white;padding:2px 8px;"
    f"border-radius:4px;font-size:0.8em;margin-left:8px'>{surface_dist}</span>"
    if surface_dist else ""
)

# タイトル
st.markdown(
    f"<h2 style='margin-bottom:4px'>{race['venue']} {race['race_num']}R　{race['race_name']}{surface_badge}</h2>",
    unsafe_allow_html=True,
)
st.markdown(
    f"<span style='background:{sign_color};color:white;padding:4px 12px;"
    f"border-radius:6px;font-weight:bold'>{sign_label}</span>"
    f"&nbsp;&nbsp;<span style='color:#555;font-size:0.9em'>{sign_detail}</span>",
    unsafe_allow_html=True,
)
st.markdown("")

# 馬スコア表
if not df.empty:
    show_cols = [c for c in ["順位", "馬番", "馬名", "合計スコア", "単勝オッズ", "人気", "調教コメント"] if c in df.columns]
    st.dataframe(
        df[show_cols].set_index("順位"),
        use_container_width=True,
        height=min(50 + len(df) * 38, 520),
    )

# 評価コメント
if data["eval_comments"]:
    box_color = sign_color
    comment_html = "".join(f"<li>{c}</li>" for c in data["eval_comments"])
    st.markdown(
        f"<div style='background:{box_color}18;border-left:4px solid {box_color};"
        f"padding:10px 14px;border-radius:4px;margin:8px 0'>"
        f"<ul style='margin:0;padding-left:18px;color:#333'>{comment_html}</ul></div>",
        unsafe_allow_html=True,
    )

# 買い目
col1, col2 = st.columns(2)

with col1:
    if data["formb_combos"]:
        h = data["formb_header"]
        st.markdown(f"**■ 三連複フォームB**")
        if h:
            st.caption("  ".join(h))
        combo_text = "　".join(data["formb_combos"])
        # 3列表示
        chunks = [data["formb_combos"][i:i+6] for i in range(0, len(data["formb_combos"]), 6)]
        for chunk in chunks:
            st.text("  ".join(chunk))

with col2:
    if data["form7_combos"]:
        h = data["form7_header"]
        st.markdown(f"**■ 三連複7点**")
        if h:
            st.caption("  ".join(h))
        chunks = [data["form7_combos"][i:i+6] for i in range(0, len(data["form7_combos"]), 6)]
        for chunk in chunks:
            st.text("  ".join(chunk))

# 加点・減点詳細（展開式）
if not df.empty and "加点内訳" in df.columns:
    with st.expander("加点・減点詳細"):
        detail_cols = [c for c in ["馬番", "馬名", "合計スコア", "加点内訳", "減点内訳"] if c in df.columns]
        st.dataframe(df[detail_cols].set_index("馬番"), use_container_width=True)
