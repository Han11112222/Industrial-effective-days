# app.py — 금요일 공급량 비중 추세 분석 (GitHub raw/XLSX 지원)
# - 깃허브 raw URL로 엑셀 로딩
# - 월별 총공급량 대비 '금요일 공급비중(%)' 계산
# - 연도 선택/공휴일 포함여부 옵션
# - 히트맵 + 라인그래프 + 연도별 기울기(추세) 제공

import io
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from urllib.parse import urlparse

st.set_page_config(page_title="금요일 공급량 비중 추세", layout="wide")
st.title("📉 금요일 공급량 비중 추세 분석")
st.caption("월별 총공급량 대비 '금요일' 공급량 비중(%)을 연·월·요일 기준으로 산출해 추세를 확인")

# ─────────────────────────────────────────────────────────────
# Sidebar — 입력
# ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    raw_url = st.text_input(
        "GitHub raw 파일 URL (xlsx/csv)",
        value="https://raw.githubusercontent.com/<your-org-or-id>/<repo>/main/effective_days_calendar.xlsx",
        help="깃허브 파일 페이지에서 'Raw' 버튼을 눌러 나온 주소를 붙여넣어"
    )
    include_holiday = st.checkbox("공휴일 포함(금요일이 공휴일이어도 포함)", value=False)
    st.caption("※ 미체크 시, 금요일이 공휴일인 날은 금요일 집계에서 제외")

# ─────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_data_from_github(url: str) -> pd.DataFrame:
    """
    GitHub raw URL에서 xlsx 또는 csv를 읽어 DataFrame 반환.
    """
    parsed = urlparse(url)
    if "raw.githubusercontent.com" not in parsed.netloc:
        raise ValueError("raw.githubusercontent.com URL을 넣어줘")

    if url.lower().endswith(".xlsx") or url.lower().endswith(".xls"):
        df = pd.read_excel(url, engine="openpyxl")
    elif url.lower().endswith(".csv"):
        # 한글/쉼표 가능성: encoding='cp949' 시도 후 utf-8로 폴백
        try:
            df = pd.read_csv(url, encoding="cp949")
        except:
            df = pd.read_csv(url, encoding="utf-8")
    else:
        raise ValueError("지원 확장자: .xlsx, .xls, .csv")

    return df

def to_numeric_maybe_comma(x):
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.number)):
        return x
    s = str(x)
    s = s.replace(",", "")  # "223,034,735" → "223034735"
    # 한국어 엑셀에서 소수점은 '.' 가정
    try:
        return float(s)
    except:
        return np.nan

# 요일 정렬 유지용
WEEK_ORDER = ["월","화","수","목","금","토","일"]

# ─────────────────────────────────────────────────────────────
# Load
# ─────────────────────────────────────────────────────────────
try:
    df = load_data_from_github(raw_url)
    st.success("데이터 로딩 완료")
except Exception as e:
    st.error(f"데이터 로딩 실패: {e}")
    st.stop()

# ─────────────────────────────────────────────────────────────
# 컬럼 표준화 (필요 컬럼: 날짜, 연, 월, 요일, 공휴일여부, 공급량(MJ))
# ─────────────────────────────────────────────────────────────
col_map = {c.strip(): c.strip() for c in df.columns}
df.columns = list(col_map.keys())

required = ["날짜","연","월","요일","공휴일여부","공급량(MJ)"]
missing = [c for c in required if c not in df.columns]
if missing:
    st.error(f"필수 컬럼 누락: {missing}")
    st.stop()

# 날짜 파싱
# 날짜가 'YYYYMMDD' 또는 'YYYY-MM-DD'로 온다고 가정
def parse_date(x):
    s = str(x)
    s = s.strip()
    if re.fullmatch(r"\d{8}", s):
        return pd.to_datetime(s, format="%Y%m%d")
    else:
        return pd.to_datetime(s, errors="coerce")

df["날짜_dt"] = df["날짜"].apply(parse_date)
if df["날짜_dt"].isna().all():
    st.error("날짜 컬럼 파싱 실패(형식 점검 필요)")
    st.stop()

# 숫자 변환
df["연"] = pd.to_numeric(df["연"], errors="coerce").astype("Int64")
df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")
df["공급량(MJ)"] = df["공급량(MJ)"].apply(to_numeric_maybe_comma)

# 요일/공휴일 정리
df["요일"] = df["요일"].astype(str).str.strip()
df["공휴일여부"] = df["공휴일여부"].astype(str).str.upper().isin(["TRUE","1","T","Y","YES"])

# 금요일 필터에서 공휴일 제외 옵션
if include_holiday:
    is_fri = (df["요일"] == "금")
else:
    is_fri = (df["요일"] == "금") & (~df["공휴일여부"])

# ─────────────────────────────────────────────────────────────
# 월별 총공급량 & 금요일 공급량
# ─────────────────────────────────────────────────────────────
grp_total = df.groupby(["연","월"], dropna=False)["공급량(MJ)"].sum().rename("월총공급량")
grp_fri   = df[is_fri].groupby(["연","월"], dropna=False)["공급량(MJ)"].sum().rename("금요일공급량")

merged = pd.concat([grp_total, grp_fri], axis=1).fillna(0.0).reset_index()
merged["금요일비중(%)"] = np.where(merged["월총공급량"]>0,
                                merged["금요일공급량"]/merged["월총공급량"]*100, np.nan)

