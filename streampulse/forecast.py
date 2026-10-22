import warnings

import numpy as np
import pandas as pd
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

HORIZON_DAYS = 30
WEEK = 7


def load_daily_views_gained(connection, country, category):
    """Daily views gained by a category's trending videos in one country, with missing days interpolated."""
    # A video's gain is its view increase since its previous list appearance. When a day is missing from
    # the data, the increase covers two days, so it is spread evenly over the gap.
    daily = connection.execute("""
        WITH ordered AS (
            SELECT
                trending_date,
                view_count,
                lag(view_count) OVER video AS previous_views,
                lag(trending_date) OVER video AS previous_date
            FROM trending
            WHERE country = ? AND category = ?
            WINDOW video AS (PARTITION BY video_id ORDER BY trending_date)
        )
        SELECT
            trending_date,
            sum(greatest(view_count - previous_views, 0) / date_diff('day', previous_date, trending_date)) AS views_gained
        FROM ordered
        WHERE previous_views IS NOT NULL
        GROUP BY trending_date
        ORDER BY trending_date
    """, [country, category]).df()
    views_gained = daily.set_index(pd.to_datetime(daily["trending_date"]))["views_gained"].asfreq("D")
    return views_gained.interpolate()


def naive_forecast(train, horizon=HORIZON_DAYS):
    """Repeat the last observed value."""
    return np.repeat(train.iloc[-1], horizon)


def seasonal_naive_forecast(train, horizon=HORIZON_DAYS):
    """Repeat the last observed week."""
    return np.resize(train.iloc[-WEEK:].to_numpy(), horizon)


def weekday_average_forecast(train, horizon=HORIZON_DAYS, weeks=4):
    """Average of the same weekday over the last few weeks."""
    recent = train.iloc[-WEEK * weeks:]
    weekday_profile = recent.groupby(recent.index.dayofweek).mean()
    future_dates = pd.date_range(train.index[-1] + pd.Timedelta(1, "D"), periods=horizon)
    return weekday_profile.loc[future_dates.dayofweek].to_numpy()


def ets_forecast(train, horizon=HORIZON_DAYS):
    """Holt-Winters with a damped trend and weekly seasonality, fitted on log views."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model = ExponentialSmoothing(
            np.log(train), trend="add", damped_trend=True, seasonal="add", seasonal_periods=WEEK
        ).fit()
    return np.exp(model.forecast(horizon)).to_numpy()


def fit_sarima(train, history_days=365):
    """SARIMA(1,1,1)(0,1,1,7) on log views over the most recent year of the training data."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        warnings.simplefilter("ignore", UserWarning)
        return SARIMAX(np.log(train.iloc[-history_days:]), order=(1, 1, 1), seasonal_order=(0, 1, 1, WEEK)).fit(disp=False)


def sarima_forecast(train, horizon=HORIZON_DAYS):
    """Point forecast from fit_sarima, back on the views scale."""
    return np.exp(fit_sarima(train).forecast(horizon)).to_numpy()


FORECASTERS = {
    "naive": naive_forecast,
    "seasonal naive": seasonal_naive_forecast,
    "4-week weekday average": weekday_average_forecast,
    "Holt-Winters": ets_forecast,
    "SARIMA": sarima_forecast,
}


def mape(actual, predicted):
    """Mean absolute percentage error, in percent."""
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    return 100 * np.mean(np.abs((actual - predicted) / actual))


def total_error(actual, predicted):
    """Percent error of the forecast total over the whole horizon."""
    return 100 * (np.sum(predicted) - np.sum(actual)) / np.sum(actual)


def rolling_origin_evaluation(series, origins, forecasters=FORECASTERS, horizon=HORIZON_DAYS):
    """Fit each forecaster on data up to each origin and score it on the following horizon."""
    rows = []
    for origin in origins:
        train = series.loc[:origin]
        test = series.loc[origin + pd.Timedelta(1, "D"): origin + pd.Timedelta(horizon, "D")]
        for name, forecaster in forecasters.items():
            predicted = forecaster(train, horizon)
            rows.append({
                "origin": origin,
                "model": name,
                "mape": mape(test, predicted),
                "total_error_pct": total_error(test, predicted),
            })
    return pd.DataFrame(rows)
