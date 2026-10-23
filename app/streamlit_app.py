import hashlib
import io
import os
import sys
from pathlib import Path

# Streamlit Cloud runs this file directly without installing the project, so the repository root is added
# to the import path to make the streampulse package importable there as well as locally.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from groq import RateLimitError

from streampulse.app_data import APP_DATA_DIR, SAMPLE_UPLOAD_PATH, connect_app_database
from streampulse.ask import SCHEMA_NOTES, build_chart, choose_chart
from streampulse.charts import COUNTRY_COLORS, SECONDARY_INK
from streampulse.example_answers import EXAMPLE_QUESTIONS, load_example_answers
from streampulse.upload import (
    UPLOAD_COUNTRIES, UploadError, build_upload_database, check_upload_header, connect_upload_database,
    country_from_file_name, save_upload, upload_database_path, upload_schema_notes,
)
from streampulse.virality_scoring import FEATURE_COLUMNS, feature_matrix, load_saved_models

st.set_page_config(page_title="StreamPulse", layout="wide")

# On Streamlit Cloud the Groq key comes from the app's secrets; locally it comes from .env.
try:
    if "GROQ_API_KEY" in st.secrets:
        os.environ.setdefault("GROQ_API_KEY", st.secrets["GROQ_API_KEY"])
except FileNotFoundError:
    pass

COUNTRIES = ["IN", "US", "GB"]
BUILT_IN = "built-in"
KAGGLE_URL = "https://www.kaggle.com/datasets/rsrishav/youtube-trending-video-dataset"
LOCAL_TIMEZONE_SQL = (
    "timezone(CASE country "
    + " ".join(f"WHEN '{code}' THEN '{zone}'" for code, (_, zone) in UPLOAD_COUNTRIES.items())
    + " END, published_at AT TIME ZONE 'UTC')"
)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
AXIS_LABELS = {"country": "Country", "videos": "Trending videos", "median_days": "Median days",
               "mean_days": "Average days", "category": "", "week": "", "month": "",
               "new_videos": "New trending videos", "pct_of_videos": "% of the country's trending videos",
               "name": "Topic"}
DAILY_LIMIT_MESSAGE = ("The free Groq token limit for today is used up, so new AI answers are paused. Charts and "
                       "the saved example answers still work; please try again later.")
MINUTE_LIMIT_MESSAGE = "The AI service is busy (free tier limit per minute). Please wait a minute and try again."


@st.cache_resource
def database(source=BUILT_IN):
    if source == BUILT_IN:
        return connect_app_database()
    return connect_upload_database(upload_database_path(source))


@st.cache_resource
def virality_models():
    return load_saved_models()


@st.cache_data
def query(sql, parameters=(), source=BUILT_IN):
    # Each query gets its own cursor, because several visitors can use the shared connection at once.
    return database(source).cursor().execute(sql, list(parameters)).df()


# The file argument starts with an underscore so Streamlit does not hash a possibly 200 MB upload on every rerun;
# the upload key already identifies it.
@st.cache_resource(show_spinner="Checking and cleaning the file...")
def prepare_upload(upload_key, country, _file, file_name):
    saved_path = save_upload(_file, file_name)
    try:
        return build_upload_database(saved_path, country, upload_database_path(upload_key))
    finally:
        saved_path.unlink(missing_ok=True)


@st.cache_data
def read_app_file(name):
    path = APP_DATA_DIR / name
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    return path.read_text(encoding="utf-8")


def rate_limit_message(limit_error):
    # Groq names the limit it hit; only the daily one means waiting is pointless.
    return DAILY_LIMIT_MESSAGE if "per day" in str(limit_error) else MINUTE_LIMIT_MESSAGE


def country_label(code):
    return f"{UPLOAD_COUNTRIES[code][0]} ({code})"


def built_in_source(message=None):
    if message:
        st.error(f"{message} Showing the built-in data instead.")
    return {"key": BUILT_IN, "countries": COUNTRIES, "summary": None, "notes": SCHEMA_NOTES}


