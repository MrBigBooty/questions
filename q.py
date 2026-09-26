import streamlit as st
import pandas as pd
import random
import sqlite3

# -----------------------------------------------------------------------------
# 1. 頁面配置與基本資料載入
# -----------------------------------------------------------------------------
st.set_page_config(page_title="個人專屬刷題系統", layout="wide")

DB_FILE = "progress.db"


def init_database():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS question_progress (
            question_id TEXT PRIMARY KEY,
            is_used INTEGER NOT NULL DEFAULT 0,
            is_wrong INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def load_progress():
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT question_id, is_used, is_wrong FROM question_progress"
    ).fetchall()
    conn.close()

    used = {str(qid) for qid, is_used, _ in rows if is_used}
    wrong = {str(qid) for qid, _, is_wrong in rows if is_wrong}
    return used, wrong


def save_progress(used_ids, wrong_ids):
    conn = sqlite3.connect(DB_FILE)

    all_ids = {str(x) for x in used_ids} | {str(x) for x in wrong_ids}
    for qid in all_ids:
        conn.execute("""
            INSERT INTO question_progress (question_id, is_used, is_wrong)
            VALUES (?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                is_used = excluded.is_used,
                is_wrong = excluded.is_wrong
        """, (
            qid,
            1 if qid in used_ids else 0,
            1 if qid in wrong_ids else 0
        ))

    conn.execute("""
        UPDATE question_progress
        SET is_used = 0
        WHERE question_id NOT IN (
            SELECT question_id FROM question_progress
        )
    """)

    conn.commit()
    conn.close()


def update_question_status(question_id, *, is_used=None, is_wrong=None):
    """只修改指定題目的永久狀態。"""
    qid = str(question_id)
    conn = sqlite3.connect(DB_FILE)

    row = conn.execute(
        "SELECT is_used, is_wrong FROM question_progress WHERE question_id = ?",
        (qid,)
    ).fetchone()

    current_used = row[0] if row else 0
    current_wrong = row[1] if row else 0

    new_used = current_used if is_used is None else (1 if is_used else 0)
    new_wrong = current_wrong if is_wrong is None else (1 if is_wrong else 0)

    conn.execute("""
        INSERT INTO question_progress (question_id, is_used, is_wrong)
        VALUES (?, ?, ?)
        ON CONFLICT(question_id) DO UPDATE SET
            is_used = excluded.is_used,
            is_wrong = excluded.is_wrong
    """, (qid, new_used, new_wrong))

    conn.commit()
    conn.close()


init_database()

@st.cache_data
def load_data():
    df = pd.read_csv('questions.csv', dtype=str).fillna('')
    df.columns = df.columns.str.strip()
    return df

try:
    df_all = load_data()
except Exception as e:
    st.error(f"無法讀取 CSV 檔案，請確認檔名為 'questions.csv' 且欄位正確。錯誤資訊: {e}")
    st.stop()

# -----------------------------------------------------------------------------
# 2. 初始化 Session State 狀態（個人歷程紀錄）
# -----------------------------------------------------------------------------
if 'used_ids' not in st.session_state or 'wrong_ids' not in st.session_state:
    saved_used, saved_wrong = load_progress()

    if 'used_ids' not in st.session_state:
        st.session_state.used_ids = saved_used

    if 'wrong_ids' not in st.session_state:
        st.session_state.wrong_ids = saved_wrong

if 'exam_paper' not in st.session_state:
    st.session_state.exam_paper = []

if 'submitted' not in st.session_state:
    st.session_state.submitted = False

if 'user_answers' not in st.session_state:
    st.session_state.user_answers = {}

if 'current_mode' not in st.session_state:
    st.session_state.current_mode = None

# -----------------------------------------------------------------------------
# 3. 側邊欄：功能選單與狀態統計
# -----------------------------------------------------------------------------
st.sidebar.title("📚 刷題系統選單")

st.sidebar.markdown("---")
st.sidebar.subheader("📊 答題進度統計")
st.sidebar.write(f"• 正式考試已考題數：**{len(st.session_state.used_ids)}** / {len(df_all)}")
st.sidebar.write(f"• 錯題本累積題數：**{len(st.session_state.wrong_ids)}** 題")

if st.sidebar.button("🗑️ 重置正式考試抽題池"):
    st.session_state.used_ids = set()
    save_progress(st.session_state.used_ids, st.session_state.wrong_ids)
    st.sidebar.success("已重置抽題紀錄，可重新開始循環！")
    st.rerun()

st.sidebar.markdown("---")
mode = st.sidebar.radio("請選擇測驗模式：", ["正式考試", "題型/分類考試", "錯誤題練習"])

# -----------------------------------------------------------------------------
# 4. 輔助函式：產生題目選項與格式化
# -----------------------------------------------------------------------------
def get_options_for_question(row):
    """根據 CSV 的 Type 建立選項，並使用與 Answer 一致的數字編碼。"""
    q_type = str(row['Type']).strip()

    if q_type in ("TrueFalse", "是非題", "是非"):
        return {"1": "1. 對", "2": "2. 錯"}

    options = {}
    option_map = [
        ("1", "A", "Option_A"),
        ("2", "B", "Option_B"),
        ("3", "C", "Option_C"),
        ("4", "D", "Option_D"),
        ("5", "E", "Option_E"),
    ]

    for answer_code, letter, opt_col in option_map:
        if opt_col in row and str(row[opt_col]).strip() != "":
            options[answer_code] = f"{answer_code}. {row[opt_col]}"

    return options


