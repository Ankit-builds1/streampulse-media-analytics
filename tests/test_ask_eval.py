import datetime

import pandas as pd

from streampulse.ask_eval import is_refusal, results_match


def test_extra_columns_are_allowed():
    reference = pd.DataFrame({"country": ["IN"]})
    candidate = pd.DataFrame({"country": ["IN"], "videos": [78847]})
    assert results_match(reference, candidate, ordered=False)


def test_column_names_do_not_matter():
    reference = pd.DataFrame({"videos": [78847]})
    candidate = pd.DataFrame({"unique_trending_videos": [78847]})
    assert results_match(reference, candidate, ordered=False)


def test_rounding_and_percent_scale_are_allowed():
    reference = pd.DataFrame({"pct": [51.858]})
    assert results_match(reference, pd.DataFrame({"share_percent": [51.86]}), ordered=False)
    assert results_match(reference, pd.DataFrame({"share": [0.51858]}), ordered=False)


def test_wrong_value_fails():
    reference = pd.DataFrame({"titles": [1879]})
    assert not results_match(reference, pd.DataFrame({"titles": [2015]}), ordered=False)


def test_row_order_matters_only_when_ordered():
    reference = pd.DataFrame({"category": ["Gaming", "Music"]})
    swapped = pd.DataFrame({"category": ["Music", "Gaming"]})
    assert results_match(reference, swapped, ordered=False)
    assert not results_match(reference, swapped, ordered=True)


def test_different_row_count_fails():
    reference = pd.DataFrame({"category": ["Gaming", "Music"]})
    assert not results_match(reference, pd.DataFrame({"category": ["Gaming"]}), ordered=False)


def test_dates_compare_on_the_day():
    reference = pd.DataFrame({"last_date": [datetime.date(2024, 4, 15)]})
    candidate = pd.DataFrame({"max_date": [pd.Timestamp("2024-04-15")]})
    assert results_match(reference, candidate, ordered=False)


def test_refusal_detection():
    not_answerable = {"error": None, "rows": pd.DataFrame({"answer": ["not answerable from this data"]})}
    rejected = {"error": "Rejected: Only SELECT queries are allowed, got DELETE.", "rows": None}
    answered = {"error": None, "rows": pd.DataFrame({"videos": [5]})}
    assert is_refusal(not_answerable)
    assert is_refusal(rejected)
    assert not is_refusal(answered)
