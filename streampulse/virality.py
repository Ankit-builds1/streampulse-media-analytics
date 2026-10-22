import numpy as np
import pandas as pd

from streampulse.analysis import DATA_END, DATA_START, INDIA_LIST_CHANGE
from streampulse.database import connect
from streampulse.load import PROJECT_ROOT
from streampulse.titles import TITLE_FEATURES, add_title_features

FEATURES_PATH = PROJECT_ROOT / "data" / "processed" / "virality_features.parquet"
# Runs are split by the date they first trended, so the model is always tested on videos newer than any it saw.
TRAIN_END = "2022-12-31"
VALIDATION_END = "2023-06-30"
LONG_RUN_TOP_SHARE = 0.25

NUMERIC_FEATURES = [
    "days_to_trend",
    "upload_hour_local",
    "log_first_day_views",
    "first_day_likes_per_1k_views",
    "first_day_comments_per_1k_views",
    "tag_count",
    "channel_prior_runs",
    "channel_prior_mean_days",
    "channel_prior_long_run_rate",
    "channel_prior_mean_log_peak_views",
    "sentiment",
    *TITLE_FEATURES,
]
CATEGORICAL_FEATURES = ["country", "category", "upload_weekday_local", "sentiment_label", "india_after_list_change"]


def load_runs(connection):
    """One row per completed trending run with what was known on its first trending day."""
    # Runs cut off at either end of the data have unknown length, so they are left out.
    return connection.execute(f"""
        WITH first_day AS (
            SELECT country, video_id, view_count, likes, comment_count, tags
            FROM trending
            QUALIFY row_number() OVER (PARTITION BY country, video_id ORDER BY trending_date) = 1
        )
        SELECT
            runs.country,
            runs.video_id,
            runs.channel_id,
            runs.category,
            runs.title,
            runs.first_trending_date,
            runs.last_trending_date,
            runs.days_trending,
            runs.peak_views,
            date_diff('day', CAST(runs.published_at AS DATE), runs.first_trending_date) AS days_to_trend,
            timezone(
                CASE runs.country WHEN 'IN' THEN 'Asia/Kolkata' WHEN 'US' THEN 'America/New_York' ELSE 'Europe/London' END,
                runs.published_at AT TIME ZONE 'UTC'
            ) AS published_local,
            first_day.view_count AS first_day_views,
            first_day.likes AS first_day_likes,
            first_day.comment_count AS first_day_comments,
            first_day.tags
        FROM trending_videos AS runs
        JOIN first_day USING (country, video_id)
        WHERE runs.first_trending_date > DATE '{DATA_START}'
          AND runs.last_trending_date < DATE '{DATA_END}'
    """).df()


def add_split(runs):
    """Label each run train, validation or test by the date it first trended."""
    first_day = pd.to_datetime(runs["first_trending_date"])
    split = np.select(
        [first_day <= TRAIN_END, first_day <= VALIDATION_END],
        ["train", "validation"],
        default="test",
    )
    return runs.assign(split=split)


def long_run_threshold(days_trending, top_share=LONG_RUN_TOP_SHARE):
    """Shortest run length that no more than top_share of runs reach, e.g. 7 days if 24% of runs last 7+ days."""
    return min(days for days in np.unique(days_trending) if (days_trending >= days).mean() <= top_share)


def add_targets(runs):
    """Add the long-runner flag, with each country's threshold set from training runs only."""
    training_runs = runs[runs["split"] == "train"]
    threshold_by_country = training_runs.groupby("country")["days_trending"].apply(long_run_threshold)
    thresholds = runs["country"].map(threshold_by_country)
    return runs.assign(
        long_run_threshold_days=thresholds,
        long_runner=(runs["days_trending"] >= thresholds).astype(int),
    )


def add_channel_history(runs):
    """Add the channel's record in the same country from runs that ended before this run started.

    Only finished runs count, so nothing that happens on or after a run's first trending day can leak into its
    features. A channel with no earlier finished runs gets 0 prior runs and missing averages.
    """
    finished = runs.sort_values("last_trending_date").assign(
        log_peak_views=np.log(runs["peak_views"].astype(float))
    )
    by_channel = finished.groupby(["country", "channel_id"])
    history = finished[["country", "channel_id", "last_trending_date"]].assign(
        channel_prior_runs=by_channel.cumcount() + 1,
        total_days=by_channel["days_trending"].cumsum(),
        total_long_runs=by_channel["long_runner"].cumsum(),
        total_log_peak_views=by_channel["log_peak_views"].cumsum(),
    )
    # Several runs can end on the same day; keep the running totals after the last of them.
    history = history.drop_duplicates(["country", "channel_id", "last_trending_date"], keep="last")

    with_history = pd.merge_asof(
        runs.sort_values("first_trending_date"),
        history.sort_values("last_trending_date"),
        left_on="first_trending_date",
        right_on="last_trending_date",
        by=["country", "channel_id"],
        allow_exact_matches=False,
        suffixes=("", "_history"),
    )
    prior_runs = with_history["channel_prior_runs"].fillna(0)
    return with_history.assign(
        channel_prior_runs=prior_runs,
        channel_prior_mean_days=with_history["total_days"] / prior_runs.where(prior_runs > 0),
        channel_prior_long_run_rate=with_history["total_long_runs"] / prior_runs.where(prior_runs > 0),
        channel_prior_mean_log_peak_views=with_history["total_log_peak_views"] / prior_runs.where(prior_runs > 0),
    ).drop(columns=["last_trending_date_history", "total_days", "total_long_runs", "total_log_peak_views"])


def add_first_day_features(runs):
    """Add the features that describe the video on its first trending day."""
    published_local = pd.to_datetime(runs["published_local"])
    first_day_views = runs["first_day_views"].astype(float)
    with_features = runs.assign(
        upload_hour_local=published_local.dt.hour,
        upload_weekday_local=published_local.dt.day_name(),
        # Hidden view counters are missing; log of a missing value stays missing.
        log_first_day_views=np.log(first_day_views.where(first_day_views > 0)),
        first_day_likes_per_1k_views=1000 * runs["first_day_likes"].astype(float) / first_day_views.where(first_day_views > 0),
        first_day_comments_per_1k_views=1000 * runs["first_day_comments"].astype(float) / first_day_views.where(first_day_views > 0),
        tag_count=runs["tags"].fillna("").str.split("|").map(lambda tags: len([tag for tag in tags if tag])),
        india_after_list_change=(
            (runs["country"] == "IN") & (pd.to_datetime(runs["first_trending_date"]) >= INDIA_LIST_CHANGE)
        ).map({True: "yes", False: "no"}),
    )
    return add_title_features(with_features)


def build_features(connection):
    """The full modelling table: features known on the first trending day, both targets and the time split."""
    runs = add_targets(add_split(load_runs(connection)))
    runs = add_channel_history(runs)
    runs = add_first_day_features(runs)
    return runs.sort_values(["first_trending_date", "country", "video_id"]).reset_index(drop=True)


if __name__ == "__main__":
    with connect() as connection:
        features = build_features(connection)
    features.to_parquet(FEATURES_PATH, index=False)
    print(f"{len(features):,} runs saved to {FEATURES_PATH}")
    print(features.groupby("split").agg(
        runs=("video_id", "size"),
        first_day=("first_trending_date", "min"),
        last_day=("first_trending_date", "max"),
        long_runner_rate=("long_runner", "mean"),
    ))
    print(features.groupby("country")["long_run_threshold_days"].first())
