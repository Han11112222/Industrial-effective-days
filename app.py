# app.py — 요일/공휴일 공급량 비중(%) 분석 + 금요일 집중 보기
# • GitHub raw XLSX/CSV 읽기(blob → raw 자동 보정)
# • 월별 총공급량 대비 선택 요일(월~일) 또는 공휴일 비중(%) — 합계 100%
# • 연도 멀티선택, 요일/공휴일 멀티선택
# • 히트맵(금요일 기본) + 비교막대 + 동적 추세선(Plotly)
# • 한글 폰트: Plotly는 브라우저 렌더라 비교적 안전 / Matplotlib은 숫자만 사용

import re, io
from urllib.parse import urlparse
import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="요일/공휴일 공급량 비중 분석", layout="wide")

st.title("📊 월별 총공급량 대비 요일·공휴일 **공급량 비중(%)**")
st.caption("※ ‘공급량 비중’ = (선택 요일/공휴일 공급량 합 ÷ 해당 월 총공급량) × 100")

# ─────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    raw_url = st.text_input(
        "GitHub raw 파일 URL (xlsx/csv)",
        value="https://raw.githubusercontent.com/Han11112222/Industrial-effective-days/main/effective_days_calendar.xlsx",
        help="깃허브 파일 페이지에서 Raw 버튼 주소를 넣어. blob 주소여도 자동 변환됨."
    )
    st.divider()
    st.markdown("**요일/공휴일 분리 규칙**")
    split_holiday = st.radio(
        "공휴일을 별도 카테고리로 분리(합계 100%)",
        options=["예(권장)","아니오(해당 요일에 포함)"],
        index=0,
        horizontal=True
    ) == "예(권장)"

# ─────────────────────────────────────────────────────────────
# Utils
# ─────────────────────────────────────────────────────────────
def normalize_github_url(url: str) -> str:
    u = url.strip()
    if "raw.githubusercontent.com" in u:
        return u.split("?")[0]
    if "github.com" in u and "/blob/" in u:
        owner_repo, path = u.split("github.com/")[1].split("/blob/")
        return f"https://raw.githubusercontent.com/{owner_repo}/{path}".split("?")[0]
    return u

@st.cache_data(show_spinner=False)
def load_df(url: str) -> pd.DataFrame:
    url = normalize_github_url(url)
    parsed = urlparse(url)
    if "raw.githubusercontent.com" not in parsed.netloc:
        raise ValueError("GitHub raw URL이 아님. Raw 버튼 주소를 넣어줘.")

    # 존재 확인(404 등 친절 메시지)
    h = requests.head(url, timeout=10)
    if h.status_code == 404:
        raise FileNotFoundError("HTTP 404 — 브랜치/경로/파일명(대소문자) 확인")
    h.raise_for_status()

    if url.lower().endswith((".xlsx",".xls")):
        import openpyxl  # ensure installed
        df = pd.read_excel(url, engine="openpyxl")
    elif url.lower().endswith(".csv"):
        try:
            df = pd.read_csv(url, encoding="cp949")
        except:
            df = pd.read_csv(url, encoding="utf-8")
    else:
        raise ValueError("지원 확장자: .xlsx, .xls, .csv")
    return df

def to_float_num(x):
    if pd.isna(x): return np.nan
    if isinstance(x,(int,float,np.number)): return float(x)
    s = str(x).replace(",","")
    try: return float(s)
    except: return np.nan

def parse_date8(s):
    s = str(s).strip()
    if re.fullmatch(r"\d{8}", s):
        return pd.to_datetime(s, format="%Y%m%d")
    return pd.to_datetime(s, errors="coerce")

# ─────────────────────────────────────────────────────────────
# Load
# ─────────────────────────────────────────────────────────────
try:
    raw_df = load_df(raw_url)
    st.success("데이터 로딩 완료")
except Exception as e:
    st.error(f"데이터 로딩 실패: {e}")
    st.stop()

# 표준 컬럼명 점검
need = ["날짜","연","월","요일","공휴일여부","공급량(MJ)"]
missing = [c for c in need if c not in raw_df.columns]
if missing:
    st.error(f"필수 컬럼 누락: {missing}")
    st.stop()

