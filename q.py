import streamlit as st
import pandas as pd
import random
import json
import datetime

import gspread
from google.oauth2.service_account import Credentials

# -----------------------------------------------------------------------------
# 1. 頁面配置與基本資料載入
# -----------------------------------------------------------------------------
st.set_page_config(page_title="個人專屬刷題系統", layout="wide")

SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

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
# 1b. 題型判斷（同時相容中文命名與 CSV 實際使用的英文命名）
# -----------------------------------------------------------------------------
TF_LABELS = {"TrueFalse", "是非題", "是非"}
MC_LABELS = {"SingleChoice", "選擇題", "選擇"}

def is_tf_type(type_str):
    return str(type_str).strip() in TF_LABELS

def is_mc_type(type_str):
    return str(type_str).strip() in MC_LABELS

# -----------------------------------------------------------------------------
# 1c. 進度持久化：使用 Google Sheet 當外部儲存，不怕 Streamlit Cloud 容器重建
#     做法：把整包進度序列化成一段 JSON 字串，存放在該試算表第一個工作表的 A1 儲存格。
# -----------------------------------------------------------------------------
@st.cache_resource
def get_gsheet():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SHEET_SCOPES
    )
    client = gspread.authorize(creds)
    return client.open_by_key(st.secrets["sheet_id"]).sheet1

def load_progress():
    try:
        raw = get_gsheet().acell('A1').value
        if raw:
            return json.loads(raw)
    except Exception as e:
        st.sidebar.warning(f"⚠️ 無法連線雲端進度資料庫，本次先以空白進度開始。({e})")
    return {}

def save_progress():
    data = {
        'used_ids': list(st.session_state.used_ids),
        'wrong_ids': list(st.session_state.wrong_ids),
        'score_history': st.session_state.score_history,
    }
    try:
        get_gsheet().update('A1', [[json.dumps(data, ensure_ascii=False)]])
    except Exception as e:
        st.sidebar.error(f"⚠️ 進度儲存失敗，本次結果可能不會保留：{e}")

# -----------------------------------------------------------------------------
# 2. 初始化 Session State 狀態（個人歷程紀錄）
# -----------------------------------------------------------------------------
if 'progress_loaded' not in st.session_state:
    _progress = load_progress()
    st.session_state.used_ids = {str(x) for x in _progress.get('used_ids', [])}
    st.session_state.wrong_ids = {str(x) for x in _progress.get('wrong_ids', [])}
    st.session_state.score_history = _progress.get('score_history', [])
    st.session_state.progress_loaded = True

if 'exam_paper' not in st.session_state:
    st.session_state.exam_paper = []

if 'submitted' not in st.session_state:
    st.session_state.submitted = False

if 'user_answers' not in st.session_state:
    st.session_state.user_answers = {}

if 'current_mode' not in st.session_state:
    st.session_state.current_mode = None

if 'exam_results' not in st.session_state:
    st.session_state.exam_results = None       # 交卷當下算好的批改結果，畫面重繪只讀不重算

if 'result_recorded' not in st.session_state:
    st.session_state.result_recorded = False   # 本次考卷是否已寫入歷史紀錄，避免重複計次

MODE_LABELS = {
    "formal": "正式考試",
    "category": "題型/分類考試",
    "wrong": "錯誤題練習",
}

def start_new_paper(paper, mode_key):
    """開始一份新考卷時，重置所有作答相關狀態。"""
    st.session_state.current_mode = mode_key
    st.session_state.submitted = False
    st.session_state.user_answers = {}
    st.session_state.exam_results = None
    st.session_state.result_recorded = False
    st.session_state.exam_paper = paper

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
    save_progress()
    st.sidebar.success("已重置抽題紀錄，可重新開始循環！")
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("🕒 歷史成績紀錄")
if st.session_state.score_history:
    hist_df = pd.DataFrame(st.session_state.score_history[::-1])  # 最新的排前面
    hist_df = hist_df.rename(columns={
        "time": "時間", "mode": "模式", "score": "答對",
        "total": "總題數", "percent": "得分",
    })
    st.sidebar.dataframe(hist_df, use_container_width=True, hide_index=True)
    if st.sidebar.button("🧹 清除歷史成績紀錄"):
        st.session_state.score_history = []
        save_progress()
        st.sidebar.success("已清除歷史成績紀錄")
        st.rerun()
