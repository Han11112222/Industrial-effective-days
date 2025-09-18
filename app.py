# app.py — 금요일/월요일/휴일 vs 평일(화·수·목) 월별 비율 분석
# Streamlit: 1.31+ / pandas / numpy / openpyxl / matplotlib

import os
from pathlib import Path
import warnings
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# ---------- 한글 폰트(있으면 적용) ----------
def set_korean_font():
    candidates = [
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/Library/Fonts/AppleSDGothicNeo.ttc"),
    ]
    for p in candidates:
        try:
            if p.exists():
                mpl.font_manager.fontManager.addfont(str(p))
                fam = mpl.font_manager.FontProperties(fname=str(p)).get_name()
                plt.rcParams["font.family"] = [fam]
                plt.rcParams["axes.unicode_minus"] = False
                return
        except Exception:
            pass
    plt.rcParams["axes.unicode_minus"] = False

set_korean_font()

# ---------- 작은 유틸 ----------
KOR_DOW_SHORT = {"월":0,"화":1,"수":2,"목":3,"금":4,"토":5,"일":6}
KOR_DOW_LONG  = {"월요일":0,"화요일":1,"수요일":2,"목요일":3,"금요일":4,"토요일":5,"일요일":6}
ENG_DOW_SHORT = {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}
ENG_DOW_LONG  = {"Monday":0,"Tuesday":1,"Wednesday":2,"Thursday":3,"Friday":4,"Saturday":5,"Sunday":6}

def detect_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    # 느슨한 매칭
    low = {str(c).lower(): c for c in df.columns}
    for cand in candidates:
        k = str(cand).lower()
        if k in low: return low[k]
    return None

def parse_weekday_series(s):
    """요일 문자열 -> 0=월 .. 6=일 (숫자 이미 있으면 그대로)"""
    v = s.astype(str).str.strip()
    out = pd.Series(np.nan, index=v.index, dtype="float")
    maps = [KOR_DOW_SHORT, KOR_DOW_LONG, ENG_DOW_SHORT, ENG_DOW_LONG]
    for mp in maps:
        mask = v.isin(mp.keys())
        if mask.any(): out.loc[mask] = v.loc[mask].map(mp).astype(float)
    num = pd.to_numeric(v, errors="coerce")
    out = np.where(pd.notna(num), num, out).astype(float)
    return pd.Series(out, index=v.index)

def month_start(x): x = pd.to_datetime(x); return pd.Timestamp(x.year, x.month, 1)

# ---------- 파일 읽기 ----------
@st.cache_data(ttl=600)
def load_calendar_excel(path, sheet=None):
    xls = pd.ExcelFile(path, engine="openpyxl")
    sheet_name = sheet if (sheet and sheet in xls.sheet_names) else xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=sheet_name)
    df.columns = [str(c).strip() for c in df.columns]

    # 날짜
    date_col = detect_col(df, ["날짜","일자","date","Date"])
    if date_col is None:
        raise ValueError("날짜 열을 찾을 수 없습니다. (예: '날짜','일자','date')")
    df["날짜"] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=["날짜"]).copy()

    # 공급량
    value_col = detect_col(df, ["공급량(MJ)","공급량","사용량","수요","value","usage"])
    if value_col is None:
        raise ValueError("공급량 열을 찾을 수 없습니다. (예: '공급량(MJ)','공급량')")
    df["공급량"] = pd.to_numeric(df[value_col], errors="coerce")
    df = df.dropna(subset=["공급량"]).copy()

    # 요일
    dow_col = detect_col(df, ["요일","dow","DOW"])
    if dow_col is not None:
        dow = parse_weekday_series(df[dow_col])
    else:
        dow = df["날짜"].dt.weekday.astype(float)
    df["요일(0=월)"] = dow

    # 주중/휴무/공휴일/법정일 플래그(있으면 사용)
    def to_bool(s):
        if s is None: return None
        v = pd.Series(s)
        if v.dtype == bool: return v
        return v.astype(str).str.strip().str.upper().map({"TRUE":True,"FALSE":False,"Y":True,"N":False,"1":True,"0":False}).fillna(np.nan)

    df["주중여부"] = to_bool(df.get("주중여부"))
    df["휴무여부"] = to_bool(df.get("휴무여부"))
    df["공휴일"]  = to_bool(df.get("공휴일"))
    df["법정일"]  = to_bool(df.get("법정일"))

    if "연" not in df.columns: df["연"] = df["날짜"].dt.year
    if "월" not in df.columns: df["월"] = df["날짜"].dt.month

    # 구분 텍스트(주말/명절 등) — 선택적
    df["구분"] = df.get("구분").astype(str).fillna("")

    return df[["날짜","연","월","요일(0=월)","공급량","주중여부","휴무여부","공휴일","법정일","구분"]]