def choose_data_source():
    """The data the first five tabs use: the built-in data or one uploaded country file."""
    st.sidebar.header("Data")
    mode = st.sidebar.radio("Data", ["Built-in: India, US and UK", "Upload a Kaggle trending CSV"],
                            label_visibility="collapsed")
    if mode.startswith("Built-in"):
        return built_in_source()
    st.sidebar.caption(f"One country's file from the [Kaggle YouTube trending dataset]({KAGGLE_URL}), such as "
                       "CA_youtube_trending_data.csv. Files are about 400 MB, over the 200 MB limit, so gzip the "
                       "file first (it shrinks to about 160 MB) or try the sample.")
    use_sample = st.sidebar.checkbox("Use the sample file (UK, 1 Mar to 15 Apr 2024)")
    st.sidebar.download_button("Download the sample file", SAMPLE_UPLOAD_PATH.read_bytes(),
                               file_name=SAMPLE_UPLOAD_PATH.name, mime="application/gzip")
    if not use_sample:
        uploaded = st.sidebar.file_uploader("Trending CSV (.csv or .csv.gz)", type=["csv", "gz"])
        chosen_country = st.sidebar.selectbox("Country of the file", list(UPLOAD_COUNTRIES), index=None,
                                              format_func=country_label, placeholder="Read from the file name")
    if use_sample:
        upload_key, country, file_name = "sample", "GB", SAMPLE_UPLOAD_PATH.name
        file = io.BytesIO(SAMPLE_UPLOAD_PATH.read_bytes())
    elif uploaded is not None:
        try:
            check_upload_header(uploaded, uploaded.name)
        except UploadError as upload_error:
            return built_in_source(str(upload_error))
        # The country is not inside the Kaggle files, only in their names, so guessing wrong would mislabel the data.
        country = chosen_country or country_from_file_name(uploaded.name)
        if country is None:
            st.info(f"Choose the country of '{uploaded.name}' in the sidebar; it could not be read from the file name.")
            return built_in_source()
        upload_key = hashlib.sha256(f"{uploaded.file_id}{country}".encode()).hexdigest()[:16]
        file, file_name = uploaded, uploaded.name
    else:
        st.info("Upload a file or tick the sample in the sidebar. Until then the tabs show the built-in data.")
        return built_in_source()
    try:
        summary = prepare_upload(upload_key, country, file, file_name)
    except UploadError as upload_error:
        return built_in_source(str(upload_error))
    st.success(
        f"Showing your upload for {country_label(country)}: {summary['videos']:,} videos from {summary['first_day']} "
        f"to {summary['last_day']}. Removed {summary['same_day_repeats']:,} same-day repeat rows"
        + (f" and {summary['unreadable_rows']:,} unreadable rows" if summary["unreadable_rows"] else "")
        + ". The Virality predictor, Title optimizer and Topics tabs always use the built-in data, because the "
        "models were trained on it.")
    if summary["unknown_categories"]:
        st.caption("Category ids with no known name: " + ", ".join(summary["unknown_categories"]))
    notes = upload_schema_notes(country, summary["first_day"], summary["last_day"])
    return {"key": upload_key, "countries": [country], "summary": summary, "notes": notes}