else:
    st.sidebar.caption("尚無作答紀錄")

st.sidebar.markdown("---")
mode = st.sidebar.radio("請選擇測驗模式：", ["正式考試", "題型/分類考試", "錯誤題練習"])

# -----------------------------------------------------------------------------
# 4. 輔助函式：產生題目選項與答案正規化
# -----------------------------------------------------------------------------
def get_options_for_question(row):
    """根據 CSV 的 Type 建立選項，使用與 Answer 一致的數字編碼（1~5）。"""
    q_type = str(row['Type']).strip()

    if is_tf_type(q_type):
        return {"1": "1. 對", "2": "2. 錯"}

    options = {}
    option_map = [
        ("1", "Option_A"),
        ("2", "Option_B"),
        ("3", "Option_C"),
        ("4", "Option_D"),
        ("5", "Option_E"),
    ]
    for code, opt_col in option_map:
        if opt_col in row and str(row[opt_col]).strip() != "":
            options[code] = f"{code}. {row[opt_col]}"
    return options

def normalize_answer(answer, q_type):
    """把使用者作答與 CSV 的 Answer 欄位統一轉成 1~5 的數字格式，
    這樣不論 CSV 裡存的是 O/X、對/錯，還是字母或數字，都能正確比對。"""
    answer = str(answer).strip().upper()
    q_type = str(q_type).strip()

    if is_tf_type(q_type):
        mapping = {
            "1": "1", "2": "2",
            "對": "1", "錯": "2",
            "O": "1", "X": "2",
            "TRUE": "1", "FALSE": "2",
        }
        return mapping.get(answer, answer)

    mapping = {
        "1": "1", "2": "2", "3": "3", "4": "4", "5": "5",
        "A": "1", "B": "2", "C": "3", "D": "4", "E": "5",
    }
    return mapping.get(answer, answer)

def generate_exam(df_subset, tf_count, mc_count):
    """自訂組卷邏輯，抽完後打亂順序，讓是非題與選擇題混合出現。"""
    tf_pool = df_subset[df_subset['Type'].apply(is_tf_type)]
    mc_pool = df_subset[df_subset['Type'].apply(is_mc_type)]

    selected_tf = tf_pool.sample(n=min(tf_count, len(tf_pool))).to_dict('records') if len(tf_pool) > 0 else []
    selected_mc = mc_pool.sample(n=min(mc_count, len(mc_pool))).to_dict('records') if len(mc_pool) > 0 else []

    paper = selected_tf + selected_mc
    random.shuffle(paper)
    return paper

# -----------------------------------------------------------------------------
# 5. 模式切換邏輯
# -----------------------------------------------------------------------------
if mode == "正式考試":
    st.header("🎯 正式考試模式")
    st.caption("每次從未考題庫中隨機抽出 10 題是非題與 30 題選擇題，考過的題目不會重複出現。")

    unused_df = df_all[~df_all['ID'].astype(str).isin(st.session_state.used_ids)]

    if st.button("🚀 開始/重新抽題 (產生40題考卷)") or st.session_state.current_mode != "formal":
        tf_unused = unused_df[unused_df['Type'].apply(is_tf_type)]
        mc_unused = unused_df[unused_df['Type'].apply(is_mc_type)]

        if len(tf_unused) < 10 or len(mc_unused) < 30:
            st.warning("⚠️剩餘未考題目不足以湊滿 10 題是非與 30 題選擇！將為您抽取剩餘的所有可用題目。")

        start_new_paper(generate_exam(unused_df, 10, 30), "formal")
        st.rerun()