def normalize_answer(answer, q_type):
    """將使用者答案與 CSV Answer 統一成 1~5 的數字格式。"""
    answer = str(answer).strip().upper()
    q_type = str(q_type).strip()

    if q_type in ("TrueFalse", "是非題", "是非"):
        mapping = {
            "1": "1",
            "2": "2",
            "對": "1",
            "錯": "2",
            "O": "1",
            "X": "2",
            "TRUE": "1",
            "FALSE": "2",
        }
        return mapping.get(answer, answer)

    mapping = {
        "1": "1",
        "2": "2",
        "3": "3",
        "4": "4",
        "5": "5",
        "A": "1",
        "B": "2",
        "C": "3",
        "D": "4",
        "E": "5",
    }
    return mapping.get(answer, answer)


def generate_exam(df_subset, tf_count, mc_count):
    tf_pool = df_subset[df_subset['Type'].astype(str).str.strip().isin(['是非', 'TrueFalse'])]
    mc_pool = df_subset[df_subset['Type'].astype(str).str.strip().isin(['選擇', 'SingleChoice'])]
    
    selected_tf = tf_pool.sample(n=min(tf_count, len(tf_pool))).to_dict('records') if len(tf_pool) > 0 else []
    selected_mc = mc_pool.sample(n=min(mc_count, len(mc_pool))).to_dict('records') if len(mc_pool) > 0 else []
    
    paper = selected_tf + selected_mc
    return paper

# -----------------------------------------------------------------------------
# 5. 模式切換邏輯
# -----------------------------------------------------------------------------
if mode == "正式考試":
    st.header("🎯 正式考試模式")
    st.caption("每次從未考題庫中隨機抽出 10 題是非題與 30 題選擇題，考過的題目不會重複出現。")
    
    unused_df = df_all[~df_all['ID'].astype(str).isin(st.session_state.used_ids)]
    
    if st.button("🚀 開始/重新抽題 (產生40題考卷)") or st.session_state.current_mode != "formal":
        st.session_state.current_mode = "formal"
        st.session_state.submitted = False
        st.session_state.user_answers = {}
        
        tf_unused = unused_df[unused_df['Type'].astype(str).str.strip().isin(['是非', 'TrueFalse'])]
        mc_unused = unused_df[unused_df['Type'].astype(str).str.strip().isin(['選擇', 'SingleChoice'])]
        
        if len(tf_unused) < 10 or len(mc_unused) < 30:
            st.warning("⚠️剩餘未考題目不足以湊滿 10 題是非與 30 題選擇！將為您抽取剩餘的所有可用題目。")
            
        st.session_state.exam_paper = generate_exam(unused_df, 10, 30)
        st.rerun()

elif mode == "題型/分類考試":
    st.header("📂 題型與 Category 專項練習")
    
    categories = sorted(list(df_all['Category'].unique()))
    selected_cat = st.selectbox("請選擇 Category 分類：", categories)
    cat_df = df_all[df_all['Category'] == selected_cat]
    
    num_questions = st.number_input("請選擇抽題數量：", min_value=5, max_value=max(5, len(cat_df)), value=min(20, len(cat_df)), step=5)
    
    if st.button("開始分類測驗"):
        st.session_state.current_mode = "category"
        st.session_state.submitted = False
        st.session_state.user_answers = {}
        
        paper = cat_df.sample(n=num_questions).to_dict('records')
        st.session_state.exam_paper = paper
        st.rerun()

elif mode == "錯誤題練習":
    st.header("📝 錯題本專項重測")
    st.subheader("🛠️ 錯題本管理")

    all_question_ids = [str(x) for x in df_all['ID'].tolist()]

    add_id = st.selectbox(
        "新增指定題目到錯題本：",
        options=all_question_ids,
        format_func=lambda qid: (
            f"{qid}｜{df_all.loc[df_all['ID'].astype(str) == qid, 'Question'].iloc[0][:70]}"
        ),
        key="add_wrong_question_id"
    )

    if st.button("➕ 新增至錯題本", key="add_wrong_btn"):
        st.session_state.wrong_ids.add(str(add_id))
        update_question_status(add_id, is_wrong=True)
        st.success(f"題目 {add_id} 已加入錯題本。")
        st.rerun()

    if st.session_state.wrong_ids:
        wrong_ids_sorted = sorted(
            st.session_state.wrong_ids,
            key=lambda x: str(x)
        )

        remove_id = st.selectbox(
            "從錯題本移除指定題目：",
            options=wrong_ids_sorted,
            format_func=lambda qid: (
                f"{qid}｜{df_all.loc[df_all['ID'].astype(str) == qid, 'Question'].iloc[0][:70]}"
                if not df_all.loc[df_all['ID'].astype(str) == qid].empty
                else qid
            ),
            key="remove_wrong_question_id"
        )

        if st.button("➖ 從錯題本移除", key="remove_wrong_btn"):
            st.session_state.wrong_ids.discard(str(remove_id))
            update_question_status(remove_id, is_wrong=False)
            st.success(f"題目 {remove_id} 已從錯題本移除。")
            st.rerun()

    st.markdown("---")

    if not st.session_state.wrong_ids:
        st.info("目前錯題本中沒有任何題目。")
        st.session_state.exam_paper = []
    else:
        wrong_df = df_all[
            df_all['ID'].astype(str).isin(st.session_state.wrong_ids)
        ]
        st.write(f"目前錯題庫共有 **{len(wrong_df)}** 題。")

        if st.button("生成錯題考卷") or st.session_state.current_mode != "wrong":
            st.session_state.current_mode = "wrong"
            st.session_state.submitted = False
            st.session_state.user_answers = {}
            st.session_state.exam_paper = wrong_df.to_dict('records')
            st.rerun()