# 연도 선택
years_all = [int(y) for y in sorted(merged["연"].dropna().unique())]
with st.sidebar:
    sel_years = st.multiselect("연도 선택", options=years_all, default=years_all)
    st.caption("선택한 연도만 시각화/집계에 반영")

view = merged[merged["연"].isin(sel_years)].copy()

# ─────────────────────────────────────────────────────────────
# 요약 카드(선택연도 전체)
# ─────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
overall_mean = view["금요일비중(%)"].mean(skipna=True)
overall_median = view["금요일비중(%)"].median(skipna=True)
n_months = view["금요일비중(%)"].notna().sum()
col1.metric("평균 금요일 비중(%)", f"{overall_mean:,.2f}")
col2.metric("중앙값(%)", f"{overall_median:,.2f}")
col3.metric("분석 월 수", f"{n_months}")

st.markdown("---")

# ─────────────────────────────────────────────────────────────
# (1) 히트맵: 연(행) × 월(열) 금요일 비중
# ─────────────────────────────────────────────────────────────
pivot = view.pivot_table(index="연", columns="월", values="금요일비중(%)", aggfunc="mean")
pivot = pivot.reindex(index=sorted(pivot.index), columns=range(1,13))  # 월 1~12 정렬

st.subheader("🧊 연·월 히트맵 (금요일 비중 %)")
fig_hm, ax = plt.subplots(figsize=(12, max(2.5, 0.35*len(pivot.index))))
im = ax.imshow(pivot.values, aspect="auto")
ax.set_yticks(range(len(pivot.index))); ax.set_yticklabels(pivot.index)
ax.set_xticks(range(12)); ax.set_xticklabels(range(1,13))
ax.set_xlabel("월"); ax.set_ylabel("연")
# 값 주석
for i in range(pivot.shape[0]):
    for j in range(pivot.shape[1]):
        v = pivot.values[i,j]
        if pd.notna(v):
            ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=9)
cbar = fig_hm.colorbar(im, ax=ax)
cbar.set_label("금요일 비중(%)")
st.pyplot(fig_hm)
st.caption("색이 옅어지거나 값이 낮아지는 연·월 구간이 누적되면 금요일 비중이 하락 추세일 가능성이 큼")

# ─────────────────────────────────────────────────────────────
# (2) 라인 그래프: 연도별 월 금요일 비중
# ─────────────────────────────────────────────────────────────
st.subheader("📈 연도별 월 금요일 비중(%)")
fig_ln, ax2 = plt.subplots(figsize=(12,4))
for y in sorted(view["연"].unique()):
    s = view[view["연"]==y].sort_values("월")
    ax2.plot(s["월"], s["금요일비중(%)"], marker="o", label=str(int(y)))
ax2.set_xlabel("월"); ax2.set_ylabel("금요일 비중(%)")
ax2.set_xticks(range(1,13))
ax2.grid(True, alpha=0.3)
ax2.legend(ncol=6, fontsize=8, frameon=False)
st.pyplot(fig_ln)

# ─────────────────────────────────────────────────────────────
# (3) 연도별 추세 기울기 (단순선형회귀)
# ─────────────────────────────────────────────────────────────
rows = []
for y in sorted(view["연"].unique()):
    s = view[view["연"]==y].dropna(subset=["월","금요일비중(%)"]).sort_values("월")
    if len(s)>=3:
        # x=월(1~12), y=비중(%)
        x = s["월"].to_numpy()
        yv = s["금요일비중(%)"].to_numpy()
        # 최소제곱 직선 y = a*x + b
        a = np.polyfit(x, yv, 1)[0]
        rows.append({"연": int(y), "월-기울기(pp/월)": a, "연간변화추정(pp/년)": a*11})
trend_df = pd.DataFrame(rows)
st.subheader("📉 연도별 금요일 비중 추세(기울기)")
st.dataframe(trend_df.style.format({"월-기울기(pp/월)":"{:.3f}", "연간변화추정(pp/년)":"{:.2f}"}), use_container_width=True)
st.caption("연간변화추정은 월 기울기에 11을 곱한 근사(1→12월). 음수면 하락 추세로 해석")

# ─────────────────────────────────────────────────────────────
# (4) 상세 테이블 & 다운로드
# ─────────────────────────────────────────────────────────────
st.subheader("📄 월별 금요일 비중(%) 상세")
show = view.sort_values(["연","월"]).copy()
st.dataframe(show.style.format({"월총공급량":"{:,.0f}","금요일공급량":"{:,.0f}","금요일비중(%)":"{:.2f}"}), use_container_width=True)

csv = show.to_csv(index=False, encoding="utf-8-sig")
st.download_button("CSV 다운로드 (선택연도)", data=csv, file_name="friday_share_by_month.csv", mime="text/csv")

# 주의/전제
with st.expander("데이터/계산 전제"):
    st.markdown("""
- '금요일' 판정은 `요일=='금'` 기준이며, **공휴일 제외 옵션**이 꺼져 있으면 공휴일 금요일도 포함됨.
- 월총공급량은 해당 월 모든 일자 합(공휴일 포함).
- 공급량은 쉼표 제거 후 실수형으로 변환해 합산.
- 히트맵 값은 **월별 금요일 비중의 평균(선택연도)**.
""")
