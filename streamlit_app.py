"""메리츠 파트너스 — 커뮤니티 반응 대시보드.

온라인 커뮤니티에서 '메리츠 파트너스' 키워드가 언급된 반응을 수집·집계한다.
화면은 두 섹션으로 나뉜다.
    1) 게시글 탐색  — 개별 반응을 검색·정렬·필터로 훑어보기
    2) 인사이트 분석 — 언급량·채널·감성·키워드 집계 분석

데이터는 ``data.load_mentions()`` 가 제공한다(현재 샘플 → 추후 네이버/YouTube API).
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data import KEYWORD, load_mentions

# =============================================================================
# 설정 & 스타일
# =============================================================================

st.set_page_config(
    page_title="메리츠 파트너스 · 커뮤니티 반응",
    page_icon="📊",
    layout="wide",
)

PRIMARY = "#FF5C5C"
SENTIMENT_COLORS = {"긍정": "#3BC97A", "중립": "#A8B0BD", "부정": "#FF5C5C"}
SENTIMENT_EMOJI = {"긍정": "🟢 긍정", "중립": "⚪ 중립", "부정": "🔴 부정"}
CHANNEL_PALETTE = px.colors.qualitative.Set2
PLOTLY_FONT = dict(family="Pretendard, 'Noto Sans KR', sans-serif", size=13, color="#E6E8EB")

st.markdown(
    """
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');
    html, body, [class*="css"], .stMarkdown, .stMetric { font-family: 'Pretendard', 'Noto Sans KR', sans-serif; }
    .block-container { padding-top: 2.2rem; max-width: 1280px; }
    [data-testid="stMetricValue"] { font-weight: 700; }
    .kw-badge {
        display:inline-block; background:rgba(255,92,92,0.16); color:#FF8A85;
        font-weight:700; font-size:0.85rem; padding:3px 12px; border-radius:999px;
        margin-left:8px; vertical-align:middle;
    }
    .stTabs [data-baseweb="tab"] { font-size:1rem; font-weight:600; padding:10px 18px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600)
def get_data() -> tuple[pd.DataFrame, str]:
    df = load_mentions()
    return df, df.attrs.get("source", "샘플 데이터")


def style_fig(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        height=height,
        margin=dict(l=10, r=10, t=30, b=10),
        font=PLOTLY_FONT,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=-0.25, x=0),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)", zeroline=False)
    return fig


# =============================================================================
# 데이터 로드 & 전역 필터 (사이드바)
# =============================================================================

df_all, DATA_SOURCE = get_data()
IS_SAMPLE = DATA_SOURCE == "샘플 데이터"
# 네이버 검색 API는 좋아요·댓글(engagement)을 제공하지 않는다 → 0이면 관련 UI 숨김
HAS_ENGAGEMENT = bool(df_all["engagement"].sum() > 0)

with st.sidebar:
    st.markdown("### 🔎 필터")

    min_d, max_d = df_all["date"].min().date(), df_all["date"].max().date()
    date_range = st.date_input(
        "기간",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d,
        format="YYYY-MM-DD",
    )
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        d_start, d_end = date_range
    else:
        d_start, d_end = min_d, max_d

    channels = sorted(df_all["channel"].unique())
    sel_channels = st.multiselect("채널", channels, default=channels)

    sentiments = ["긍정", "중립", "부정"]
    sel_sent = st.pills(
        "감성", sentiments, default=sentiments, selection_mode="multi"
    ) or sentiments

    st.divider()
    if IS_SAMPLE:
        st.caption(
            "🟡 현재 **샘플 데이터**입니다. `.streamlit/secrets.toml` 에 네이버 키를 "
            "넣으면 실데이터로 교체됩니다."
        )
    else:
        st.caption(f"🟢 데이터 출처: **{DATA_SOURCE}**")

# 작성일 미확인(NaT) 글은 기간 필터와 무관하게 항상 포함
in_range = df_all["date"].isna() | (
    (df_all["date"].dt.date >= d_start) & (df_all["date"].dt.date <= d_end)
)
mask = (
    in_range
    & (df_all["channel"].isin(sel_channels))
    & (df_all["sentiment"].isin(sel_sent))
)
df = df_all[mask].copy()


# =============================================================================
# 헤더
# =============================================================================

