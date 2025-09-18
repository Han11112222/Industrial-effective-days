# app.py — 요일/공휴일 공급량 비중(%) 분석 (오류 수정판)
# - GitHub raw XLSX/CSV 로딩(blob → raw 자동 변환)
# - 월 총공급량 대비 요일/공휴일 공급량 비중(%)  =  (해당 카테고리 공급량 ÷ 월 총공급량)×100
# - 연도 선택(사이드바), 요일/공휴일 멀티선택
# - 히트맵(크게), 100% 누적 막대(연간 구조 변화), 요일별 추세선(빈 달/미래연도 제거)
# - 하단 자동 요약/결론

import re
from urllib.parse import urlparse
import numpy as np
import pandas as pd
import requests
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="요일/공휴일 공급량 비중 분석", layout="wide")

st.title("📊 월별 총공급량 대비 요일·공휴일 **공급량 비중(%)**")
st.caption("※ ‘공급량 비중’은 월 총공급량에서 선택된 요일/공휴일이 차지하는 비중(%)을 의미")

# ───────────────────────────
# Sidebar
# ───────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    raw_url = st.text_input(
        "GitHub raw 파일 URL (xlsx/csv)",
        value="https://raw.githubusercontent.com/Han11112222/Industrial-effective-days/main/effective_days_calendar.xlsx",
        help="파일 페이지의 Raw 주소. blob 주소를 넣어도 자동 변환됨."
    )
    split_holiday = st.radio(
        "공휴일을 별도 카테고리로 분리(합계 100%)",
        options=["예(권장)","아니오(해당 요일에 포함)"], index=0, horizontal=True
    ) == "예(권장)"

# ───────────────────────────
# Utils
# ───────────────────────────
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
        raise ValueError("GitHub raw URL이 아님")

    h = requests.head(url, timeout=10)
    if h.status_code == 404:
        raise FileNotFoundError("HTTP 404 — 브랜치/경로/파일명 확인")
    h.raise_for_status()

    if url.lower().endswith((".xlsx",".xls")):
        import openpyxl  # noqa: F401
        df = pd.read_excel(url, engine="openpyxl")
    elif url.lower().endswith(".csv"):
        try: df = pd.read_csv(url, encoding="cp949")
        except: df = pd.read_csv(url, encoding="utf-8")
    else:
        raise ValueError("지원 확장자: .xlsx, .xls, .csv")
    return df

def to_float(x):
    if pd.isna(x): return np.nan
    if isinstance(x, (int,float,np.number)): return float(x)
    return float(str(x).replace(",",""))

def parse_date8(s):
    s = str(s).strip()
    if re.fullmatch(r"\d{8}", s):
        return pd.to_datetime(s, format="%Y%m%d")
    return pd.to_datetime(s, errors="coerce")

# ───────────────────────────
# Load & normalize
# ───────────────────────────
try:
    raw = load_df(raw_url)
    st.success("데이터 로딩 완료")
except Exception as e:
    st.error(f"데이터 로딩 실패: {e}")
    st.stop()

need = ["날짜","연","월","요일","공휴일여부","공급량(MJ)"]
missing = [c for c in need if c not in raw.columns]
if missing:
    st.error(f"필수 컬럼 누락: {missing}")
    st.stop()

df = raw.copy()
df["날짜_dt"] = df["날짜"].apply(parse_date8)
df["연"] = pd.to_numeric(df["연"], errors="coerce").astype("Int64")
df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")
df["요일"] = df["요일"].astype(str).str.strip()
df["공휴일여부"] = df["공휴일여부"].astype(str).str.upper().isin(["TRUE","T","1","Y","YES"])
df["공급량(MJ)"] = df["공급량(MJ)"].apply(to_float)

def cat_fn(r):
    if split_holiday and r["공휴일여부"]:
        return "공휴일"
    return r["요일"]
df["카테고리"] = df.apply(cat_fn, axis=1)

# 월 총공급량, 카테고리 공급량
m_total = df.groupby(["연","월"], dropna=False)["공급량(MJ)"].sum().rename("월총공급량")
m_cat = df.groupby(["연","월","카테고리"], dropna=False)["공급량(MJ)"].sum().rename("카테고리공급량").reset_index()
m = m_cat.merge(m_total, on=["연","월"], how="left")
# **빈 달/미래연도 제거**: 월총공급량>0만 유지
m = m[m["월총공급량"] > 0].copy()
m["비중(%)"] = m["카테고리공급량"] / m["월총공급량"] * 100

# 사이드바 연도 선택
valid_years = [int(y) for y in sorted(m["연"].dropna().unique())]
with st.sidebar:
    sel_years = st.multiselect("연도 선택", options=valid_years, default=valid_years)

