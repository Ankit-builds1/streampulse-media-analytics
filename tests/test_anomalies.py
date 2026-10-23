import pandas as pd

from streampulse.anomalies import add_robust_z_scores, flag_anomalies, parse_explanation


def daily_series(values, category="Music"):
    return pd.DataFrame({
        "country": "US",
        "category": category,
        "trending_date": pd.date_range("2023-01-01", periods=len(values)),
        "new_videos": values,
    })


def test_a_spike_after_a_quiet_month_is_flagged():
    scored = add_robust_z_scores(daily_series([3, 4, 3, 5, 4] * 6 + [20]))
    flags = flag_anomalies(scored)
    assert list(flags["new_videos"]) == [20]


def test_the_day_itself_is_not_in_its_own_baseline():
    scored = add_robust_z_scores(daily_series([3, 4, 3, 5, 4] * 6 + [20]))
    assert scored["baseline_median"].iloc[-1] == 4


def test_too_little_history_gives_no_score():
    scored = add_robust_z_scores(daily_series([3] * 10))
    assert scored["robust_z"].isna().all()


def test_small_bursts_in_quiet_categories_are_not_flagged():
    scored = add_robust_z_scores(daily_series([0, 1] * 15 + [6]))
    assert scored["robust_z"].iloc[-1] >= 3
    assert flag_anomalies(scored).empty


def test_series_are_scored_separately():
    two_categories = pd.concat([daily_series([3, 4] * 15 + [20]), daily_series([30, 40] * 15 + [35], "Sports")])
    flags = flag_anomalies(add_robust_z_scores(two_categories))
    assert list(flags["category"]) == ["Music"]


def test_parse_explanation_accepts_short_json():
    assert parse_explanation('{"explanation": "All titles cover one match."}') == "All titles cover one match."
    assert parse_explanation('Here it is: {"explanation": "A product launch."}') == "A product launch."


def test_parse_explanation_rejects_echoes_and_long_answers():
    assert parse_explanation("**Country:** US\n**Titles:** ...") is None
    assert parse_explanation('{"explanation": "' + "word " * 61 + '"}') is None
    assert parse_explanation('{"note": "wrong key"}') is None
