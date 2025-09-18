# app.py — 도시가스 산업용: 금요일/요일·공휴일 비중 추세 분석 (GitHub raw 지원)

import io, re
from urllib.parse import urlparse
import requests
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────
# 기본 세팅 (한글 폰트/마이너스 표시)
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="금요일/요일·공휴일 비중 추세", layout="wide")

mpl.rcParams["font.family"] = ["Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"]
mpl.rcParams["axes.unicode_minus"] = False

st.title("📊 월별 **총공급량 대비 금요일 공급량 비중(%)** · 요일·공휴일 구성(%)")
st.caption("월별 총공급량을 100으로 보고, 금요일/요일·공휴일이 차지하는 **공급량 비중(%)**을 계산합니다.")

# ─────────────────────────────────────────────────────────────
# Sidebar — 입력
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    raw_url = st.text_input(
        "GitHub raw 파일 URL (xlsx/csv)",
        value="https://raw.githubusercontent.com/Han11112222/Industrial-effective-days/main/effective_days_calendar.xlsx",
        help="파일 페이지에서 Raw 버튼 주소를 붙여넣어. blob 주소여도 자동 변환됨."
    )
    include_fri_holiday = st.checkbox("금요일 집계에 공휴일 포함", value=False,
                                      help="끄면 공휴일인 금요일은 금요일 집계에서 제외")
    st.markdown("---")
    st.caption("※ 요일·공휴일 구성은 **‘공휴일’이 True면 요일 대신 ‘공휴일’로 분리**하여 총합이 100%가 되도록 처리")

# ─────────────────────────────────────────────────────────────
# 유틸
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
def load_data_from_github(url: str) -> pd.DataFrame:
    url = normalize_github_url(url)
    parsed = urlparse(url)
    if "raw.githubusercontent.com" not in parsed.netloc:
        raise ValueError("GitHub raw URL이 아님: Raw 주소를 넣어줘.")
    h = requests.head(url, timeout=10)
    if h.status_code == 404:
        raise FileNotFoundError("HTTP 404 — 브랜치/경로/파일명(대소문자) 확인")
    h.raise_for_status()
    if url.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(url, engine="openpyxl")
    elif url.lower().endswith(".csv"):
        try:
            df = pd.read_csv(url, encoding="cp949")
        except:
            df = pd.read_csv(url, encoding="utf-8")
    else:
        raise ValueError("지원: .xlsx/.xls/.csv")
    return df

def to_numeric_maybe_comma(x):
    if pd.isna(x): return np.nan
    if isinstance(x, (int, float, np.number)): return float(x)
    s = str(x).replace(",", "")
    try: return float(s)
    except: return np.nan

def parse_date(x):
    s = str(x).strip()
    if re.fullmatch(r"\d{8}", s):
        return pd.to_datetime(s, format="%Y%m%d")
    else:
        return pd.to_datetime(s, errors="coerce")

# ─────────────────────────────────────────────────────────────
# Load & 표준화
# ─────────────────────────────────────────────────────────────
try:
    df = load_data_from_github(raw_url)
    st.success("데이터 로딩 완료")
except Exception as e:
    st.error(f"데이터 로딩 실패: {e}")
    st.stop()

need = ["날짜","연","월","요일","공휴일여부","공급량(MJ)"]
miss = [c for c in need if c not in df.columns]
if miss:
    st.error(f"필수 컬럼 누락: {miss}")
    st.stop()

df["날짜_dt"] = df["날짜"].apply(parse_date)
df["연"] = pd.to_numeric(df["연"], errors="coerce").astype("Int64")
df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")
df["요일"] = df["요일"].astype(str).str.strip()
df["공휴일여부"] = df["공휴일여부"].astype(str).str.upper().isin(["TRUE","1","T","Y","YES"])
df["공급량(MJ)"] = df["공급량(MJ)"].apply(to_numeric_maybe_comma)

# ─────────────────────────────────────────────────────────────
# 금요일 비중(%) — 월 총공급량 대비 금요일 공급량
# ─────────────────────────────────────────────────────────────
is_fri = (df["요일"]=="금")
if not include_fri_holiday:
    is_fri = is_fri & (~df["공휴일여부"])