# ---------- 분류 로직 ----------
def classify_row(row) -> str:
    dow = int(row["요일(0=월)"]) if pd.notna(row["요일(0=월)"]) else None

    # 휴일 판정: 토/일 OR 휴무/공휴/법정일 OR 구분에 주말/명절/휴일 등
    text = str(row.get("구분",""))
    is_weekend = (dow in [5,6])
    is_flag_holiday = any([
        row.get("휴무여부") is True,
        row.get("공휴일")  is True,
        row.get("법정일")  is True,
        (row.get("주중여부") is False)
    ])
    is_text_holiday = any(k in text for k in ["주말","명절","휴일","공휴"])
    if is_weekend or is_flag_holiday or is_text_holiday:
        return "휴일"

    if dow == 0:  # 월
        return "평일1(월)"
    if dow == 4:  # 금
        return "평일2(금)"
    if dow in [1,2,3]:  # 화/수/목
        return "평일(화수목)"

    # 혹시 모를 나머지(월~일 외 데이터) → 휴일로 처리
    return "휴일"

# ---------- 월별 집계 & 비율 ----------
def monthly_agg(df, yfrom=2021, yto=2025):
    df = df[(df["연"]>=yfrom) & (df["연"]<=yto)].copy()
    df["분류"] = df.apply(classify_row, axis=1)

    # 합계/일평균
    grp = df.groupby(["연","월","분류"])
    agg = grp["공급량"].agg(total="sum", mean="mean", days="count").reset_index()

    # 피벗: 합계/일평균 각각
    total_pv = agg.pivot_table(index=["연","월"], columns="분류", values="total").reset_index()
    mean_pv  = agg.pivot_table(index=["연","월"], columns="분류", values="mean").reset_index()

    # 비율: (월/금/휴일) / (화수목)
    def ratio_frame(pv: pd.DataFrame, how="mean"):
        pv = pv.copy()
        base = "평일(화수목)"
        for tgt in ["평일1(월)", "평일2(금)", "휴일"]:
            pv[f"{how}_ratio_{tgt}"] = np.where(
                pv.get(base, np.nan).fillna(0)==0, np.nan,
                pv.get(tgt, np.nan) / pv.get(base, np.nan)
            )
        return pv

    total_rat = ratio_frame(total_pv, "sum")
    mean_rat  = ratio_frame(mean_pv,  "mean")

    # 보기 좋게 merge
    out = pd.merge(mean_rat, total_rat, on=["연","월"], how="outer", suffixes=("_mean","_sum"))
    out = out.sort_values(["연","월"]).reset_index(drop=True)
    out["월표기"] = out["월"].map(lambda m: f"{m:02d}월")
    return out, df

# ---------- 표시용 테이블 ----------
def show_table(df: pd.DataFrame, title: str):
    st.markdown(f"### {title}")
    fmt = df.copy()
    # 값 포맷
    for c in fmt.columns:
        if c in ["연","월","월표기"]: continue
        if "ratio" in c:
            fmt[c] = pd.to_numeric(fmt[c], errors="coerce").map(lambda x: "" if pd.isna(x) else f"{x:.3f}")
        else:
            fmt[c] = pd.to_numeric(fmt[c], errors="coerce").map(lambda x: "" if pd.isna(x) else f"{x:,.0f}")
    st.dataframe(fmt, use_container_width=True)

