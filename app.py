# app.py — 요일/공휴일 공급량 비중(%) 분석 (히트맵 우선/가로 버튼/CAGR 추가판)
# - GitHub raw XLSX/CSV 로딩(blob → raw 자동 변환)
# - 월 총공급량 대비 요일/공휴일 공급량 비중(%) 계산
# - 연도 선택(사이드바), 카테고리 가로형 버튼 선택
# - 시각화:
#   (1) 카테고리별 월별 히트맵(가장 먼저, 크게)
#   (2) 연간 평균 비중(%) 카테고리별 추세선(그래프 위 가로형 버튼으로 넣고/빼고)
# - 표:
#   (A) 월별 상세표(기존 유지)
#   (B) 최근 5년 CAGR & p.p. 변화(요일/공휴일별)
# - 빈 달/미래연도(월총공급량=0) 제거

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
st.caption("※ ‘공급량 비중’ = (해당 카테고리 공급량 ÷ 월 총공급량) × 100")

# ───────────────────────────
# Sidebar
# ───────────────────────────
with st.sidebar:
    st.header("⚙️ 설정")
    raw_url = st.text_input(
        "GitHub raw 파일 URL (xlsx/csv)",
        value="https://raw.githubusercontent.com/Han11112222/Industrial-effective-days/main/effective_days_calendar.xlsx",
        help="파일 페이지의 Raw 주소. blob 주소여도 자동 변환됨."
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

def ui_pills(label: str, options: list, default, multi=True):
    """
    최신 Streamlit이면 st.pills 사용, 아니면 multiselect로 폴백.
    multi=True면 다중선택, False면 단일선택(segmented처럼 동작).
    """
    try:
        # Streamlit >= 1.32
        if multi:
            return st.pills(label, options=options, selection_mode="multi", default=default)
        else:
            sel = st.pills(label, options=options, selection_mode="single", default=default)
            return sel
    except Exception:
        if multi:
            return st.multiselect(label, options=options, default=default)
        else:
            return st.selectbox(label, options=options, index=options.index(default))

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

# 연도/카테고리
weekday_order = ["월","화","수","목","금","토","일","공휴일"]
cats_all = [c for c in weekday_order if c in m["카테고리"].unique()]
valid_years = [int(y) for y in sorted(m["연"].dropna().unique())]

with st.sidebar:
    sel_years = st.multiselect("연도 선택", options=valid_years, default=valid_years)

st.caption("**용어 확인** — ‘비중’은 *월 총공급량 대비* **선택된 요일/공휴일의 공급량 비중(%)**")
view = m[m["연"].isin(sel_years)].copy()

st.divider()

# ───────────────────────────
# (1) 카테고리별 월별 히트맵 — 먼저 보여주기 + 가로 버튼
# ───────────────────────────
st.subheader("🧊 월별 히트맵 — 카테고리 선택")
default_cat = "금" if "금" in cats_all else cats_all[0]
target_cat = ui_pills("히트맵에 볼 카테고리", options=cats_all, default=default_cat, multi=False)

hm = view[view["카테고리"] == target_cat]
if hm.empty:
    st.info("선택된 연도/카테고리에 해당하는 데이터가 없습니다.")
else:
    pivot = hm.pivot_table(index="연", columns="월", values="비중(%)", aggfunc="mean")
    pivot = pivot.reindex(index=sorted(pivot.index), columns=range(1,13))
    heat_height = max(520, 44 * max(1, len(pivot.index)))
    fig_hm = px.imshow(
        pivot.values,
        x=list(range(1,13)), y=[int(i) for i in pivot.index],
        color_continuous_scale="Viridis", origin="upper",
        labels=dict(color="비중(%)", x="월", y="연"), height=heat_height
    )
    text_vals = np.where(np.isnan(pivot.values), "", np.vectorize(lambda v: f"{v:.1f}")(pivot.values))
    fig_hm.update_traces(text=text_vals, texttemplate="%{text}", textfont=dict(size=10))
    fig_hm.update_layout(margin=dict(l=50,r=20,t=10,b=40),
                         font=dict(family="Noto Sans KR, Nanum Gothic, Malgun Gothic"))
    st.plotly_chart(fig_hm, use_container_width=True)

st.divider()

# ───────────────────────────
# (2) 연간 평균 비중(%) — 카테고리별 추세선 (그래프 위 가로 버튼)
# ───────────────────────────
st.subheader("📈 연간 평균 비중(%) — 카테고리별 **추세선**")
year_cat = view.groupby(["연","카테고리"], as_index=False)["비중(%)"].mean()
year_cat["카테고리"] = pd.Categorical(year_cat["카테고리"], categories=cats_all, ordered=True)
year_cat = year_cat.sort_values(["카테고리","연"])

# 가로형 멀티 버튼
sel_cats_trend = ui_pills("표시할 카테고리(여러 개 선택 가능)", options=cats_all, default=cats_all, multi=True)

trend_df = year_cat[year_cat["카테고리"].isin(sel_cats_trend)].copy()
fig_tr = go.Figure()
summary_rows = []
for c in sel_cats_trend:
    s = trend_df[trend_df["카테고리"]==c].dropna(subset=["비중(%)"])
    if s.empty: continue
    fig_tr.add_trace(go.Scatter(x=s["연"].astype(str), y=s["비중(%)"], mode="lines+markers", name=c))
    if len(s) >= 3:
        x = s["연"].astype(int).to_numpy()
        y = s["비중(%)"].to_numpy()
        a, b = np.polyfit(x, y, 1)            # y = a*연 + b
        yhat = a*x + b
        fig_tr.add_trace(go.Scatter(x=s["연"].astype(str), y=yhat, mode="lines",
                                    name=f"{c} 추세", line=dict(dash="dash")))
        early = s.head(min(3, len(s)))["비중(%)"].mean()
        late  = s.tail(min(3, len(s)))["비중(%)"].mean()
        summary_rows.append({"카테고리": c, "연간 기울기(pp/년)": float(a),
                             "초기3년→최근3년 변화(pp)": float(late - early)})

fig_tr.update_layout(xaxis_title="연도", yaxis_title="연간 평균 비중(%)",
                     legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                     font=dict(family="Noto Sans KR, Nanum Gothic, Malgun Gothic"))
st.plotly_chart(fig_tr, use_container_width=True)

st.divider()

# ───────────────────────────
# (3) 상세 테이블 + 다운로드 (기존 유지)
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
# (4) 최근 5년 CAGR & p.p. 변화 (요일/공휴일별)
# ───────────────────────────
st.subheader("📌 최근 5년 요일/공휴일 **월평균 성장률(CAGR)** 및 p.p. 변화")
yc = year_cat.copy()  # 연간 평균 비중(%) 기준
years_sorted = sorted(yc["연"].unique())
if len(years_sorted) >= 2:
    # 최근 5개 연도(있으면 5개, 아니면 가능한 만큼)
    last_years = years_sorted[-min(5, len(years_sorted)):]
    out_rows = []
    for c in cats_all:
        s = yc[(yc["카테고리"]==c) & (yc["연"].isin(last_years))].sort_values("연")
        if len(s) >= 2:
            first = s["비중(%)"].iloc[0]
            last  = s["비중(%)"].iloc[-1]
            n = len(s) - 1  # 간격 수
            if first > 0:
                cagr = (last/first)**(1/n) - 1
            else:
                cagr = np.nan
            out_rows.append({
                "카테고리": c,
                "기간": f"{int(s['연'].iloc[0])}–{int(s['연'].iloc[-1])}",
                "초기(%)": first,
                "최근(%)": last,
                "p.p.변화": last - first,
                "CAGR(연평균)": cagr*100
            })
    cagr_df = pd.DataFrame(out_rows)
    if not cagr_df.empty:
        cagr_df = cagr_df[["카테고리","기간","초기(%)","최근(%)","p.p.변화","CAGR(연평균)"]]
        st.dataframe(
            cagr_df.style.format({"초기(%)":"{:.2f}","최근(%)":"{:.2f}","p.p.변화":"{:+.2f}","CAGR(연평균)":"{:+.2f}%"}),
            use_container_width=True
        )
    else:
        st.info("최근 5년을 계산할 충분한 연도 데이터가 없습니다.")
else:
    st.info("연도 수가 2개 미만이라 CAGR을 계산할 수 없습니다.")

# ───────────────────────────
# (5) 자동 요약/결론 (간단)
# ───────────────────────────
msgs = []
# 금요일 요약
if "금" in year_cat["카테고리"].unique():
    s = year_cat[year_cat["카테고리"]=="금"].sort_values("연")
    if len(s)>=2:
        diff  = s["비중(%)"].iloc[-1] - s["비중(%)"].iloc[0]
        msgs.append(f"- **금요일 연간 평균 비중**: 기간 처음 대비 최근 {diff:+.2f}p 변화")
# 전체 증가/감소
chg = []
for c in cats_all:
    s = year_cat[year_cat["카테고리"]==c].sort_values("연")
    if len(s)>=2:
        chg.append((c, s["비중(%)"].iloc[-1]-s["비중(%)"].iloc[0]))
if chg:
    chg.sort(key=lambda x: x[1], reverse=True)
    inc = [f"{c} (+{d:.2f}p)" for c,d in chg if d>0]
    dec = [f"{c} ({d:.2f}p)" for c,d in chg if d<0]
    if inc: msgs.append("- **비중이 늘어난 쪽**: " + ", ".join(inc))
    if dec: msgs.append("- **비중이 줄어든 쪽**: " + ", ".join(dec))

if msgs:
    st.markdown("\n".join(msgs))
