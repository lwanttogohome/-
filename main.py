import io
import json
import zipfile

import pandas as pd
import requests
import plotly.express as px
import streamlit as st


# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(
    page_title="전국 고령화 단계구분도",
    page_icon="🗺️",
    layout="wide",
)

POPULATION_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/contents/"
    "/main/population_ts_yearly_gender.zip"
)

GEOJSON_URL = (
    "https://raw.githubusercontent.com/first2022-cyber/contents/"
    "/main/sigungu_kr.geojson"
)


# -----------------------------
# 데이터 불러오기
# -----------------------------
@st.cache_data
def load_population():
    response = requests.get(POPULATION_URL, timeout=60)
    response.raise_for_status()

    # ZIP 파일을 메모리에서 열기
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        csv_files = [
            name for name in z.namelist()
            if name.lower().endswith(".csv")
        ]

        if not csv_files:
            raise ValueError("ZIP 파일 안에서 CSV 파일을 찾을 수 없습니다.")

        # CSV가 하나라는 전제
        csv_name = csv_files[0]

        with z.open(csv_name) as f:
            df = pd.read_csv(f)

    return df


@st.cache_data
def load_geojson():
    response = requests.get(GEOJSON_URL, timeout=60)
    response.raise_for_status()

    return response.json()


# -----------------------------
# 고령화율 계산
# -----------------------------
@st.cache_data
def calculate_aging_rate(df):
    # 2026년만 사용
    df = df.copy()

    # 연도 자료형이 숫자/문자열 어느 쪽이어도 대응
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce")
    df = df[df["연도"] == 2026].copy()

    if df.empty:
        raise ValueError("2026년 데이터가 없습니다.")

    # 코드 문자열 처리
    df["코드"] = df["코드"].astype("string").str.strip()

    # 시군구 코드 = 읍·면·동 코드 앞 5자리
    df["시군구코드"] = df["코드"].str[:5]

    # 계_로 시작하는 열만 사용
    # 남_ / 여_ 열은 제외됨
    total_columns = [
        col for col in df.columns
        if col.startswith("계_")
    ]

    # 65세 이상 열
    age_65_columns = []

    for col in total_columns:
        age = col.replace("계_", "").strip()

        # 65세 ~ 100세 이상
        if age == "100세 이상":
            age_65_columns.append(col)
        else:
            try:
                age_number = int(age.replace("세", "").strip())

                if age_number >= 65:
                    age_65_columns.append(col)
            except ValueError:
                pass

    if not total_columns:
        raise ValueError("'계_'로 시작하는 인구 열을 찾을 수 없습니다.")

    if not age_65_columns:
        raise ValueError("65세 이상 인구 열을 찾을 수 없습니다.")

    # 숫자로 변환
    for col in total_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 읍·면·동별 전체 인구
    df["전체인구"] = df[total_columns].sum(axis=1)

    # 읍·면·동별 65세 이상 인구
    df["65세이상인구"] = df[age_65_columns].sum(axis=1)

    # 시군구별 합계
    result = (
        df.groupby("시군구코드", as_index=False)
        .agg(
            전체인구=("전체인구", "sum"),
            **{"65세이상인구": ("65세이상인구", "sum")}
        )
    )

    # 고령화율(%)
    result["고령화율"] = (
        result["65세이상인구"]
        / result["전체인구"]
        * 100
    )

    result["고령화율"] = result["고령화율"].round(2)

    # 5자리 코드도 문자열로 고정
    result["시군구코드"] = (
        result["시군구코드"]
        .astype("string")
        .str.zfill(5)
    )

    return result


# -----------------------------
# GeoJSON에 데이터 연결
# -----------------------------
@st.cache_data
def make_geojson(population_df, geojson):
    geojson = json.loads(json.dumps(geojson))

    # GeoJSON의 코드도 문자열로 통일
    for feature in geojson["features"]:
        properties = feature.get("properties", {})

        code = properties.get("코드")

        if code is not None:
            properties["코드"] = str(code).strip().zfill(5)

    return geojson