st.markdown(
    f"# 커뮤니티 반응 대시보드 "
    f"<span class='kw-badge'>{KEYWORD}</span>",
    unsafe_allow_html=True,
)
st.caption(
    f"수집 기간 {d_start:%Y.%m.%d} ~ {d_end:%Y.%m.%d}  ·  "
    f"채널 {len(sel_channels)}개  ·  최종 업데이트 {max_d:%Y.%m.%d}"
)

if df.empty:
    st.warning("선택한 조건에 해당하는 반응이 없습니다. 필터를 조정해 주세요.")
    st.stop()


# =============================================================================
# 탭 구성
# =============================================================================

tab_posts, tab_insight = st.tabs(["📰 게시글 탐색", "📊 인사이트 분석"])


# -----------------------------------------------------------------------------
# 탭 1) 게시글 탐색
# -----------------------------------------------------------------------------
with tab_posts:
    # 탐색 컨트롤
    with st.container(horizontal=True, vertical_alignment="bottom"):
        query = st.text_input(
            "🔍 키워드 검색 (제목·본문)", placeholder="예: 정착지원금, 후기, 수수료 …"
        )
        sort_opts = (["최신순", "반응 많은순", "오래된순"] if HAS_ENGAGEMENT
                     else ["최신순", "오래된순"])
        sort_by = st.selectbox("정렬", sort_opts, index=0)  # 기본: 작성일 내림차순

    view = df.copy()
    if query:
        q = query.strip()
        view = view[
            view["title"].str.contains(q, case=False, na=False)
            | view["snippet"].str.contains(q, case=False, na=False)
            | view["keyword"].str.contains(q, case=False, na=False)
        ]

    if sort_by == "반응 많은순":
        view = view.sort_values("engagement", ascending=False)
    elif sort_by == "최신순":
        view = view.sort_values("date", ascending=False)
    else:
        view = view.sort_values("date", ascending=True)

    # 요약 지표 (현재 탐색 결과 기준)
    with st.container(horizontal=True):
        st.metric("검색 결과", f"{len(view):,}건", border=True)
        if HAS_ENGAGEMENT:
            st.metric("총 반응수", f"{int(view['engagement'].sum()):,}", border=True)
        else:
            st.metric("채널 수", f"{view['channel'].nunique()}개", border=True)
        st.metric(
            "긍정 비율",
            f"{(view['sentiment'] == '긍정').mean() * 100:.1f}%" if len(view) else "—",
            border=True,
        )

    st.caption(f"전체 {len(df):,}건 중 {len(view):,}건 표시 · 정렬: {sort_by}")

    cols = ["date", "channel", "sentiment", "title", "keyword", "author"]
    if HAS_ENGAGEMENT:
        cols.append("engagement")
    cols.append("url")

    show = view[cols].copy()
    show["sentiment"] = show["sentiment"].map(SENTIMENT_EMOJI)
    show["date"] = show["date"].dt.strftime("%Y-%m-%d").fillna("미확인")
    show = show.rename(
        columns={
            "date": "작성일", "channel": "채널", "sentiment": "감성",
            "title": "제목", "keyword": "연관 키워드", "author": "작성자",
            "engagement": "반응수", "url": "링크",
        }
    )

    st.dataframe(
        show,
        hide_index=True,
        height=560,
        column_config={
            "제목": st.column_config.TextColumn("제목", width="large"),
            "링크": st.column_config.LinkColumn("링크", display_text="원문 보기"),
            "반응수": st.column_config.NumberColumn("반응수", format="%d"),
        },
    )