def sidebar_filters(source):
    st.sidebar.header("Filters")
    st.sidebar.caption("Apply to the Overview, Trends, Publish time and Countries tabs.")
    countries = source["countries"]
    if source["key"] == BUILT_IN:
        countries = st.sidebar.multiselect("Country", COUNTRIES, default=COUNTRIES, format_func=country_label) or COUNTRIES
    all_categories = query("SELECT DISTINCT category FROM trending_videos ORDER BY category",
                           source=source["key"])["category"].tolist()
    # Keys include the source so switching data resets these instead of keeping values the new data lacks.
    categories = st.sidebar.multiselect("Category", all_categories, default=all_categories,
                                        key=f"categories_{source['key']}")
    first_day, last_day = query("SELECT min(first_trending_date), max(first_trending_date) FROM trending_videos",
                                source=source["key"]).iloc[0]
    date_range = st.sidebar.date_input("First trending date", (first_day, last_day), min_value=first_day,
                                       max_value=last_day, key=f"dates_{source['key']}")
    start, end = date_range if len(date_range) == 2 else (first_day, last_day)
    st.sidebar.divider()
    st.sidebar.caption("Built-in data: YouTube trending in India, the US and the UK, 12 Aug 2020 to 15 Apr 2024, "
                       "and the Netflix catalog to Sep 2021 with IMDb ratings.")
    return countries, categories or all_categories, start, end


def filter_sql(countries, categories, start, end):
    """A WHERE clause and its parameters for the sidebar filters on trending_videos."""
    return ("country IN (SELECT unnest(?)) AND category IN (SELECT unnest(?)) "
            "AND first_trending_date BETWEEN ? AND ?", (countries, categories, start, end))


def overview_tab(source, filters):
    where, parameters = filter_sql(*filters)
    summary = query(f"""
        SELECT count(*) AS videos, count(DISTINCT channel_id) AS channels, median(days_trending) AS median_days,
               100 * avg(CAST(date_diff('day', CAST(published_at AS DATE), first_trending_date) <= 1 AS INTEGER))
                   AS pct_by_next_day
        FROM trending_videos WHERE {where}""", parameters, source["key"]).iloc[0]
    columns = st.columns(4)
    columns[0].metric("Trending videos", f"{summary['videos']:,.0f}")
    columns[1].metric("Channels", f"{summary['channels']:,.0f}")
    columns[2].metric("Median days on the list", f"{summary['median_days']:.0f}")
    columns[3].metric("Trended within a day of upload", f"{summary['pct_by_next_day']:.1f}%")

    by_country = query(f"""
        SELECT country, count(*) AS videos, median(days_trending) AS median_days
        FROM trending_videos WHERE {where} GROUP BY country ORDER BY country""", parameters, source["key"])
    left, right = st.columns(2)
    left.plotly_chart(px.bar(by_country, x="country", y="videos", color="country", color_discrete_map=COUNTRY_COLORS,
                             labels=AXIS_LABELS, title="Trending videos by country").update_layout(showlegend=False),
                      width="stretch")
    right.plotly_chart(px.bar(by_country, x="country", y="median_days", color="country",
                              color_discrete_map=COUNTRY_COLORS, labels=AXIS_LABELS,
                              title="Median days on the list").update_layout(showlegend=False),
                       width="stretch")

    if source["key"] != BUILT_IN:
        st.caption("The AI insight report covers the built-in data, so it is not shown for uploads.")
        return
    st.subheader("AI insight report")
    st.caption("Written by an LLM from 10 SQL queries. Every number was checked against the queries by code; "
               "sentences were checked by a second LLM pass, which can miss errors. Any unverified sentence is listed "
               "at the end. It covers all data and ignores the filters.")
    st.markdown(read_app_file("insight_report.md"))