df = raw_df.copy()
df["날짜_dt"] = df["날짜"].apply(parse_date8)
df["연"] = pd.to_numeric(df["연"], errors="coerce").astype("Int64")
df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")
df["요일"] = df["요일"].astype(str).str.strip()
df["공휴일여부"] = df["공휴일여부"].astype(str).str.upper().isin(["TRUE","T","1","Y","YES"])
df["공급량(MJ)"] = df["공급량(MJ)"].apply(to_float_num)

# 카테고리(요일/공휴일) 만들기 — 합계 100% 보장
# split_holiday=True면 공휴일은 '공휴일'로, 아니면 원래 요일에 귀속
def build_category(row):
    if split_holiday and row["공휴일여부"]:
        return "공휴일"
    return row["요일"]

df["카테고리"] = df.apply(build_category, axis=1)

# ─────────────────────────────────────────────────────────────
# 월별 총공급량 대비 카테고리 비중 계산
# ─────────────────────────────────────────────────────────────
# 월 총공급량
m_total = df.groupby(["연","월"], dropna=False)["공급량(MJ)"].sum().rename("월총공급량")
# 선택 카테고리 공급량
m_cat = df.groupby(["연","월","카테고리"], dropna=False)["공급량(MJ)"].sum().rename("카테고리공급량").reset_index()
m = m_cat.merge(m_total, on=["연","월"], how="left")
m["비중(%)"] = np.where(m["월총공급량"]>0, m["카테고리공급량"]/m["월총공급량"]*100, np.nan)

# 선택 UI
years_all = [int(y) for y in sorted(m["연"].dropna().unique())]
weekday_order = ["월","화","수","목","금","토","일"] + (["공휴일"] if split_holiday else [])
cats_all = [c for c in weekday_order if c in m["카테고리"].unique()]

c1, c2 = st.columns([1,2])
with c1:
    sel_years = st.multiselect("연도 선택", years_all, default=years_all)
with c2:
    sel_cats = st.multiselect("요일/공휴일 선택", cats_all, default=["금"] if "금" in cats_all else cats_all)

m_sel = m[(m["연"].isin(sel_years)) & (m["카테고리"].isin(sel_cats))].copy()

st.markdown(
    f"**용어 확인** — 본 화면의 ‘비중’은 *월별 총공급량 대비* **선택된 요일/공휴일의 공급량 비중(%)**을 뜻함."
)

st.divider()

# ─────────────────────────────────────────────────────────────
# 1) 히트맵(금요일 기본) — 연(행)×월(열)
# ─────────────────────────────────────────────────────────────
default_for_heatmap = "금" if "금" in cats_all else cats_all[0]
target_cat = st.selectbox("히트맵에 볼 카테고리(요일/공휴일)", options=cats_all, index=cats_all.index(default_for_heatmap))

hm = m[(m["카테고리"]==target_cat) & (m["연"].isin(sel_years))].copy()
pivot = hm.pivot_table(index="연", columns="월", values="비중(%)", aggfunc="mean")
pivot = pivot.reindex(index=sorted(pivot.index), columns=range(1,13))

st.subheader(f"🧊 연·월 히트맵 — **{target_cat} 공급량 비중(%)**")
fig_hm = px.imshow(
    pivot.values,
    x=list(range(1,13)), y=[int(i) for i in pivot.index],
    color_continuous_scale="Viridis",
    origin="upper",
    labels=dict(color="비중(%)", x="월", y="연"),
)
# 중앙값 라벨 표시
text_vals = np.where(np.isnan(pivot.values), "", np.vectorize(lambda v: f"{v:.1f}")(pivot.values))
fig_hm.update_traces(text=text_vals, texttemplate="%{text}", textfont=dict(size=10))
fig_hm.update_layout(margin=dict(l=40,r=20,t=20,b=40), coloraxis_colorbar=dict(title="비중(%)"), font=dict(family="Noto Sans KR, Nanum Gothic, Malgun Gothic"))
st.plotly_chart(fig_hm, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 2) 선택 카테고리 간 월별 비중 비교(막대)
# ─────────────────────────────────────────────────────────────
st.subheader("📦 선택 카테고리 월별 비중(%) 비교")
bar_df = m_sel.groupby(["연","월","카테고리"], as_index=False)["비중(%)"].mean()
bar_df["연월"] = bar_df["연"].astype(int).astype(str) + "-" + bar_df["월"].astype(int).astype(str).str.zfill(2)
fig_bar = px.bar(bar_df, x="연월", y="비중(%)", color="카테고리", barmode="group",
                 labels={"연월":"연-월"}, hover_data=["연","월","카테고리","비중(%)"])
