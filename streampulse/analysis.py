import numpy as np
import pandas as pd
from scipy import stats

DATA_START = "2020-08-12"
DATA_END = "2024-04-15"
# On this day India's daily list stopped holding a steady 200 videos and likes per view dropped from about
# 60 to about 42 per 1,000 views in every category. The cause is not in the data, so India is split in two.
INDIA_LIST_CHANGE = "2022-10-06"


def load_time_to_trend(connection):
    """One row per video and country with days from upload to first trending day and the UTC upload hour."""
    # Videos first seen on the first day of data may have started trending earlier, so they are excluded.
    return connection.execute(f"""
        SELECT
            country,
            video_id,
            category,
            hour(published_at) AS upload_hour_utc,
            date_diff('day', CAST(published_at AS DATE), first_trending_date) AS days_to_trend,
            CAST(date_diff('day', CAST(published_at AS DATE), first_trending_date) <= 1 AS INTEGER)
                AS trended_by_next_day
        FROM trending_videos
        WHERE first_trending_date > DATE '{DATA_START}'
    """).df()


def load_trending_durations(connection):
    """One row per video and country with days on the trending list and whether it left before the data ends."""
    # Videos still trending on the last day are right-censored (left_list = 0). Videos already trending
    # on the first day are excluded, since their earlier days are unknown.
    return connection.execute(f"""
        SELECT
            country,
            video_id,
            category,
            days_trending,
            CAST(last_trending_date < DATE '{DATA_END}' AS INTEGER) AS left_list
        FROM trending_videos
        WHERE first_trending_date > DATE '{DATA_START}'
    """).df()


def load_first_day_engagement(connection):
    """One row per video and country with views, likes and comments on its first trending day."""
    # Likes and comments per view fall as a video ages, and videos stay on the list longer in some
    # countries than others, so every video is measured at the same point in its life.
    return connection.execute(f"""
        WITH first_day AS (
            SELECT
                country,
                video_id,
                category,
                trending_date AS first_trending_date,
                view_count AS views,
                likes,
                comment_count AS comments
            FROM trending
            QUALIFY row_number() OVER (PARTITION BY country, video_id ORDER BY trending_date) = 1
        )
        SELECT
            *,
            1000.0 * likes / views AS likes_per_1k_views,
            1000.0 * comments / views AS comments_per_1k_views,
            CASE
                WHEN country <> 'IN' THEN country
                WHEN first_trending_date < DATE '{INDIA_LIST_CHANGE}' THEN 'IN before Oct 2022'
                ELSE 'IN from Oct 2022'
            END AS country_period
        FROM first_day
        WHERE first_trending_date > DATE '{DATA_START}'
          AND views > 0
    """).df()


def load_publish_slots(connection):
    """One row per completed trending run with local upload weekday and hour, peak views and channel strength."""
    # Channel strength is the channel's average log peak views on its other trending videos in the same
    # country. It stands in for audience size, which the data does not record. Runs cut off at either end
    # of the data are excluded because their peak views are incomplete.
    return connection.execute(f"""
        WITH local_upload AS (
            SELECT
                *,
                timezone(
                    CASE country WHEN 'IN' THEN 'Asia/Kolkata' WHEN 'US' THEN 'America/New_York' ELSE 'Europe/London' END,
                    published_at AT TIME ZONE 'UTC'
                ) AS published_local
            FROM trending_videos
            WHERE first_trending_date > DATE '{DATA_START}'
              AND last_trending_date < DATE '{DATA_END}'
              AND peak_views > 0
        )
        SELECT
            country,
            video_id,
            channel_id,
            category,
            days_trending,
            peak_views,
            ln(peak_views) AS log_peak_views,
            isodow(published_local) AS upload_weekday,
            hour(published_local) AS upload_hour,
            count(*) OVER channel AS channel_trending_videos,
            (sum(ln(peak_views)) OVER channel - ln(peak_views)) / nullif(count(*) OVER channel - 1, 0)
                AS channel_strength,
            CASE
                WHEN country <> 'IN' THEN country
                WHEN first_trending_date < DATE '{INDIA_LIST_CHANGE}' THEN 'IN before Oct 2022'
                ELSE 'IN from Oct 2022'
            END AS country_period
        FROM local_upload
        WINDOW channel AS (PARTITION BY country, channel_id)
    """).df()


def median_with_ci(values, confidence=0.95):
    """Median with a distribution-free confidence interval taken from the order statistics."""
    sorted_values = np.sort(values.dropna().to_numpy())
    n_values = len(sorted_values)
    z_score = stats.norm.ppf(0.5 + confidence / 2)
    lower_rank = max(int(np.floor(n_values / 2 - z_score * np.sqrt(n_values) / 2)), 0)
    upper_rank = min(int(np.ceil(n_values / 2 + z_score * np.sqrt(n_values) / 2)), n_values - 1)
    return pd.Series({
        "videos": n_values,
        "median": np.median(sorted_values),
        "ci_low": sorted_values[lower_rank],
        "ci_high": sorted_values[upper_rank],
    })


def _exponentiated_terms(fitted_model, term_contains):
    params = fitted_model.params[fitted_model.params.index.str.contains(term_contains, regex=False)]
    conf_int = fitted_model.conf_int().loc[params.index]
    return np.exp(params), np.exp(conf_int[0]), np.exp(conf_int[1]), fitted_model.pvalues.loc[params.index]


def odds_ratios(fitted_model, term_contains):
    """Odds ratios with 95% confidence intervals for the model terms whose name contains the given text."""
    ratio, ci_low, ci_high, p_value = _exponentiated_terms(fitted_model, term_contains)
    return pd.DataFrame({"odds_ratio": ratio, "ci_low": ci_low, "ci_high": ci_high, "p_value": p_value})


def percent_differences(fitted_model, term_contains):
    """For a model of log(outcome), the percent difference in the outcome for each matching term, with 95% CI."""
    ratio, ci_low, ci_high, p_value = _exponentiated_terms(fitted_model, term_contains)
    return pd.DataFrame({
        "pct_difference": 100 * (ratio - 1),
        "ci_low": 100 * (ci_low - 1),
        "ci_high": 100 * (ci_high - 1),
        "p_value": p_value,
    })