def trends_tab(source, filters):
    where, parameters = filter_sql(*filters)
    # Partial first and last weeks would show as sudden drops, so only weeks fully inside the data are charted.
    weekly = query(f"""
        WITH data_range AS (SELECT min(first_trending_date) AS first_day, max(first_trending_date) AS last_day
                            FROM trending_videos)
        SELECT date_trunc('week', first_trending_date) AS week, country, count(*) AS new_videos
        FROM trending_videos, data_range
        WHERE {where} AND date_trunc('week', first_trending_date) >= first_day
          AND date_trunc('week', first_trending_date) + INTERVAL 6 DAY <= last_day
        GROUP BY ALL ORDER BY week""", parameters, source["key"])
    st.plotly_chart(px.line(weekly, x="week", y="new_videos", color="country", color_discrete_map=COUNTRY_COLORS,
                            labels=AXIS_LABELS, title="New videos entering the trending list per week"),
                    width="stretch")

    # Days on the list are whole numbers, so category medians mostly tie at 3 or 6; the mean shows the differences.
    by_category = query(f"""
        SELECT category, country, round(avg(days_trending), 1) AS mean_days, count(*) AS videos
        FROM trending_videos WHERE {where} GROUP BY ALL HAVING count(*) >= 100 ORDER BY mean_days""", parameters, source["key"])
    st.plotly_chart(px.bar(by_category, x="mean_days", y="category", color="country", barmode="group",
                           orientation="h", color_discrete_map=COUNTRY_COLORS, height=600, labels=AXIS_LABELS,
                           title="Average days on the list by category (categories with 100+ videos)"),
                    width="stretch")

    if source["key"] != BUILT_IN:
        st.caption("Unusual spikes with AI notes are computed for the built-in data only.")
        return
    st.subheader("Unusual spikes")
    st.caption("Days when a category got far more new trending videos than in the previous 28 days (robust z-score "
               "of 4 or more). The 20 largest have a short AI note on what the titles had in common, with the top "
               "titles shown so it can be checked.")
    countries, categories, start, end = filters
    anomalies = read_app_file("anomalies.csv")
    anomalies["trending_date"] = pd.to_datetime(anomalies["trending_date"]).dt.date
    shown = anomalies[anomalies["country"].isin(countries) & anomalies["category"].isin(categories)
                      & anomalies["trending_date"].between(start, end)]
    st.dataframe(shown[["trending_date", "country", "category", "new_videos", "baseline_median", "robust_z",
                        "explanation", "top_titles"]], hide_index=True, width="stretch")


def publish_time_tab(source, filters):
    countries, categories, start, end = filters
    country = st.selectbox("Country", countries, format_func=country_label)
    slots = query(f"""
        SELECT isodow({LOCAL_TIMEZONE_SQL}) AS weekday, hour({LOCAL_TIMEZONE_SQL}) AS hour, count(*) AS videos
        FROM trending_videos
        WHERE country = ? AND category IN (SELECT unnest(?)) AND first_trending_date BETWEEN ? AND ?
        GROUP BY ALL""", (country, categories, start, end), source["key"])
    grid = (slots.pivot(index="weekday", columns="hour", values="videos")
            .reindex(index=range(1, 8), columns=range(24)).fillna(0))
    grid = 100 * grid / grid.to_numpy().sum()
    figure = px.imshow(grid, x=[f"{hour:02d}" for hour in range(24)], y=WEEKDAYS, color_continuous_scale="Blues",
                       labels={"x": "Upload hour (local time)", "y": "", "color": "% of videos"}, aspect="auto",
                       title=f"When trending videos in {UPLOAD_COUNTRIES[country][0]} were uploaded")
    st.plotly_chart(figure, width="stretch")
    st.info("This shows when trending videos were uploaded, not whether a time slot helps. In the project's analysis "
            "of India, the US and the UK, the "
            "channel explained over 200 times as much of a video's views as its upload hour; once channel and "
            "category were accounted for, hour effects stayed between -11% and +14%. See notebooks/06_publish_time.ipynb.")


CATEGORY_MIX_SQL = """
    SELECT country, category, 100.0 * count(*) / sum(count(*)) OVER (PARTITION BY country) AS pct_of_videos
    FROM trending_videos WHERE {where} GROUP BY country, category"""