# -----------------------------------------------------------------------------
# 6. 考卷渲染與作答/核對區
# -----------------------------------------------------------------------------
if st.session_state.exam_paper:
    st.markdown("---")
    st.subheader(f"📋 當前考卷（共 {len(st.session_state.exam_paper)} 題）")
    
    # 情況 A：尚未提交，顯示可填答表單
    if not st.session_state.submitted:
        with st.form(key="exam_form"):
            for idx, q in enumerate(st.session_state.exam_paper, start=1):
                q_id = q['ID']
                options_dict = get_options_for_question(q)
                
                if st.session_state.current_mode == "formal":
                    st.markdown(f"**第 {idx} 題**")
                else:
                    st.markdown(f"**第 {idx} 題 [{q['Type']}]（分類: {q['Category']}）**")
                st.write(q['Question'])
                
                user_choice = st.radio(
                    label=f"請選擇第 {idx} 題答案：",
                    options=list(options_dict.keys()),
                    format_func=lambda x: options_dict[x],
                    key=f"q_{q_id}",
                    index=None,
                    label_visibility="collapsed"
                )
                
                if user_choice:
                    st.session_state.user_answers[q_id] = user_choice
                    
                st.markdown("---")
                
            submit_btn = st.form_submit_button("📤 提交考卷並核對答案", type="primary")
            if submit_btn:
                st.session_state.submitted = True
                st.rerun()

    # 情況 B：已提交，顯示含有紅綠標記的題目與核對結果
    else:
        score = 0
        total = len(st.session_state.exam_paper)

        for idx, q in enumerate(st.session_state.exam_paper, start=1):
            q_id = q['ID']
            options_dict = get_options_for_question(q)
            standard_ans = normalize_answer(q['Answer'], q['Type'])
            user_ans = st.session_state.user_answers.get(q_id, None)
            normalized_user_ans = normalize_answer(user_ans, q['Type']) if user_ans else None
            
            is_correct = (normalized_user_ans == standard_ans)
            
            # 更新狀態
            if st.session_state.current_mode == "formal":
                st.session_state.used_ids.add(str(q_id))
                update_question_status(q_id, is_used=True)
            
            if is_correct:
                score += 1
                st.session_state.wrong_ids.discard(str(q_id))
                update_question_status(q_id, is_wrong=False)
            else:
                st.session_state.wrong_ids.add(str(q_id))
                update_question_status(q_id, is_wrong=True)

            # 顯示題目頭部與狀態
            if st.session_state.current_mode == "formal":
                title_text = f"**第 {idx} 題**"
            else:
                title_text = f"**第 {idx} 題 [{q['Type']}]（分類: {q['Category']}）**"
                
            if is_correct:
                st.markdown(f"{title_text} :green[✔ 正確]")
            else:
                st.markdown(f"{title_text} :red[✖ 錯誤]")

            st.write(q['Question'])

            # 渲染選項並進行紅綠著色
            for code, opt_text in options_dict.items():
                is_std = (code == standard_ans)
                is_user = (code == normalized_user_ans)

                if is_std and is_user:
                    # 選對：正確答案標綠色
                    st.markdown(f"- :green[**{opt_text} (您的選擇 / 正確答案)**]")
                elif is_std:
                    # 這是正確答案，但使用者沒選或選錯：標綠色
                    st.markdown(f"- :green[**{opt_text} (正確答案)**]")
                elif is_user:
                    # 使用者選錯的選項：標紅色
                    st.markdown(f"- :red[**{opt_text} (您的選擇)**]")
                else:
                    # 其他未選選項：維持原樣
                    st.markdown(f"- {opt_text}")

            if q.get('Explanation'):
                st.info(f"💡 **解析：** {q['Explanation']}")
                
            st.markdown("---")

        # 頂部/底部分數統計與重新開始按鈕
        final_score = round((score / total) * 100, 1) if total > 0 else 0
        st.metric(label="最終得分", value=f"{final_score} 分", delta=f"{score}/{total} 題")
        
        if st.button("🔄 重新進行測驗"):
            st.session_state.submitted = False
            st.session_state.user_answers = {}
            st.rerun()
