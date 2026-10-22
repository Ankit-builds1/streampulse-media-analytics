import numpy as np
import pandas as pd

DATA_START = "2020-08-12"


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