def countries_tab(source, filters):
    if source["key"] != BUILT_IN:
        upload_countries_tab(source, filters)
        return
    where, parameters = filter_sql(*filters)
    mix = query(CATEGORY_MIX_SQL.format(where=where), parameters)
    top_categories = mix.groupby("category")["pct_of_videos"].mean().nlargest(10).index
    st.plotly_chart(px.bar(mix[mix["category"].isin(top_categories)], x="pct_of_videos", y="category",
                           color="country", barmode="group", orientation="h", color_discrete_map=COUNTRY_COLORS,
                           labels=AXIS_LABELS, height=550, title="Category mix: % of each country's trending videos"),
                    width="stretch")
    overlap = query(f"""
        WITH filtered AS (SELECT country, video_id FROM trending_videos WHERE {where})
        SELECT a.country AS country, b.country AS also_trending_in, count(*) AS shared_videos,
               round(100.0 * count(*) / any_value(totals.videos), 1) AS pct_of_country_videos
        FROM filtered AS a JOIN filtered AS b ON a.video_id = b.video_id AND a.country <> b.country
        JOIN (SELECT country, count(*) AS videos FROM filtered GROUP BY country) AS totals ON totals.country = a.country
        GROUP BY a.country, b.country ORDER BY a.country, b.country""", parameters)
    st.subheader("Videos that trended in more than one country")
    st.dataframe(overlap, hide_index=True, width="stretch")
    st.caption("The US and UK share about half their trending videos; India shares about 2% with either.")


def upload_countries_tab(source, filters):
    """Compare the uploaded country with the built-in countries, over each one's full period."""
    countries, categories, start, end = filters
    upload_label = f"{countries[0]} (upload)"
    where, parameters = filter_sql(*filters)
    built_in_where, built_in_parameters = filter_sql(COUNTRIES, categories, "2000-01-01", "2100-01-01")
    mix = pd.concat([
        query(CATEGORY_MIX_SQL.format(where=where), parameters, source["key"]).assign(country=upload_label),
        query(CATEGORY_MIX_SQL.format(where=built_in_where), built_in_parameters),
    ])
    top_categories = mix.groupby("category")["pct_of_videos"].mean().nlargest(10).index
    st.plotly_chart(px.bar(mix[mix["category"].isin(top_categories)], x="pct_of_videos", y="category",
                           color="country", barmode="group", orientation="h",
                           color_discrete_map={**COUNTRY_COLORS, upload_label: SECONDARY_INK}, labels=AXIS_LABELS,
                           height=600, title="Category mix: your upload against the built-in countries"),
                    width="stretch")
    st.caption("The built-in countries cover 12 Aug 2020 to 15 Apr 2024; your upload covers its own dates, so "
               "differences can come from timing as well as from the market.")
    uploaded_ids = query(f"SELECT DISTINCT video_id FROM trending_videos WHERE {where}", parameters, source["key"])
    built_in_ids = query("SELECT country, video_id FROM trending_videos")
    shared = built_in_ids[built_in_ids["video_id"].isin(uploaded_ids["video_id"])].groupby("country").size()
    overlap = pd.DataFrame({
        "also_trending_in": COUNTRIES,
        "shared_videos": [int(shared.get(country, 0)) for country in COUNTRIES],
    }).assign(pct_of_upload_videos=lambda table: (100 * table["shared_videos"] / len(uploaded_ids)).round(1))
    st.subheader("Uploaded videos that also trended in the built-in countries")
    st.dataframe(overlap, hide_index=True, width="stretch")


@st.cache_data
def read_example_answers():
    return load_example_answers()


@st.cache_data(show_spinner=False)
def cached_answer(question, source_key, schema_notes):
    from streampulse.ask import answer_question
    return answer_question(question, database(source_key).cursor(), schema_notes)


