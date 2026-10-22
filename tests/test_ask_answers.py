import datetime

import pandas as pd
import pytest

from streampulse.ask import build_chart, choose_chart, unsupported_numbers


@pytest.mark.parametrize("answer, rows, question, expected", [
    ("India has the most, with 78,847 unique videos.", pd.DataFrame({"country": ["IN"], "videos": [78847]}), "", []),
    ("About 51.86% of US videos also trended in the UK.", pd.DataFrame({"share": [0.5186]}), "", []),
    ("Korean TV shows rate highest at 7.81.", pd.DataFrame({"genre": ["Korean TV Shows"], "rating": [7.8123]}), "", []),
    ("Views averaged 13.4 million a day.", pd.DataFrame({"views": [13_412_000]}), "", []),
    ("In 2019 Netflix added 2,015 titles.", pd.DataFrame({"titles": [2015]}), "How many titles were added in 2019?", []),
    ("The peak was on 2021-05-30.", pd.DataFrame({"day": [datetime.date(2021, 5, 30)], "views": [5]}), "", []),
    ("India has about 90,000 unique videos.", pd.DataFrame({"country": ["IN"], "videos": [78847]}), "", ["90,000"]),
    ("Korean TV shows rate 7.9 on average.", pd.DataFrame({"rating": [7.8123]}), "", ["7.9"]),
])
def test_unsupported_numbers(answer, rows, question, expected):
    assert unsupported_numbers(answer, rows, question) == expected


def test_no_chart_for_a_single_number():
    assert choose_chart(pd.DataFrame({"titles": [2015]})) is None


def test_no_chart_without_numbers():
    assert choose_chart(pd.DataFrame({"title": ["a", "b"], "channel": ["x", "y"]})) is None


def test_bar_chart_for_categories():
    rows = pd.DataFrame({"category": ["Music", "Gaming"], "likes_per_1k": [80.0, 60.0], "videos": [100, 90]})
    assert choose_chart(rows) == {"kind": "bar", "x": "likes_per_1k", "y": "category", "color": None}


def test_bar_chart_split_by_country():
    rows = pd.DataFrame({"country": ["IN", "US"], "category": ["Music", "Music"], "videos": [10, 20]})
    assert choose_chart(rows) == {"kind": "bar", "x": "videos", "y": "category", "color": "country"}


def test_chart_prefers_the_measure_over_a_row_count():
    rows = pd.DataFrame({"country": ["IN", "US"], "video_count": [78487, 46742], "median_days": [3.0, 6.0]})
    assert choose_chart(rows)["x"] == "median_days"


def test_chart_labels_with_names_not_ids():
    rows = pd.DataFrame({"channel_id": ["UC1", "UC2"], "channel_name": ["Sun TV", "SAB TV"], "total_days": [9, 8]})
    assert choose_chart(rows)["y"] == "channel_name"


def test_count_is_used_when_it_is_the_only_measure():
    rows = pd.DataFrame({"category": ["Music", "Gaming"], "video_count": [100, 90]})
    assert choose_chart(rows)["x"] == "video_count"


@pytest.mark.parametrize("time_column, time_values", [
    ("year_added", [2019, 2020, 2021]),
    ("trending_day", [datetime.date(2024, 1, day) for day in (1, 2, 3)]),
])
def test_line_chart_over_time(time_column, time_values):
    rows = pd.DataFrame({time_column: time_values, "titles": [5, 7, 6]})
    assert choose_chart(rows) == {"kind": "line", "x": time_column, "y": "titles", "color": None}


def test_build_chart_returns_a_figure():
    rows = pd.DataFrame({"country": ["IN", "US", "GB"], "videos": [78847, 47142, 47607]})
    figure = build_chart(rows, choose_chart(rows))
    assert len(figure.data) == 3