fig_bar.update_layout(xaxis_tickangle=-45, font=dict(family="Noto Sans KR, Nanum Gothic, Malgun Gothic"))
st.plotly_chart(fig_bar, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 3) 동적 추세선(선택 카테고리 합산 기준)
#    - 선택한 연도×월에서 선택 카테고리들의 비중을 합쳐 하나의 시계열로 보고
#      월 인덱스(연*12+월)에 대해 단순선형 추세선(OLS)을 overlay
# ─────────────────────────────────────────────────────────────
st.subheader("📈 동적 추세선 — 선택 카테고리 **합계 비중(%)**")
ts = m_sel.groupby(["연","월"], as_index=False)["비중(%)"].sum().sort_values(["연","월"])
# 시간 인덱스(연*12+월)로 회귀
ts["t"] = ts["연"].astype(int)*12 + ts["월"].astype(int)
if len(ts) >= 3:
    coef = np.polyfit(ts["t"], ts["비중(%)"], 1)  # y = a t + b
    ts["추세선"] = coef[0]*ts["t"] + coef[1]
else:
    ts["추세선"] = np.nan

ts["연월"] = ts["연"].astype(int).astype(str) + "-" + ts["월"].astype(int).astype(str).str.zfill(2)
fig_ts = go.Figure()
fig_ts.add_traces([
    go.Scatter(x=ts["연월"], y=ts["비중(%)"], mode="lines+markers", name="합계 비중(%)"),
    go.Scatter(x=ts["연월"], y=ts["추세선"], mode="lines", name="선형 추세선", line=dict(dash="dash"))
])
fig_ts.update_layout(xaxis_title="연-월", yaxis_title="비중(%)", font=dict(family="Noto Sans KR, Nanum Gothic, Malgun Gothic"))
st.plotly_chart(fig_ts, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 4) 금요일 요약 카드(빠른 진단)
# ─────────────────────────────────────────────────────────────
fri_key = "금" if "금" in cats_all else (cats_all[0] if cats_all else None)
if fri_key is not None:
    fm = m[(m["카테고리"]==fri_key) & (m["연"].isin(sel_years))].copy()
    mean_fri = fm["비중(%)"].mean()
    med_fri = fm["비중(%)"].median()
    st.markdown("### 🧭 금요일 비중 요약")
    c1, c2, c3 = st.columns(3)
    c1.metric(f"금요일 평균 비중(%)", f"{mean_fri:,.2f}")
    c2.metric(f"금요일 중앙값(%)", f"{med_fri:,.2f}")
    c3.metric("현 설정(연도·분리규칙)", "적용 중")

# ─────────────────────────────────────────────────────────────
# 5) 상세 테이블 + 다운로드
# ─────────────────────────────────────────────────────────────
st.subheader("📄 상세 테이블(연·월·카테고리)")
table = m_sel.sort_values(["연","월","카테고리"]).copy()
st.dataframe(
    table[["연","월","카테고리","월총공급량","카테고리공급량","비중(%)"]]
        .style.format({"월총공급량":"{:,.0f}","카테고리공급량":"{:,.0f}","비중(%)":"{:.2f}"}),
    use_container_width=True
)
st.download_button(
    "CSV 다운로드(현재 선택)",
    data=table.to_csv(index=False, encoding="utf-8-sig"),
    file_name="weekday_holiday_share.csv",
    mime="text/csv"
)

with st.expander("계산 전제/해석 팁"):
    st.markdown("""
- **비중(%)** = (해당 월에서 *선택한 카테고리*의 공급량 합 ÷ *해당 월 총공급량*) × 100  
- **공휴일 분리=예**: 공휴일은 ‘공휴일’ 카테고리에만 들어가고, 요일(월~일)에서 제외 → 합계 100%가 정확히 맞음.  
- **공휴일 분리=아니오**: 공휴일이 해당 요일(월~일)에 포함됨 → ‘공휴일’ 카테고리는 없음.  
- ‘금요일 공급량 비중’은 금요일 카테고리의 비중(%)을 의미함.
""")