def ask_tab(source):
    st.write("Ask a question about the trending data or the Netflix catalog. An LLM writes the SQL, which runs "
             "read-only on the data; the answer's numbers are checked against the result.")
    saved_answers, saved_on = read_example_answers()
    if source["key"] == BUILT_IN:
        examples = EXAMPLE_QUESTIONS
    else:
        examples = [
            "Which 5 channels spent the most days on the trending list?",
            "What is the median number of days a video stays trending in each category?",
            "How many new videos entered the trending list each month?",
        ]
    example = st.selectbox("Try an example", [""] + examples)
    question = st.text_input("Your question", value=example)
    if not question:
        return
    if source["key"] == BUILT_IN and question in saved_answers:
        result = saved_answers[question]
        chart_choice = choose_chart(result["rows"])
        result["chart"] = build_chart(result["rows"], chart_choice) if chart_choice else None
        st.caption(f"Saved answer, made with the same pipeline on {saved_on}. Edit the question to ask live.")
    else:
        with st.spinner("Writing and running the query..."):
            try:
                result = cached_answer(question, source["key"], source["notes"])
            except RateLimitError as limit_error:
                st.warning(rate_limit_message(limit_error))
                return
    if result["error"]:
        st.error(result["error"])
    else:
        st.markdown(result["answer"])
        if result["unsupported_numbers"]:
            st.warning("These numbers in the answer were not found in the query result: "
                       + ", ".join(result["unsupported_numbers"]))
        if result["chart"] is not None:
            st.plotly_chart(result["chart"], width="stretch")
        st.dataframe(result["rows"], hide_index=True, width="stretch")
        if result["truncated"]:
            st.caption("Only the first 200 rows are shown.")
    with st.expander("SQL"):
        st.code(result["sql"], language="sql")
    st.caption("Measured accuracy: 96.7% (58 of 60) on the project's test questions about the built-in data "
               "(evals/text_to_sql_report.md).")


def pick_video(key):
    videos = read_app_file("title_optimizer_videos.parquet")
    country = st.selectbox("Country", COUNTRIES, format_func=country_label, key=f"{key}_country")
    in_country = videos[videos["country"] == country].sort_values("title").reset_index(drop=True)
    position = st.selectbox("Video (Jul 2023 to Apr 2024, not seen in training)", in_country.index,
                            format_func=lambda row: in_country.loc[row, "title"], key=f"{key}_video")
    return in_country.loc[position]


def virality_tab():
    st.write("Predicts, on the morning a video first reaches the trending list, whether it will stay longer than "
             "most (7+ days in the US and UK, 5+ in India) and for how many days.")
    video = pick_video("virality")
    classifier, regressor, categories = virality_models()
    matrix = feature_matrix(pd.DataFrame([video]), categories)
    probability = classifier.predict(matrix)[0]
    predicted_days = regressor.predict(matrix)[0]
    columns = st.columns(3)
    columns[0].metric("Chance of a long run", f"{100 * probability:.0f}%")
    columns[1].metric("Predicted days on the list", f"{predicted_days:.1f}")
    columns[2].metric("Actual days on the list", f"{video['days_trending']:.0f}",
                      "long run" if video["long_runner"] else "not a long run", delta_color="off")
    contributions = pd.Series(classifier.predict(matrix, pred_contrib=True)[0][:-1], index=FEATURE_COLUMNS)
    top = contributions.reindex(contributions.abs().nlargest(10).index)[::-1]
    top.index = top.index.str.replace("_", " ")
    figure = px.bar(x=top.values, y=top.index, orientation="h", color=np.where(top.values > 0, "toward a long run",
                    "toward a short run"), color_discrete_map={"toward a long run": "#2a78d6", "toward a short run": "#e34948"},
                    labels={"x": "SHAP value (log-odds)", "y": "", "color": ""}, title="What drove this prediction")
    st.plotly_chart(figure, width="stretch")
    st.caption("Test ROC-AUC 0.790 against 0.698 for channel history alone. In 2023-2024 US and UK videos stayed "
               "longer than in training, so probabilities there run low. See evals/virality_report.md.")


@st.cache_data(show_spinner=False)
def cached_title_suggestions(video_id, country, title):
    from streampulse.title_optimizer import optimize_title
    videos = read_app_file("title_optimizer_videos.parquet")
    video = videos[(videos["video_id"] == video_id) & (videos["country"] == country)].iloc[0].copy()
    video["title"] = title
    return optimize_title(video, virality_models())


