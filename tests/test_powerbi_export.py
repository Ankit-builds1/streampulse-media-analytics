import pandas as pd
import pytest

from streampulse.database import DATABASE_PATH
from streampulse.powerbi_export import build_tables, date_table


def test_date_table_weeks_start_on_monday_and_weekdays_sort_correctly():
    dates = date_table("2024-04-08", "2024-04-15")
    assert (dates["week_start"].dt.weekday == 0).all()
    assert dates.loc[dates["weekday"] == "Mon", "weekday_number"].unique().tolist() == [1]
    assert dates.loc[dates["weekday"] == "Sun", "weekday_number"].unique().tolist() == [7]


@pytest.fixture(scope="module")
def tables():
    if not DATABASE_PATH.exists():
        pytest.skip("build the database first: python -m streampulse.database")
    return build_tables()


def test_fact_table_flags_reproduce_the_findings(tables):
    runs = tables["fact_trending_runs"]
    known = runs[runs["full_run_known"] == 1]
    assert len(runs) == 173_596 and len(known) == 173_025
    next_day = 100 * known.groupby("country")["trended_by_next_day"].mean()
    assert next_day.round(1).to_dict() == {"GB": 57.2, "IN": 87.3, "US": 57.4}
    assert known.groupby("country")["days_trending"].median().to_dict() == {"GB": 6, "IN": 3, "US": 6}


def test_every_fact_key_has_a_matching_dimension_row(tables):
    runs = tables["fact_trending_runs"]
    assert runs["run_key"].is_unique
    assert set(runs["country"]) <= set(tables["dim_country"]["country"])
    assert set(runs["category"]) <= set(tables["dim_category"]["category"])
    assert set(runs["channel_id"]) <= set(tables["dim_channel"]["channel_id"])
    assert tables["dim_channel"]["channel_id"].is_unique
    dates = set(pd.to_datetime(tables["dim_date"]["date"]).dt.date)
    assert set(pd.to_datetime(runs["first_trending_date"]).dt.date) <= dates
