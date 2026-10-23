import json
import re

import numpy as np
import pandas as pd

from streampulse.analysis import DATA_START
from streampulse.database import connect
from streampulse.llm import complete
from streampulse.load import PROJECT_ROOT

ANOMALIES_PATH = PROJECT_ROOT / "reports" / "anomalies.csv"
BASELINE_DAYS = 28
MIN_BASELINE_DAYS = 21
Z_THRESHOLD = 4.0
# A jump from 1 to 4 new videos can have a huge z-score in a quiet category; require a real burst too.
MIN_NEW_VIDEOS = 8
# Turns the median absolute deviation into a standard-deviation scale for normally distributed data.
MAD_TO_STANDARD_DEVIATION = 1.4826

EXPLANATION_PROMPT = """You explain a spike in a YouTube trending list. You get the country, category, date, how many
new videos of that category entered the list that day compared with normal, and the titles and channels of those
videos. In one or two plain sentences, say what the titles have in common, for example one event, show, release or
channel. If most titles do not share one theme, say the spike is a mix of unrelated videos and name the largest
group, if any. Use only what the titles show; do not add or change facts, dates or numbers.
Do not repeat the input. Reply with only this JSON and nothing else: {"explanation": "<one or two sentences>"}"""
MAX_EXPLANATION_WORDS = 60


def load_daily_new_videos(connection):
    """New videos entering each country's list per day, per category, spread evenly over any missing days."""
    daily = connection.execute(f"""
        WITH list_days AS (
            SELECT country, trending_date,
                   date_diff('day', lag(trending_date) OVER (PARTITION BY country ORDER BY trending_date),
                             trending_date) AS days_since_previous_list
            FROM (SELECT DISTINCT country, trending_date FROM trending)
        ),
        new_videos AS (
            SELECT country, category, first_trending_date AS trending_date, count(*) AS new_videos
            FROM trending_videos
            WHERE first_trending_date > DATE '{DATA_START}'
            GROUP BY ALL
        )
        SELECT list_days.country, categories.category, list_days.trending_date,
               coalesce(new_videos.new_videos, 0) AS new_videos_raw,
               -- After a day with no list, two days of new videos land on one date.
               coalesce(new_videos.new_videos, 0) / list_days.days_since_previous_list AS new_videos
        FROM list_days
        CROSS JOIN (SELECT DISTINCT category FROM trending_videos) AS categories
        LEFT JOIN new_videos USING (country, category, trending_date)
        WHERE list_days.trending_date > DATE '{DATA_START}'
        ORDER BY list_days.country, categories.category, list_days.trending_date
    """).df()
    return daily


def add_robust_z_scores(daily):
    """Compare each day with the median of the previous 28 list days of the same country and category."""
    grouped = daily.groupby(["country", "category"])["new_videos"]
    # shift(1) keeps the day itself out of its own baseline, so nothing from the future or the spike leaks in.
    baseline_median = grouped.transform(
        lambda values: values.shift(1).rolling(BASELINE_DAYS, min_periods=MIN_BASELINE_DAYS).median())
    baseline_mad = grouped.transform(
        lambda values: values.shift(1).rolling(BASELINE_DAYS, min_periods=MIN_BASELINE_DAYS)
        .apply(lambda window: np.median(np.abs(window - np.median(window))), raw=True))
    # A category that is almost always 0 or 1 has a MAD of 0; a floor of 1 video keeps z-scores finite and sane.
    scale = MAD_TO_STANDARD_DEVIATION * baseline_mad.clip(lower=1)
    return daily.assign(baseline_median=baseline_median, robust_z=(daily["new_videos"] - baseline_median) / scale)


def flag_anomalies(scored):
    """Days with an unusually large burst of new videos in one category."""
    return scored[(scored["robust_z"] >= Z_THRESHOLD) & (scored["new_videos"] >= MIN_NEW_VIDEOS)].sort_values(
        "robust_z", ascending=False)


def titles_for_anomaly(connection, country, category, trending_date, limit=15):
    """Titles and channels of the videos that entered the list on an anomaly day."""
    return connection.execute("""
        SELECT title, channel_title
        FROM trending_videos
        WHERE country = ? AND category = ? AND first_trending_date = ?
        ORDER BY peak_views DESC
        LIMIT ?
    """, [country, category, trending_date, limit]).df()


def parse_explanation(reply):
    """The explanation text from a model reply, or None if it is not the requested short JSON answer."""
    json_object = re.search(r"\{.*\}", reply, re.DOTALL)
    try:
        explanation = str(json.loads(json_object.group(0))["explanation"]).strip() if json_object else None
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not explanation or len(explanation.split()) > MAX_EXPLANATION_WORDS:
        return None
    return explanation


def explain_anomaly(anomaly, titles, attempts=2):
    """A one or two sentence note on what the titles behind a spike have in common, or None if none was usable."""
    user_prompt = (
        f"Country: {anomaly['country']}. Category: {anomaly['category']}. Date: {anomaly['trending_date']:%Y-%m-%d}. "
        f"New videos that day: {anomaly['new_videos']:.0f}, against a usual {anomaly['baseline_median']:.0f}.\n"
        "Titles (channel):\n" + "\n".join(f"{row.title} ({row.channel_title})" for row in titles.itertuples())
    )
    for _ in range(attempts):
        explanation = parse_explanation(complete(EXPLANATION_PROMPT, user_prompt, light=True))
        if explanation:
            return explanation
    return None


def detect_and_explain(connection, explain_top=20):
    """Flag spikes in every country and category, and add an LLM note to the largest ones."""
    flags = flag_anomalies(add_robust_z_scores(load_daily_new_videos(connection)))
    explanations, evidence = {}, {}
    for index, anomaly in flags.head(explain_top).iterrows():
        titles = titles_for_anomaly(connection, anomaly["country"], anomaly["category"], anomaly["trending_date"])
        explanations[index] = explain_anomaly(anomaly, titles)
        # Kept next to the note so a reader can check it against what actually entered the list.
        evidence[index] = " || ".join(titles["title"].head(5))
    return flags.assign(explanation=pd.Series(explanations), top_titles=pd.Series(evidence)).reset_index(drop=True)


if __name__ == "__main__":
    with connect() as connection:
        anomalies = detect_and_explain(connection)
    anomalies.round({"new_videos": 1, "baseline_median": 1, "robust_z": 2}).to_csv(ANOMALIES_PATH, index=False)
    print(f"{len(anomalies)} spikes flagged; {anomalies['explanation'].notna().sum()} explained")
    for row in anomalies.dropna(subset=["explanation"]).itertuples():
        print(f"{row.country} {row.category} {row.trending_date:%Y-%m-%d} ({row.new_videos:.0f} vs {row.baseline_median:.0f}): "
              f"{row.explanation}")