# -----------------------------
# 앱 본문
# -----------------------------
st.title("🗺️ 전국 고령화 단계구분도")
st.caption("2026년 6월 기준 읍·면·동 인구자료를 시군구 단위로 집계")

try:
    population_df = load_population()
    geojson = load_geojson()

    aging_df = calculate_aging_rate(population_df)
    geojson = make_geojson(aging_df, geojson)

except Exception as e:
    st.error("데이터를 불러오거나 처리하는 중 오류가 발생했습니다.")
    st.exception(e)
    st.stop()


# -----------------------------
# GeoJSON과 인구 데이터 코드 비교
# -----------------------------
geo_codes = {
    str(feature.get("properties", {}).get("코드", "")).strip().zfill(5)
    for feature in geojson["features"]
}

data_codes = set(aging_df["시군구코드"].dropna().astype(str))

matched_codes = geo_codes & data_codes

if not matched_codes:
    st.error(
        "인구 데이터와 GeoJSON의 시군구 코드가 하나도 일치하지 않습니다."
    )
    st.stop()

map_df = aging_df[
    aging_df["시군구코드"].isin(matched_codes)
].copy()


# -----------------------------
# 단계구분도
# -----------------------------
fig = px.choropleth(
    map_df,
    geojson=geojson,
    locations="시군구코드",
    featureidkey="properties.코드",
    color="고령화율",
    color_continuous_scale="YlOrRd",
    range_color=(
        float(map_df["고령화율"].min()),
        float(map_df["고령화율"].max()),
    ),
    projection="mercator",
    labels={
        "고령화율": "고령화율 (%)"
    },
    hover_data={
        "시군구코드": False,
        "고령화율": ":.2f",
    },
)


# GeoJSON 경계만 표시하고 배경 지도는 제거
fig.update_geos(
    fitbounds="locations",
    visible=False,
)

# 경계선 설정
fig.update_traces(
    marker_line_width=0.7,
    marker_line_color="white",
    hovertemplate=(
        "<b>%{customdata[0]}</b><br>"
        "고령화율: %{z:.2f}%"
        "<extra></extra>"
    ),
    customdata=map_df[["시군구코드"]].values,
)

# 실제 시군구 이름을 GeoJSON에서 가져와 hover에 표시
name_by_code = {}

for feature in geojson["features"]:
    properties = feature.get("properties", {})
    code = str(properties.get("코드", "")).strip().zfill(5)
    name = properties.get("시군구", "")

    if code:
        name_by_code[code] = name

map_df["시군구"] = (
    map_df["시군구코드"]
    .map(name_by_code)
    .fillna("이름 없음")
)

# customdata를 시군구 이름 + 고령화율로 다시 설정
fig.update_traces(
    customdata=map_df[["시군구", "고령화율"]].values,
    hovertemplate=(
        "<b>%{customdata[0]}</b><br>"
        "고령화율: %{customdata[1]:.2f}%"
        "<extra></extra>"
    ),
)

fig.update_layout(
    height=750,
    margin=dict(l=0, r=0, t=20, b=0),
    coloraxis_colorbar=dict(
        title="고령화율 (%)"
    ),
)


# -----------------------------
# 지도 출력
# -----------------------------
st.plotly_chart(
    fig,
    width="stretch",
    config={
        "scrollZoom": True,
        "displaylogo": False,
    },
)


# -----------------------------
# 통계
# -----------------------------
col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "지도에 표시된 시군구",
        f"{len(map_df):,}개"
    )

with col2:
    st.metric(
        "최저 고령화율",
        f"{map_df['고령화율'].min():.2f}%"
    )

with col3:
    st.metric(
        "최고 고령화율",
        f"{map_df['고령화율'].max():.2f}%"
    )


# -----------------------------
# 데이터 표
# -----------------------------
with st.expander("시군구별 고령화율 표 보기"):
    table = map_df[
        ["시군구코드", "시군구", "전체인구", "65세이상인구", "고령화율"]
    ].copy()

    table = table.sort_values(
        "고령화율",
        ascending=False
    )

    table.columns = [
        "코드",
        "시군구",
        "전체 인구",
        "65세 이상 인구",
        "고령화율 (%)",
    ]

    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
    )
