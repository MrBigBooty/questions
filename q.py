import streamlit as st
import pandas as pd
import random
import sqlite3

# -----------------------------------------------------------------------------
# 1. 頁面配置與基本資料載入
# -----------------------------------------------------------------------------
st.set_page_config(page_title="個人專屬刷題系統", layout="wide")


# -----------------------------------------------------------------------------
# 1A. 永久保存使用者進度
# -----------------------------------------------------------------------------
# Streamlit 的 session_state 在重新整理頁面後會重新建立，因此：
# - used_ids / wrong_ids 不只存在 session_state
# - 同步寫入本機 SQLite
# 只要 q.py 與 progress.db 位於同一個資料夾，重新整理/重啟程式後資料仍會保留。
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

    # 先確保所有目前資料都有紀錄
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

    # 同步所有既有紀錄，確保移除錯題/重置正式考試也會永久保存
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
    # 讀取 CSV 檔，將所有欄位轉為字串並填補空值
    df = pd.read_csv('questions.csv', dtype=str).fillna('')
    # 清除欄位前後空白
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
        st.session_state.used_ids = saved_used      # 正式考試已考過的 ID

    if 'wrong_ids' not in st.session_state:
        st.session_state.wrong_ids = saved_wrong    # 錯題本 ID

if 'exam_paper' not in st.session_state:
    st.session_state.exam_paper = []       # 當前測驗的題目清單

if 'submitted' not in st.session_state:
    st.session_state.submitted = False     # 當前交卷狀態

if 'user_answers' not in st.session_state:
    st.session_state.user_answers = {}     # 使用者作答紀錄

if 'current_mode' not in st.session_state:
    st.session_state.current_mode = None   # 當前考試模式

# -----------------------------------------------------------------------------
# 3. 側邊欄：功能選單與狀態統計
# -----------------------------------------------------------------------------
st.sidebar.title("📚 刷題系統選單")

# 顯示目前個人進度
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
# 4. 輔助函式：產生題目選項
# -----------------------------------------------------------------------------
def get_options_for_question(row):
    """根據 CSV 的 Type 建立選項，並使用與 Answer 一致的數字編碼。"""
    q_type = str(row['Type']).strip()

    # 是非題：1=對、2=錯
    if q_type in ("TrueFalse", "是非題", "是非"):
        return {"1": "1. 對", "2": "2. 錯"}

    # 選擇題：1=A、2=B、3=C、4=D、5=E
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

    # 是非題：接受 1/2、對/錯、O/X
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

    # 選擇題：接受 1~5 或 A~E
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
    """自訂組卷邏輯"""
    tf_pool = df_subset[df_subset['Type'].astype(str).str.strip().isin(['是非', 'TrueFalse'])]
    mc_pool = df_subset[df_subset['Type'].astype(str).str.strip().isin(['選擇', 'SingleChoice'])]
    
    selected_tf = tf_pool.sample(n=min(tf_count, len(tf_pool))).to_dict('records') if len(tf_pool) > 0 else []
    selected_mc = mc_pool.sample(n=min(mc_count, len(mc_pool))).to_dict('records') if len(mc_pool) > 0 else []
    
    # 正式考試題序固定：前 10 題是非題，後 30 題選擇題
    # 不在這裡 shuffle，讓正式考試的題型位置固定。
    paper = selected_tf + selected_mc
    return paper

# -----------------------------------------------------------------------------
# 5. 模式一：正式考試 (10是非 + 30選擇，不重複抽題)
# -----------------------------------------------------------------------------
if mode == "正式考試":
    st.header("🎯 正式考試模式")
    st.caption("每次從未考題庫中隨機抽出 10 題是非題與 30 題選擇題，考過的題目不會重複出現。")
    
    # 篩選未考過的題目
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

# -----------------------------------------------------------------------------
# 6. 模式二：題型/分類考試
# -----------------------------------------------------------------------------
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
        
        # 按比例抽取或隨機抽取
        paper = cat_df.sample(n=num_questions).to_dict('records')
        st.session_state.exam_paper = paper
        st.rerun()

# -----------------------------------------------------------------------------
# 7. 模式三：錯誤題練習
# -----------------------------------------------------------------------------
elif mode == "錯誤題練習":
    st.header("📝 錯題本專項重測")

    # -------------------------------------------------------------------------
    # 錯題本管理：手動新增 / 指定移除
    # -------------------------------------------------------------------------
    st.subheader("🛠️ 錯題本管理")

    all_question_ids = [str(x) for x in df_all['ID'].tolist()]

    # 手動新增題目
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

    # 指定移除題目
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
# 8. 考卷渲染與作答區 (通用邏輯)
# -----------------------------------------------------------------------------
if st.session_state.exam_paper:
    st.markdown("---")
    st.subheader(f"📋 當前考卷（共 {len(st.session_state.exam_paper)} 題）")
    
    with st.form(key="exam_form"):
        for idx, q in enumerate(st.session_state.exam_paper, start=1):
            q_id = q['ID']
            options_dict = get_options_for_question(q)
            
            # 正式考試不顯示題型與分類，維持正式試卷介面
            if st.session_state.current_mode == "formal":
                st.markdown(f"**第 {idx} 題**")
            else:
                st.markdown(f"**第 {idx} 題 [{q['Type']}]（分類: {q['Category']}）**")
            st.write(q['Question'])
            
            # 單選題組件
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

    # -------------------------------------------------------------------------
    # 9. 計分與錯題紀錄處理
    # -------------------------------------------------------------------------
    if submit_btn:
        st.session_state.submitted = True
        score = 0
        total = len(st.session_state.exam_paper)
        
        st.header("💯 測驗結果與解析")
        
        for idx, q in enumerate(st.session_state.exam_paper, start=1):
            q_id = q['ID']
            user_ans = st.session_state.user_answers.get(q_id, "未作答")
            standard_ans = normalize_answer(q['Answer'], q['Type'])
            normalized_user_ans = normalize_answer(user_ans, q['Type'])
            
            # 標記為已考題（僅限正式考試模式）
            if st.session_state.current_mode == "formal":
                st.session_state.used_ids.add(str(q_id))
                update_question_status(q_id, is_used=True)
            
            # 判斷對錯
            is_correct = (normalized_user_ans == standard_ans)
            
            if is_correct:
                score += 1
                # 若在錯題模式下答對，從錯題本移出
                st.session_state.wrong_ids.discard(str(q_id))
                update_question_status(q_id, is_wrong=False)
                st.success(f"**第 {idx} 題：正確！**")
            else:
                # 答錯或未作答，加入錯題本
                st.session_state.wrong_ids.add(str(q_id))
                update_question_status(q_id, is_wrong=True)
                st.error(
                    f"**第 {idx} 題：錯誤！** | "
                    f"您的答案：`{user_ans}`（代碼 {normalized_user_ans}） | "
                    f"標準答案：`{standard_ans}`"
                )
                
            if q.get('Explanation'):
                st.info(f"💡 **解析：** {q['Explanation']}")
            st.markdown("---")
            
        final_score = round((score / total) * 100, 1) if total > 0 else 0
        st.metric(label="最終得分", value=f"{final_score} 分", delta=f"{score}/{total} 題")