# -----------------------------------------------------------------------------
# 탭 2) 인사이트 분석
# -----------------------------------------------------------------------------
with tab_insight:
    # 작성일이 확인되는 글만 시계열(추이·일평균)에 사용
    df_dated = df[df["date_known"]] if "date_known" in df.columns else df

    # KPI 행
    if not df_dated.empty:
        dd_start = df_dated["date"].dt.date.min()
        dd_end = df_dated["date"].dt.date.max()
        daily = (
            df_dated.groupby(df_dated["date"].dt.date)
            .size()
            .reindex(pd.date_range(dd_start, dd_end).date, fill_value=0)
        )
    else:
        daily = pd.Series(dtype=int)
    total = len(df)
    pos_ratio = (df["sentiment"] == "긍정").mean() * 100
    neg_ratio = (df["sentiment"] == "부정").mean() * 100
    active_channels = df["channel"].nunique()
    daily_avg = len(df_dated) / max(len(daily), 1)

    with st.container(horizontal=True):
        st.metric(
            "총 언급량", f"{total:,}건", border=True,
            chart_data=daily.tolist(), chart_type="bar",
        )
        st.metric(
            "긍정 비율", f"{pos_ratio:.1f}%",
            f"부정 {neg_ratio:.1f}%", delta_color="inverse", border=True,
        )
        st.metric("활성 채널", f"{active_channels}개", border=True)
        st.metric("일평균 언급", f"{daily_avg:.1f}건", border=True)

    # 언급량 추이 (채널별 스택)
    with st.container(border=True):
        st.markdown("**📈 언급량 추이 (채널별)**")
        n_undated = len(df) - len(df_dated)
        if n_undated:
            st.caption(
                f"※ 작성일이 확인되는 {len(df_dated):,}건 기준. "
                f"카페 등 작성일 미제공 {n_undated:,}건은 추이에서 제외(분포·감성·목록엔 포함)."
            )
        trend = (
            df_dated.groupby([df_dated["date"].dt.date, "channel"])
            .size()
            .reset_index(name="건수")
            .rename(columns={"date": "날짜"})
        )
        fig = px.area(
            trend, x="날짜", y="건수", color="channel",
            color_discrete_sequence=CHANNEL_PALETTE,
        )
        fig.update_traces(line=dict(width=0.5))
        st.plotly_chart(style_fig(fig, 340), config={"displayModeBar": False})

    # 채널 분포 · 감성 분포
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**📡 채널별 분포**")
            ch = df["channel"].value_counts().reset_index()
            ch.columns = ["channel", "건수"]
            fig = px.pie(
                ch, names="channel", values="건수", hole=0.55,
                color_discrete_sequence=CHANNEL_PALETTE,
            )
            fig.update_traces(textposition="outside", textinfo="percent+label")
            st.plotly_chart(style_fig(fig, 320), config={"displayModeBar": False})
    with c2:
        with st.container(border=True):
            st.markdown("**💬 감성 분포**")
            se = df["sentiment"].value_counts().reindex(
                ["긍정", "중립", "부정"]
            ).fillna(0).reset_index()
            se.columns = ["sentiment", "건수"]
            fig = px.pie(
                se, names="sentiment", values="건수", hole=0.55,
                color="sentiment", color_discrete_map=SENTIMENT_COLORS,
            )
            fig.update_traces(textposition="outside", textinfo="percent+label")
            st.plotly_chart(style_fig(fig, 320), config={"displayModeBar": False})

    # 주별 감성 추이
    with st.container(border=True):
        st.markdown("**🗓️ 주별 감성 추이**")
        tmp = df_dated.copy()
        tmp["주"] = tmp["date"].dt.to_period("W").dt.start_time
        wk = tmp.groupby(["주", "sentiment"]).size().reset_index(name="건수")
        fig = px.bar(
            wk, x="주", y="건수", color="sentiment",
            color_discrete_map=SENTIMENT_COLORS,
            category_orders={"sentiment": ["긍정", "중립", "부정"]},
        )
        fig.update_layout(barmode="stack")
        st.plotly_chart(style_fig(fig, 300), config={"displayModeBar": False})

    # 연관 키워드 · 채널별 반응량
    k1, k2 = st.columns(2)
    with k1:
        with st.container(border=True):
            st.markdown("**🏷️ 연관 키워드 Top 10**")
            kw = df["keyword"].value_counts().head(10).sort_values()
            fig = go.Figure(
                go.Bar(x=kw.values, y=kw.index, orientation="h",
                       marker_color=PRIMARY)
            )
            st.plotly_chart(style_fig(fig, 320), config={"displayModeBar": False})
    with k2:
        with st.container(border=True):
            if HAS_ENGAGEMENT:
                st.markdown("**🔥 채널별 반응량 (engagement 합계)**")
                series = (
                    df.groupby("channel")["engagement"].sum()
                    .sort_values(ascending=True)
                )
            else:
                st.markdown("**📊 채널별 언급량 (건수)**")
                series = df["channel"].value_counts().sort_values(ascending=True)
            fig = go.Figure(
                go.Bar(x=series.values, y=series.index, orientation="h",
                       marker_color="#F4A23F")
            )
            st.plotly_chart(style_fig(fig, 320), config={"displayModeBar": False})