def title_optimizer_tab():
    st.write("Suggests three alternative titles and scores each with the virality model, keeping everything else "
             "about the video the same. Title and tag features carry only about 6% of the model's SHAP importance, so "
             "expect small differences; use it to compare options, not to make a video go viral.")
    video = pick_video("titles")
    title = st.text_input("Title to improve", value=video["title"], max_chars=100)
    if not st.button("Suggest titles"):
        return
    with st.spinner("Asking the LLM and scoring each title..."):
        try:
            scores = cached_title_suggestions(video["video_id"], video["country"], title)
        except RateLimitError as limit_error:
            st.warning(rate_limit_message(limit_error))
            return
    shown = scores.assign(
        long_run_chance=(100 * scores["long_run_probability"]).round(1).astype(str) + "%",
        change=(100 * scores["change_in_probability"]).round(2).map("{:+.2f} pts".format),
        problems=scores["problems"].map(lambda problems: "; ".join(problems) if problems else ""),
    )[["source", "title", "long_run_chance", "change", "reason", "problems"]]
    st.dataframe(shown, hide_index=True, width="stretch")
    st.caption("Suggestions flagged in the problems column add numbers or format labels the original did not have. "
               "Check every suggestion before using it.")


def topics_tab():
    topics = read_app_file("topics.csv")
    trends = read_app_file("topic_trends.parquet")
    named = topics[topics["topic"] >= 0].sort_values("videos", ascending=False)
    st.caption(f"{len(named)} topics found by clustering title embeddings (BERTopic) and named by an LLM. "
               f"{100 * topics.loc[topics['topic'] == -1, 'videos'].sum() / topics['videos'].sum():.0f}% of titles fit "
               "no topic, mostly Indian TV serial episodes.")
    country = st.radio("Country", ["All"] + COUNTRIES, horizontal=True,
                       format_func=lambda code: code if code == "All" else country_label(code))
    in_country = trends if country == "All" else trends[trends["country"] == country]
    sizes = (in_country[in_country["topic"] >= 0].groupby("name")["new_videos"].sum().nlargest(20).iloc[::-1])
    st.plotly_chart(px.bar(x=sizes.values, y=sizes.index, orientation="h", height=600,
                           color_discrete_sequence=["#2a78d6"], labels={"x": "Trending videos", "y": ""},
                           title="Largest topics"), width="stretch")
    chosen = st.multiselect("Topics over time", named["name"].tolist(), default=named["name"].head(3).tolist())
    monthly = in_country[in_country["name"].isin(chosen)].groupby(["month", "name"])["new_videos"].sum().reset_index()
    st.plotly_chart(px.line(monthly, x="month", y="new_videos", color="name", labels=AXIS_LABELS,
                            title="New trending videos per month"), width="stretch")
    st.info("YouTube Shorts left the US and UK trending lists around April 2022 and India's on 6 October 2022, "
            "which is why Shorts topics drop to zero. See notebooks/13_topics.ipynb.")


st.title("StreamPulse")
st.caption("What trends on YouTube in India, the US and the UK, how long it lasts, and how markets differ, "
           "with AI features built on top.")
source = choose_data_source()
filters = sidebar_filters(source)
tabs = st.tabs(["Overview", "Trends", "Publish time", "Countries", "Ask the Data", "Virality predictor",
                "Title optimizer", "Topics"])
with tabs[0]:
    overview_tab(source, filters)
with tabs[1]:
    trends_tab(source, filters)
with tabs[2]:
    publish_time_tab(source, filters)
with tabs[3]:
    countries_tab(source, filters)
with tabs[4]:
    ask_tab(source)
with tabs[5]:
    virality_tab()
with tabs[6]:
    title_optimizer_tab()
with tabs[7]:
    topics_tab()