month_total = df.groupby(["연","월"], dropna=False)["공급량(MJ)"].sum().rename("월총공급량")
fri_sum     = df[is_fri].groupby(["연","월"], dropna=False)["공급량(MJ)"].sum().rename("금요일공급량")
fri_merge = pd.concat([month_total, fri_sum], axis=1).fillna(0.0).reset_index()
fri_merge["금요일비중(%)"] = np.where(fri_merge["월총공급량"]>0,
                                   fri_merge["금요일공급량"]/fri_merge["월총공급량"]*100, np.nan)

years_all = [int(y) for y in sorted(fri_merge["연"].dropna().unique())]

# ─────────────────────────────────────────────────────────────
# 요일·공휴일 구성(%) — 총합 100% 보장
#  - 공휴일이면 '공휴일', 아니면 실제 요일(월~일)
# ─────────────────────────────────────────────────────────────
df["구성카테고리"] = np.where(df["공휴일여부"], "공휴일", df["요일"])

comp = df.groupby(["연","월","구성카테고리"], dropna=False)["공급량(MJ)"].sum().reset_index()
comp = comp.merge(month_total.reset_index(), on=["연","월"], how="left")
comp["비중(%)"] = np.where(comp["월총공급량"]>0, comp["공급량(MJ)"]/comp["월총공급량"]*100, np.nan)

# 총합 확인용(표시는 하지 않아도 됨)
check_sum = comp.groupby(["연","월"])["비중(%)"].sum().round(6)
# st.write("합계 확인(100%):", check_sum.describe())

# ─────────────────────────────────────────────────────────────
# UI — 연도/카테고리 선택
# ─────────────────────────────────────────────────────────────
col_sel1, col_sel2 = st.columns([2,3])
with col_sel1:
    sel_years = st.multiselect("연도 선택", years_all, default=years_all)
with col_sel2:
    cats_all = ["월","화","수","목","금","토","일","공휴일"]
    sel_cats = st.multiselect("요일·공휴일 선택(비중 %)", cats_all, default=["금","공휴일"])

# 필터 적용
fri_view = fri_merge[fri_merge["연"].isin(sel_years)].copy()
comp_view = comp[(comp["연"].isin(sel_years)) & (comp["구성카테고리"].isin(sel_cats))].copy()

st.markdown("---")

# ─────────────────────────────────────────────────────────────
# [A] 히트맵(금요일 비중 %)
# ─────────────────────────────────────────────────────────────
st.subheader("🧊 연·월 히트맵 — **금요일 공급량 비중(%)**")
pivot = fri_view.pivot_table(index="연", columns="월", values="금요일비중(%)", aggfunc="mean")
pivot = pivot.reindex(index=sorted(pivot.index), columns=range(1,13))
fig_hm, ax = plt.subplots(figsize=(12, max(2.5, 0.35*len(pivot.index))))
im = ax.imshow(pivot.values, aspect="auto")
ax.set_yticks(range(len(pivot.index))); ax.set_yticklabels(pivot.index)
ax.set_xticks(range(12)); ax.set_xticklabels(range(1,13))
ax.set_xlabel("월"); ax.set_ylabel("연")
for i in range(pivot.shape[0]):
    for j in range(pivot.shape[1]):
        v = pivot.values[i,j]
        if pd.notna(v):
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=9)
cbar = fig_hm.colorbar(im, ax=ax); cbar.set_label("금요일 비중(%)")
st.pyplot(fig_hm)

# ─────────────────────────────────────────────────────────────
# [B] 연도별 월 금요일 비중 — 동적 라인(추세선 버튼 포함)
# ─────────────────────────────────────────────────────────────
st.subheader("📈 연도별 월 **금요일 공급량 비중(%)** — 동적 차트")
fri_line = fri_view.sort_values(["연","월"]).dropna(subset=["금요일비중(%)"]).copy()
fig = px.line(
    fri_line,
    x="월", y="금요일비중(%)", color=fri_line["연"].astype(str),
    markers=True, hover_data=["연","월","금요일공급량","월총공급량"],
)
fig.update_layout(legend_title_text="연도", xaxis=dict(dtick=1))
st.plotly_chart(fig, use_container_width=True)

