import numpy as np
import pandas as pd
import pytest

from streampulse.title_optimizer import score_titles, suggestion_problems
from streampulse.virality import FEATURES_PATH
from streampulse.virality_model import feature_matrix, load_saved_models


@pytest.mark.parametrize("original, suggested, expected_problem", [
    ("Top 5 goals of the season", "Top 10 goals of the season", "adds numbers not in the original: 10"),
    ("Best goals of the season", "Best goals of the 2023 season", "adds numbers not in the original: 2023"),
    ("Best goals", "B" * 101, "longer than 100 characters"),
    ("Best goals", "best goals", "same as the original"),
    ("SOOJIN - BLACK FOREST", "SOOJIN - BLACK FOREST (Live Performance)", "adds a format label not in the original: live"),
    ("I Trained Behzinga", "Behind the Scenes: Training Behzinga", "adds a format label not in the original: behind the scenes"),
])
def test_suggestion_problems_are_flagged(original, suggested, expected_problem):
    assert expected_problem in suggestion_problems(original, suggested)


def test_keeping_the_original_numbers_is_fine():
    assert suggestion_problems("Top 5 goals of 2023", "2023's top 5 goals, ranked") == []


def test_keeping_an_existing_format_label_is_fine():
    assert suggestion_problems("Artist - Song (Official Video)", "Song by Artist | Official Video") == []


def test_label_inside_another_word_is_not_flagged():
    assert suggestion_problems("Delivering parcels", "Parcel delivery day") == []


@pytest.fixture(scope="module")
def video_row():
    if not FEATURES_PATH.exists():
        pytest.skip("build the feature table first: python -m streampulse.virality")
    features = pd.read_parquet(FEATURES_PATH)
    return features[(features["split"] == "test") & (features["country"] == "US")].iloc[0]


def test_scoring_the_original_title_reproduces_the_model(video_row):
    classifier, regressor, categories = load_saved_models()
    direct = classifier.predict(feature_matrix(pd.DataFrame([video_row]), categories))[0]
    scored = score_titles(video_row, [video_row["title"]], (classifier, regressor, categories))
    assert np.isclose(scored.loc[0, "long_run_probability"], direct)


def test_only_title_features_change_between_titles(video_row):
    scored = score_titles(video_row, [video_row["title"], video_row["title"] + "?"])
    assert len(scored) == 2
    assert scored["long_run_probability"].between(0, 1).all()
