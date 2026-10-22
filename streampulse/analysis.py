import numpy as np
import pandas as pd

DATA_START = "2020-08-12"
DATA_END = "2024-04-15"


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


def odds_ratios(fitted_model, term_contains):
    """Odds ratios with 95% confidence intervals for the model terms whose name contains the given text."""
    params = fitted_model.params[fitted_model.params.index.str.contains(term_contains, regex=False)]
    conf_int = fitted_model.conf_int().loc[params.index]
    return pd.DataFrame({
        "odds_ratio": np.exp(params),
        "ci_low": np.exp(conf_int[0]),
        "ci_high": np.exp(conf_int[1]),
        "p_value": fitted_model.pvalues.loc[params.index],
    })