elif mode == "題型/分類考試":
    st.header("📂 題型與 Category 專項練習")

    categories = sorted(list(df_all['Category'].unique()))
    selected_cat = st.selectbox("請選擇 Category 分類：", categories)
    cat_df = df_all[df_all['Category'] == selected_cat]

    num_questions = st.number_input("請選擇抽題數量：", min_value=5, max_value=max(5, len(cat_df)), value=min(20, len(cat_df)), step=5)

    if st.button("開始分類測驗"):
        start_new_paper(cat_df.sample(n=num_questions).to_dict('records'), "category")
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
        save_progress()
        st.success(f"題目 {add_id} 已加入錯題本。")
        st.rerun()

    if st.session_state.wrong_ids:
        wrong_ids_sorted = sorted(st.session_state.wrong_ids, key=lambda x: str(x))

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
            save_progress()
            st.success(f"題目 {remove_id} 已從錯題本移除。")
            st.rerun()

    st.markdown("---")

    if not st.session_state.wrong_ids:
        st.info("目前錯題本中沒有任何題目。")
        st.session_state.exam_paper = []
    else:
        wrong_df = df_all[df_all['ID'].astype(str).isin(st.session_state.wrong_ids)]
        st.write(f"目前錯題庫共有 **{len(wrong_df)}** 題。")

        if st.button("生成錯題考卷") or st.session_state.current_mode != "wrong":
            start_new_paper(wrong_df.to_dict('records'), "wrong")
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

        # 交卷當下：批改一次、更新進度一次、寫入歷史紀錄一次
        if submit_btn:
            score = 0
            total = len(st.session_state.exam_paper)
            details = []

            for q in st.session_state.exam_paper:
                q_id = q['ID']
                options_dict = get_options_for_question(q)
                standard_ans = normalize_answer(q['Answer'], q['Type'])
                user_ans = st.session_state.user_answers.get(q_id, None)
                normalized_user_ans = normalize_answer(user_ans, q['Type']) if user_ans else None

                is_correct = (normalized_user_ans == standard_ans)
                if is_correct:
                    score += 1

                details.append({
                    "q": q,
                    "options_dict": options_dict,
                    "standard_ans": standard_ans,
                    "normalized_user_ans": normalized_user_ans,
                    "is_correct": is_correct,
                })

                if st.session_state.current_mode == "formal":
                    st.session_state.used_ids.add(str(q_id))
                if is_correct:
                    st.session_state.wrong_ids.discard(str(q_id))
                else:
                    st.session_state.wrong_ids.add(str(q_id))

            if not st.session_state.result_recorded:
                final_score = round((score / total) * 100, 1) if total > 0 else 0
                st.session_state.score_history.append({
                    "time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
                    "mode": MODE_LABELS.get(st.session_state.current_mode, str(st.session_state.current_mode)),
                    "score": score,
                    "total": total,
                    "percent": final_score,
                })
                save_progress()
                st.session_state.result_recorded = True

            st.session_state.exam_results = {"score": score, "total": total, "details": details}
            st.session_state.submitted = True
            st.rerun()

    # 情況 B：已提交，顯示含有紅綠標記的題目與核對結果（純顯示，不重算、不重寫）
    else:
        results = st.session_state.exam_results
        score = results["score"]
        total = results["total"]

        for idx, d in enumerate(results["details"], start=1):
            q = d["q"]
            options_dict = d["options_dict"]
            standard_ans = d["standard_ans"]
            normalized_user_ans = d["normalized_user_ans"]
            is_correct = d["is_correct"]

            if st.session_state.current_mode == "formal":
                title_text = f"**第 {idx} 題**"
            else:
                title_text = f"**第 {idx} 題 [{q['Type']}]（分類: {q['Category']}）**"

            if is_correct:
                st.markdown(f"{title_text} :green[✔ 正確]")
            else:
                st.markdown(f"{title_text} :red[✖ 錯誤]")

            st.write(q['Question'])

            for code, opt_text in options_dict.items():
                is_std = (code == standard_ans)
                is_user = (code == normalized_user_ans)

                if is_std and is_user:
                    st.markdown(f"- :green[**{opt_text} (您的選擇 / 正確答案)**]")
                elif is_std:
                    st.markdown(f"- :green[**{opt_text} (正確答案)**]")
                elif is_user:
                    st.markdown(f"- :red[**{opt_text} (您的選擇)**]")
                else:
                    st.markdown(f"- {opt_text}")

            if q.get('Explanation'):
                st.info(f"💡 **解析：** {q['Explanation']}")

            st.markdown("---")

        final_score = round((score / total) * 100, 1) if total > 0 else 0
        st.metric(label="最終得分", value=f"{final_score} 分", delta=f"{score}/{total} 題")

        if st.button("🔄 重新進行測驗"):
            st.session_state.submitted = False
            st.session_state.user_answers = {}
            st.session_state.exam_results = None
            st.session_state.result_recorded = False
            st.rerun()