# 추세선(연도별 단순선형회귀) — Plotly에 선 추가
rows = []
trend_fig = go.Figure()
for y in sorted(fri_line["연"].unique()):
    s = fri_line[fri_line["연"]==y]
    x = s["월"].to_numpy()
    yv = s["금요일비중(%)"].to_numpy()
    if len(s)>=3:
        a, b = np.polyfit(x, yv, 1)  # y=a*x+b
        yhat = a*x + b
        trend_fig.add_trace(go.Scatter(x=x, y=yhat, mode="lines",
                          name=f"{int(y)} 추세", line=dict(dash="dot")))
        rows.append({"연": int(y), "월-기울기(pp/월)": a, "연간변화추정(pp/년)": a*11})
trend_fig.update_layout(title="연도별 금요일 비중 추세선(선형)", xaxis=dict(dtick=1), yaxis_title="금요일 비중(%)")
st.plotly_chart(trend_fig, use_container_width=True)

if rows:
    trend_df = pd.DataFrame(rows)
    st.dataframe(trend_df.style.format({"월-기울기(pp/월)":"{:.3f}", "연간변화추정(pp/년)":"{:.2f}"}), use_container_width=True)

st.markdown("---")

# ─────────────────────────────────────────────────────────────
# [C] 요일·공휴일 구성(%) — 선택 카테고리 동적 차트
#   (총합 100% 보장: 공휴일은 요일과 분리된 독립 카테고리)
# ─────────────────────────────────────────────────────────────
st.subheader("🧩 월별 **요일·공휴일 공급량 비중(%)** — 선택 카테고리")
comp_line = comp_view.sort_values(["연","월","구성카테고리"]).copy()
fig2 = px.line(
    comp_line,
    x="월", y="비중(%)", color="구성카테고리", line_group="연",
    facet_row="연", markers=True, category_orders={"구성카테고리": ["월","화","수","목","금","토","일","공휴일"]}
)
fig2.update_layout(height=400 + 120*len(sel_years), xaxis=dict(dtick=1))
st.plotly_chart(fig2, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# [D] 상세 테이블 & 다운로드
# ─────────────────────────────────────────────────────────────
st.subheader("📄 상세 데이터")
col_a, col_b = st.columns(2)
with col_a:
    st.markdown("**금요일 비중(%) 상세**")
    show = fri_view.sort_values(["연","월"]).copy()
    st.dataframe(show.style.format({"월총공급량":"{:,.0f}","금요일공급량":"{:,.0f}","금요일비중(%)":"{:.2f}"}), use_container_width=True)
    st.download_button("CSV 다운로드 — 금요일 비중", data=show.to_csv(index=False, encoding="utf-8-sig"),
                       file_name="friday_share_by_month.csv", mime="text/csv")
with col_b:
    st.markdown("**요일·공휴일 비중(%) 상세**")
    comp_table = comp[(comp["연"].isin(sel_years))].pivot_table(
        index=["연","월"], columns="구성카테고리", values="비중(%)", aggfunc="sum"
    ).reindex(columns=cats_all + ["공휴일"]).fillna(0)
    st.dataframe(comp_table.style.format("{:.2f}"), use_container_width=True)
    st.download_button("CSV 다운로드 — 요일·공휴일 비중",
                       data=comp_table.reset_index().to_csv(index=False, encoding="utf-8-sig"),
                       file_name="weekday_holiday_share_by_month.csv", mime="text/csv")

with st.expander("계산 기준"):
    st.markdown("""
- **금요일 비중(%)** = (해당 월 금요일 공급량) ÷ (해당 월 총공급량) × 100  
- **요일·공휴일 비중(%)**: 공휴일이면 요일 대신 **‘공휴일’**로 분리해 합계를 100%로 강제  
- 금요일 비중 계산에서 공휴일 금요일 포함 여부는 사이드바 옵션으로 제어
""")