# ---------- 그래프 ----------
def plot_heatmap(pivot, title, fname):
    fig, ax = plt.subplots(figsize=(11.5, 3.6))
    im = ax.imshow(pivot.values, aspect="auto", cmap="viridis", interpolation="nearest")
    ax.set_yticks(range(len(pivot.index))); ax.set_yticklabels(pivot.index)
    ax.set_xticks(range(12)); ax.set_xticklabels([f"{m}월" for m in range(1,13)])
    ax.set_title(title)
    cbar = plt.colorbar(im, ax=ax); cbar.ax.set_ylabel("ratio", rotation=90)
    fig.tight_layout()
    st.pyplot(fig)
    return fig

def plot_timeseries(ts, title):
    fig, ax = plt.subplots(figsize=(11.5, 4.0))
    ax.plot(ts["날짜축"], ts["value"], marker="o", lw=1.8)
    ax.set_title(title); ax.set_ylabel("ratio")
    ax.grid(alpha=0.3)
    st.pyplot(fig)
    return fig

# ================== UI ==================
st.set_page_config(page_title="요일/휴일별 월별 비율 분석", layout="wide")
st.title("요일/휴일 구분 — 월별 공급량 비율 분석")

with st.sidebar:
    st.header("데이터 불러오기")
    up = st.file_uploader("엑셀 업로드 (예: effective_days_calendar.xlsx)", type=["xlsx"])
    sheet = st.text_input("시트명(선택, 기본: 첫 시트)", value="data")

    col1, col2 = st.columns(2)
    with col1:
        yfrom = st.number_input("시작 연도", value=2021, step=1)
    with col2:
        yto = st.number_input("종료 연도", value=2025, step=1)

if up is None:
    st.info("좌측에서 엑셀 파일을 업로드하세요.")
    st.stop()

try:
    raw = load_calendar_excel(up, sheet if sheet.strip() else None)
except Exception as e:
    st.error(f"파일을 읽는 중 오류: {e}")
    st.stop()

res, classified = monthly_agg(raw, yfrom=int(yfrom), yto=int(yto))

# ---- 결과 테이블(요약) ----
# 핵심 칼럼 정리
cols_show = [
    "연","월",
    "평일(화수목)_mean","평일1(월)_mean","평일2(금)_mean","휴일_mean",
    "mean_ratio_평일1(월)","mean_ratio_평일2(금)","mean_ratio_휴일",
    "평일(화수목)_sum","평일1(월)_sum","평일2(금)_sum","휴일_sum",
    "sum_ratio_평일1(월)","sum_ratio_평일2(금)","sum_ratio_휴일",
]
# 실제 존재하는 칼럼만 표시
cols_show = [c for c in cols_show if c in res.columns]
show_table(res[cols_show], "월별 집계/비율 (일평균·합계)")

# ---- 다운로드 ----
csv_bytes = res.to_csv(index=False).encode("utf-8-sig")
st.download_button("⬇️ 월별 비율 결과 CSV 다운로드", data=csv_bytes,
                   file_name="weekday_holiday_monthly_ratios.csv", mime="text/csv")

# ---- 히트맵: 일평균 기준 비율 ----
st.markdown("## 히트맵 — 일평균 기준 비율")
for tgt, label in [("평일1(월)","월요일/화·수·목"), ("평일2(금)","금요일/화·수·목"), ("휴일","휴일/화·수·목")]:
    col = f"mean_ratio_{tgt}"
    if col not in res.columns: continue
    pv = res.pivot(index="연", columns="월", values=col).reindex(columns=range(1,13))
    plot_heatmap(pv, f"{label}", f"heat_{tgt}.png")

# ---- 시계열: 일평균 기준 비율 ----
st.markdown("## 시계열 — 일평균 기준 비율(연속 월)")
for tgt, label in [("평일1(월)","월요일/화·수·목"), ("평일2(금)","금요일/화·수·목"), ("휴일","휴일/화·수·목")]:
    col = f"mean_ratio_{tgt}"
    if col not in res.columns: continue
    ts = res[["연","월",col]].dropna().copy()
    ts["날짜축"] = pd.to_datetime(ts["연"].astype(str)+"-"+ts["월"].astype(str)+"-01").map(month_start)
    ts = ts.sort_values("날짜축").rename(columns={col:"value"})
    plot_timeseries(ts, f"{label} (일평균 기준)")

# ---- 원시 분류 데이터 미리보기 ----
with st.expander("분류 결과(일별) 샘플 보기"):
    st.dataframe(classified.head(200), use_container_width=True)
