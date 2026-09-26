import streamlit as st
import pandas as pd
import random

# -----------------------------------------------------------------------------
# 1. 頁面配置與基本資料載入
# -----------------------------------------------------------------------------
st.set_page_config(page_title="個人專屬刷題系統", layout="wide")

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
if 'used_ids' not in st.session_state:
    st.session_state.used_ids = set()      # 正式考試已考過的 ID

if 'wrong_ids' not in st.session_state:
    st.session_state.wrong_ids = set()     # 錯題本 ID

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
    st.sidebar.success("已重置抽題紀錄，可重新開始循環！")
    st.rerun()

st.sidebar.markdown("---")
mode = st.sidebar.radio("請選擇測驗模式：", ["正式考試", "題型/分類考試", "錯誤題練習"])

# -----------------------------------------------------------------------------
# 4. 輔助函式：產生題目選項
# -----------------------------------------------------------------------------
def get_options_for_question(row):
    """根據題目 Type 判斷並打包選項字典"""
    q_type = str(row['Type']).strip()
    
    # 若為是非題
    if "是非" in q_type or "TrueFalse" in q_type:
        return {"O": "O (正確)", "X": "X (錯誤)"}
    
    # 若為選擇題，動態收集 A~E 欄位有值的選項
    options = {}
    for opt_key, opt_col in [('A', 'Option_A'), ('B', 'Option_B'), ('C', 'Option_C'), ('D', 'Option_D'), ('E', 'Option_E')]:
        if opt_col in row and str(row[opt_col]).strip() != "":
            options[opt_key] = f"{opt_key}. {row[opt_col]}"
            
    return options

def generate_exam(df_subset, tf_count, mc_count):
    """自訂組卷邏輯"""
    tf_pool = df_subset[df_subset['Type'].astype(str).str.strip().isin(['是非', 'TrueFalse'])]
    mc_pool = df_subset[df_subset['Type'].astype(str).str.strip().isin(['選擇', 'SingleChoice'])]
    
    selected_tf = tf_pool.sample(n=min(tf_count, len(tf_pool))).to_dict('records') if len(tf_pool) > 0 else []
    selected_mc = mc_pool.sample(n=min(mc_count, len(mc_pool))).to_dict('records') if len(mc_pool) > 0 else []
    
    paper = selected_tf + selected_mc
    random.shuffle(paper)
    return paper

# -----------------------------------------------------------------------------
# 5. 模式一：正式考試 (10是非 + 30選擇，不重複抽題)
# -----------------------------------------------------------------------------
if mode == "正式考試":
    st.header("🎯 正式考試模式")
    st.caption("每次從未考題庫中隨機抽出 10 題是非題與 30 題選擇題，考過的題目不會重複出現。")
    
    # 篩選未考過的題目
    unused_df = df_all[~df_all['ID'].isin(st.session_state.used_ids)]
    
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
    
    if not st.session_state.wrong_ids:
        st.info("🎉 太棒了！目前錯題本中沒有任何題目。")
        st.session_state.exam_paper = []
    else:
        wrong_df = df_all[df_all['ID'].isin(st.session_state.wrong_ids)]
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
            standard_ans = str(q['Answer']).strip().upper()
            
            # 標記為已考題（僅限正式考試模式）
            if st.session_state.current_mode == "formal":
                st.session_state.used_ids.add(q_id)
            
            # 判斷對錯
            is_correct = (str(user_ans).strip().upper() == standard_ans)
            
            if is_correct:
                score += 1
                # 若在錯題模式下答對，從錯題本移出
                if q_id in st.session_state.wrong_ids:
                    st.session_state.wrong_ids.remove(q_id)
                st.success(f"**第 {idx} 題：正確！**")
            else:
                # 答錯或未作答，加入錯題本
                st.session_state.wrong_ids.add(q_id)
                st.error(f"**第 {idx} 題：錯誤！** | 您的答案：`{user_ans}` | 標準答案：`{standard_ans}`")
                
            if q.get('Explanation'):
                st.info(f"💡 **解析：** {q['Explanation']}")
            st.markdown("---")
            
        final_score = round((score / total) * 100, 1) if total > 0 else 0
        st.metric(label="最終得分", value=f"{final_score} 分", delta=f"{score}/{total} 題")