weekday_order = ["월","화","수","목","금","토","일"] + (["공휴일"] if "공휴일" in m["카테고리"].unique() else [])
cats_all = [c for c in weekday_order if c in m["카테고리"].unique()]
st.caption("**용어 확인** — ‘비중’은 *월 총공급량 대비* **선택된 요일/공휴일의 공급량 비중(%)**")

view = m[m["연"].isin(sel_years)].copy()

st.divider()

# ───────────────────────────
# 1) 히트맵 (크게) — 특정 카테고리
# ───────────────────────────
default_cat = "금" if "금" in cats_all else cats_all[0]
target_cat = st.selectbox("히트맵에 볼 카테고리", options=cats_all, index=cats_all.index(default_cat))

hm = view[view["카테고리"] == target_cat]
pivot = hm.pivot_table(index="연", columns="월", values="비중(%)", aggfunc="mean").reindex(
    index=sorted(hm["연"].unique()), columns=range(1,13)
)

# ───────────────────────────
# 2) 연도별 구조 변화 — 100% 누적 막대 (전체 카테고리)  ← 교체본
# ───────────────────────────
st.subheader("🧱 연도별 구조 변화 — 모든 요일/공휴일 **연간 평균 비중(%)** (100% 기준)")

# 1) 연·카테고리 평균 비중 집계
year_cat = view.groupby(["연","카테고리"], as_index=False)["비중(%)"].mean()

# 2) 연도별로 합이 100이 되도록 정규화 (barnorm 사용 안 함)
norm = (
    year_cat
    .groupby("연", as_index=False)["비중(%)"].sum()
    .rename(columns={"비중(%)":"합계"})
)
year_cat = year_cat.merge(norm, on="연", how="left")
year_cat["연간 정규화(%)"] = np.where(year_cat["합계"]>0,
                                  year_cat["비중(%)"] / year_cat["합계"] * 100, 0.0)

# 3) 요일 순서 정렬(있을 때만)
weekday_order = ["월","화","수","목","금","토","일","공휴일"]
cats_in = [c for c in weekday_order if c in year_cat["카테고리"].unique()]
year_cat["카테고리"] = pd.Categorical(year_cat["카테고리"], categories=cats_in, ordered=True)
year_cat = year_cat.sort_values(["연","카테고리"])

# 4) 100% 누적 막대 (stack)
fig_stack = px.bar(
    year_cat, x="연", y="연간 정규화(%)", color="카테고리",
    labels={"연":"연도","연간 정규화(%)":"연 평균 비중(%)"},
)
fig_stack.update_layout(
    barmode="stack",  # 누적
    yaxis=dict(range=[0, 100]),
    margin=dict(l=30,r=20,t=10,b=40),
    xaxis=dict(type="category"),
    font=dict(family="Noto Sans KR, Nanum Gothic, Malgun Gothic")
)
st.plotly_chart(fig_stack, use_container_width=True)

st.divider()

# ───────────────────────────
# 2) 연도별 구조 변화 — 100% 누적 막대 (전체 카테고리)
# ───────────────────────────
st.subheader("🧱 연도별 구조 변화 — 모든 요일/공휴일 **연간 평균 비중(%)** (100% 기준)")
year_cat = view.groupby(["연","카테고리"], as_index=False)["비중(%)"].mean()
fig_stack = px.bar(
    year_cat, x="연", y="비중(%)", color="카테고리", barnorm="percent",
    labels={"연":"연도","비중(%)":"연 평균 비중(%)"},
)
fig_stack.update_layout(margin=dict(l=30,r=20,t=10,b=40), xaxis=dict(type="category"),
                        font=dict(family="Noto Sans KR, Nanum Gothic, Malgun Gothic"))
st.plotly_chart(fig_stack, use_container_width=True)

st.divider()

# ───────────────────────────
# 3) 요일/공휴일별 추세선 (빈 달 제거)
# ───────────────────────────
st.subheader("📈 요일/공휴일별 동적 추세선 — 월별 비중(%)")
sel_cats = st.multiselect("비교할 카테고리 선택", options=cats_all,
                          default=["금"] if "금" in cats_all else cats_all[:2])

ts = view[view["카테고리"].isin(sel_cats)].copy()
ts["t"] = ts["연"].astype(int)*12 + ts["월"].astype(int)
ts = ts.sort_values(["카테고리","연","월"])

