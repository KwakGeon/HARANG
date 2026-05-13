import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scraper import scrape_season

st.set_page_config(
    page_title="하랑 타이거즈 상대전적",
    page_icon="⚾",
    layout="wide",
)

st.title("⚾ 하랑 타이거즈 — 상대전적 대시보드")

SEASONS = [2024, 2025, 2026]


@st.cache_data(ttl=3600, show_spinner="게임원에서 경기 데이터를 불러오는 중...")
def load_data(seasons):
    all_games = []
    for season in seasons:
        games = scrape_season(season)
        for g in games:
            g["시즌"] = season
        all_games.extend(games)
    if not all_games:
        return pd.DataFrame()
    df = pd.DataFrame(all_games)
    df = df.drop_duplicates(subset=["game_idx"], keep="first")
    return df


def calc_head_to_head(df):
    summary = (
        df.groupby("상대팀")
        .apply(
            lambda g: pd.Series({
                "경기수": len(g),
                "승": int(g["결과"].str.contains("승").sum()),
                "패": int(g["결과"].str.contains("패").sum()),
                "무": int((g["결과"] == "무").sum()),
                "우리팀_총득점": int(g["우리팀_점수"].sum()),
                "상대팀_총득점": int(g["상대팀_점수"].sum()),
            })
        )
        .reset_index()
    )
    summary["승률(%)"] = (summary["승"].astype(float) / summary["경기수"] * 100).round(1)
    summary["평균득점"] = (summary["우리팀_총득점"].astype(float) / summary["경기수"]).round(2)
    summary["평균실점"] = (summary["상대팀_총득점"].astype(float) / summary["경기수"]).round(2)
    summary["득실차"] = summary["우리팀_총득점"] - summary["상대팀_총득점"]
    return summary.sort_values("경기수", ascending=False)


# 데이터 로드
df = load_data(tuple(SEASONS))

if df.empty:
    st.error("데이터를 불러오지 못했습니다. 잠시 후 새로고침해주세요.")
    st.stop()

col_refresh = st.columns([6, 1])[1]
if col_refresh.button("🔄 새로고침"):
    st.cache_data.clear()
    st.rerun()

# 사이드바 필터
st.sidebar.header("필터")
seasons = sorted(df["시즌"].unique().tolist(), reverse=True)
selected_seasons = st.sidebar.multiselect("시즌 선택", seasons, default=seasons)
df = df[df["시즌"].isin(selected_seasons)]

if "리그" in df.columns:
    leagues = sorted(df["리그"].unique().tolist())
    selected_leagues = st.sidebar.multiselect("리그 선택", leagues, default=leagues)
    df = df[df["리그"].isin(selected_leagues)]

if df.empty:
    st.warning("선택한 조건에 해당하는 경기가 없습니다.")
    st.stop()

# 전체 요약 지표
total = len(df)
wins = int(df["결과"].str.contains("승").sum())
losses = int(df["결과"].str.contains("패").sum())
draws = int((df["결과"] == "무").sum())
win_rate = wins / total * 100 if total > 0 else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("총 경기", total)
c2.metric("승", wins)
c3.metric("패", losses)
c4.metric("무", draws)
c5.metric("승률", f"{win_rate:.1f}%")

st.divider()

tab1, tab2, tab3 = st.tabs(["📊 상대전적 요약", "📋 경기 히스토리", "📈 차트 분석"])

with tab1:
    st.subheader("상대팀별 전적")
    summary = calc_head_to_head(df)

    def highlight_result(row):
        styles = [""] * len(row)
        if row["승률(%)"] >= 60:
            styles[0] = "background-color: #d4edda; color: #155724"
        elif row["승률(%)"] <= 40:
            styles[0] = "background-color: #f8d7da; color: #721c24"
        return styles

    display_cols = ["상대팀", "경기수", "승", "패", "무", "승률(%)", "평균득점", "평균실점", "득실차"]
    st.dataframe(
        summary[display_cols].style.apply(highlight_result, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("상대팀별 승률")
    fig = px.bar(
        summary.sort_values("승률(%)"),
        x="승률(%)",
        y="상대팀",
        orientation="h",
        color="승률(%)",
        color_continuous_scale=["#dc3545", "#ffc107", "#28a745"],
        range_color=[0, 100],
        text="승률(%)",
    )
    fig.add_vline(x=50, line_dash="dash", line_color="gray")
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(height=max(300, len(summary) * 40), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("경기 히스토리")
    opponents = sorted(df["상대팀"].unique().tolist())
    selected_opp = st.selectbox("상대팀 선택", ["전체"] + opponents)

    filtered = df if selected_opp == "전체" else df[df["상대팀"] == selected_opp]
    filtered = filtered.sort_values("날짜", ascending=False)

    def color_result(val):
        if "승" in str(val):
            return "background-color: #d4edda; color: #155724"
        elif "패" in str(val):
            return "background-color: #f8d7da; color: #721c24"
        elif val == "무":
            return "background-color: #fff3cd; color: #856404"
        return ""

    show_cols = ["날짜", "시즌", "상대팀", "우리팀_점수", "상대팀_점수", "결과", "리그", "구장"]
    show_cols = [c for c in show_cols if c in filtered.columns]
    st.dataframe(
        filtered[show_cols].style.applymap(color_result, subset=["결과"]),
        use_container_width=True,
        hide_index=True,
    )

    if selected_opp != "전체" and not filtered.empty:
        st.subheader(f"vs {selected_opp} 맞대결 요약")
        s = calc_head_to_head(filtered[filtered["상대팀"] == selected_opp]).iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("경기수", int(s["경기수"]))
        c2.metric("승 / 패 / 무", f"{int(s['승'])} / {int(s['패'])} / {int(s['무'])}")
        c3.metric("승률", f"{s['승률(%)']:.1f}%")
        c4.metric("득실차", f"{int(s['득실차']):+d}")

with tab3:
    st.subheader("득점/실점 비교")
    summary = calc_head_to_head(df)
    top_n = st.slider("표시할 상대팀 수", 3, min(20, len(summary)), min(10, len(summary)))
    top = summary.head(top_n)

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(name="평균 득점", x=top["상대팀"], y=top["평균득점"], marker_color="#28a745"))
    fig2.add_trace(go.Bar(name="평균 실점", x=top["상대팀"], y=top["평균실점"], marker_color="#dc3545"))
    fig2.update_layout(barmode="group", title="상대팀별 평균 득점 vs 실점")
    st.plotly_chart(fig2, use_container_width=True)

    fig3 = go.Figure()
    fig3.add_trace(go.Bar(name="승", x=top["상대팀"], y=top["승"], marker_color="#28a745"))
    fig3.add_trace(go.Bar(name="무", x=top["상대팀"], y=top["무"], marker_color="#ffc107"))
    fig3.add_trace(go.Bar(name="패", x=top["상대팀"], y=top["패"], marker_color="#dc3545"))
    fig3.update_layout(barmode="stack", title="상대팀별 승/무/패")
    st.plotly_chart(fig3, use_container_width=True)
