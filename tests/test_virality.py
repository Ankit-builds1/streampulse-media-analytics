import numpy as np
import pandas as pd

from streampulse.virality import add_channel_history, long_run_threshold


def make_run(video_id, first_day, last_day, days, long_runner, channel_id="A", country="US", peak_views=1000):
    return {
        "country": country,
        "channel_id": channel_id,
        "video_id": video_id,
        "first_trending_date": pd.Timestamp(first_day),
        "last_trending_date": pd.Timestamp(last_day),
        "days_trending": days,
        "long_runner": long_runner,
        "peak_views": peak_views,
    }


def history_for(runs):
    return add_channel_history(pd.DataFrame(runs)).set_index("video_id")


def test_only_runs_that_ended_before_the_start_are_counted():
    history = history_for([
        make_run("ended_jan_5", "2021-01-01", "2021-01-05", days=5, long_runner=0),
        make_run("starts_jan_5", "2021-01-05", "2021-01-08", days=4, long_runner=0),
        make_run("starts_jan_6", "2021-01-06", "2021-01-12", days=7, long_runner=1),
        make_run("overlaps", "2021-01-03", "2021-01-04", days=2, long_runner=0),
    ])
    # "overlaps" ends on Jan 4, before "starts_jan_5" begins, so it is the only history "starts_jan_5" sees.
    assert history.loc["ended_jan_5", "channel_prior_runs"] == 0
    assert history.loc["overlaps", "channel_prior_runs"] == 0
    assert history.loc["starts_jan_5", "channel_prior_runs"] == 1
    assert history.loc["starts_jan_5", "channel_prior_mean_days"] == 2
    assert history.loc["starts_jan_6", "channel_prior_runs"] == 2
    assert history.loc["starts_jan_6", "channel_prior_mean_days"] == 3.5


def test_a_run_never_sees_itself_or_later_runs():
    history = history_for([
        make_run("first", "2021-01-01", "2021-01-07", days=7, long_runner=1),
        make_run("second", "2021-02-01", "2021-02-03", days=3, long_runner=0),
    ])
    assert history.loc["first", "channel_prior_runs"] == 0
    assert np.isnan(history.loc["first", "channel_prior_long_run_rate"])
    assert history.loc["second", "channel_prior_long_run_rate"] == 1


def test_other_channels_and_countries_are_kept_apart():
    history = history_for([
        make_run("channel_a_us", "2021-01-01", "2021-01-02", days=2, long_runner=0),
        make_run("channel_b_us", "2021-02-01", "2021-02-02", days=2, long_runner=0, channel_id="B"),
        make_run("channel_a_gb", "2021-02-01", "2021-02-02", days=2, long_runner=0, country="GB"),
    ])
    assert history.loc["channel_b_us", "channel_prior_runs"] == 0
    assert history.loc["channel_a_gb", "channel_prior_runs"] == 0


def test_long_run_threshold_is_the_shortest_length_reached_by_a_quarter_or_fewer():
    days = np.array([3] * 30 + [5] * 40 + [6] * 6 + [7] * 24)
    # 30% of runs reach 6+ days, 24% reach 7+ days, so the threshold is 7.
    assert long_run_threshold(days) == 7
