import pandas as pd

from streampulse.insight_report import normalize_report, verify_report

FACTS = {
    "F1": ("Unique trending videos per country", pd.DataFrame({"country": ["IN", "US"], "unique_videos": [78847, 47142]})),
    "F2": ("Median days on the list, top 3 categories", pd.DataFrame({"country": ["IN"], "median_days": [3.0]})),
}


def test_correct_report_has_no_problems():
    assert verify_report("India had 78,847 unique videos [F1] and a median of 3 days [F2].", FACTS) == []


def test_invented_number_is_flagged():
    assert verify_report("India had about 80,000 unique videos [F1].", FACTS) == ["number not in any fact: 80,000"]


def test_citation_to_missing_fact_is_flagged():
    assert verify_report("India had 78,847 unique videos [F7].", FACTS) == ["cites a fact that does not exist: [F7]"]


def test_numbers_in_fact_descriptions_are_allowed():
    assert verify_report("The top 3 categories are listed [F2].", FACTS) == []


def test_full_width_brackets_become_normal_citations():
    normalized = normalize_report("India had 78,847 unique videos【F9】.")
    assert verify_report(normalized, FACTS) == ["cites a fact that does not exist: [F9]"]


def test_thin_space_thousands_are_joined():
    assert normalize_report("India had 78 847 videos") == "India had 78847 videos"


def test_separate_numbers_are_not_joined():
    assert normalize_report("between 6 and 3 days") == "between 6 and 3 days"