fig_ts = go.Figure()
summary_rows = []
for c in sel_cats:
    s = ts[ts["카테고리"]==c].dropna(subset=["비중(%)"])
    s = s[(s["월총공급량"]>0)]
    s["연월"] = s["연"].astype(int).astype(str) + "-" + s["월"].astype(int).astype(str).str.zfill(2)
    fig_ts.add_trace(go.Scatter(x=s["연월"], y=s["비중(%)"], mode="lines+markers", name=f"{c}"))
    if len(s) >= 3:
        a, b = np.polyfit(s["t"], s["비중(%)"], 1)  # y=a*t+b
        trend = a*s["t"] + b
        fig_ts.add_trace(go.Scatter(x=s["연월"], y=trend, mode="lines",
                                    name=f"{c} 추세", line=dict(dash="dash")))
        slope_year = a*12  # 월 단위 계수 → 연 단위 p.p./년
        s["연_int"] = s["연"].astype(int)
        early = s[s["연_int"] <= s["연_int"].min()+2]["비중(%)"].mean()
        late  = s[s["연_int"] >= s["연_int"].max()-2]["비중(%)"].mean()
        summary_rows.append({"카테고리": c,
                             "연간 기울기(pp/년)": float(slope_year),
                             "초기3년→최근3년 변화(pp)": float(late - early)})

fig_ts.update_layout(xaxis_title="연-월", yaxis_title="비중(%)",
                     font=dict(family="Noto Sans KR, Nanum Gothic, Malgun Gothic"),
                     legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
st.plotly_chart(fig_ts, use_container_width=True)

# ───────────────────────────
# 4) 상세/다운로드
# ───────────────────────────
st.subheader("📄 상세 테이블(연·월·카테고리)")
table = view.sort_values(["연","월","카테고리"]).copy()
st.dataframe(
    table[["연","월","카테고리","월총공급량","카테고리공급량","비중(%)"]]
        .style.format({"월총공급량":"{:,.0f}","카테고리공급량":"{:,.0f}","비중(%)":"{:.2f}"}),
    use_container_width=True
)
st.download_button("CSV 다운로드(현재 보기)", data=table.to_csv(index=False, encoding="utf-8-sig"),
                   file_name="weekday_holiday_share_monthly.csv", mime="text/csv")

st.divider()

# ───────────────────────────
# 5) 자동 요약/결론  (⬅️ 오류났던 부분 깔끔히 교체)
# ───────────────────────────
st.subheader("🧭 요약 및 결론")
txts = []

# (a) 금요일 중심 요약
if "금" in m["카테고리"].unique():
    s = view[view["카테고리"]=="금"]
    if not s.empty:
        yavg = s.groupby("연")["비중(%)"].mean()
        if len(yavg)>=2:
            first3 = yavg.sort_index().iloc[:min(3,len(yavg))].mean()
            last3  = yavg.sort_index().iloc[-min(3,len(yavg)) :].mean()
            diff = last3 - first3
            direction = "감소" if diff < 0 else "증가"
            txts.append(f"- **금요일 연평균 비중**: 초기 3년 대비 최근 3년 {abs(diff):.2f}p.p. **{direction}**")

# (b) 전체 구조 변화(연 평균, 최근 vs 초기)
year_cat_all = view.groupby(["연","카테고리"], as_index=False)["비중(%)"].mean()
weekday_order2 = [c for c in weekday_order if c in year_cat_all["카테고리"].unique()]
summary_change = []
for c in weekday_order2:
    s = year_cat_all[year_cat_all["카테고리"]==c].sort_values("연")
    if len(s)>=2:
        early = s["비중(%)"].iloc[:min(3,len(s))].mean()
        late  = s["비중(%)"].iloc[-min(3,len(s)) :].mean()
        summary_change.append((c, late-early))
if summary_change:
    summary_change.sort(key=lambda x: x[1], reverse=True)
    inc = [f"{c} (+{d:.2f}p)" for c,d in summary_change if d>0]
    dec = [f"{c} ({d:.2f}p)" for c,d in summary_change if d<0]
    if inc: txts.append("- **비중이 늘어난 요일/공휴일**: " + ", ".join(inc))
    if dec: txts.append("- **비중이 줄어든 요일/공휴일**: " + ", ".join(dec))

# (c) 추세선 요약(선택 카테고리)
if summary_rows:
    sr = pd.DataFrame(summary_rows).sort_values("연간 기울기(pp/년)", ascending=False)
    inc_line = f"- **추세선 증가 1위**: {sr.iloc[0]['카테고리']} (기울기 {sr.iloc[0]['연간 기울기(pp/년)']:.2f}p/년, 최근-초기 {sr.iloc[0]['초기3년→최근3년 변화(pp)']:.2f}p)"
    dec_line = f"- **추세선 감소 1위**: {sr.iloc[-1]['카테고리']} (기울기 {sr.iloc[-1]['연간 기울기(pp/년)']:.2f}p/년, 최근-초기 {sr.iloc[-1]['초기3년→최근3년 변화(pp)']:.2f}p)"
    txts.extend([inc_line, dec_line])

if not txts:
    txts = ["- 선택된 구간에서 뚜렷한 구조 변화 신호가 약함(연도/요일 선택을 바꿔 확인)."]

st.markdown("\n".join(txts))
