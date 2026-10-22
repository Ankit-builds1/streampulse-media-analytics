import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

TITLE_FEATURES = [
    "has_number",
    "has_question",
    "has_exclamation",
    "has_caps_word",
    "has_emoji",
    "has_shorts_tag",
    "has_other_hashtag",
    "has_pipe",
    "title_words",
]
EMOJI_PATTERN = "[\U0001F300-\U0001FAFF☀-➿]"
# VADER only knows English words. Titles written mostly in another script would all score as neutral,
# which would look like a real "neutral" signal, so they get no sentiment score at all.
MIN_LATIN_SHARE_FOR_SENTIMENT = 0.9
# VADER's own recommended cut-offs for its compound score.
SENTIMENT_THRESHOLD = 0.05

_sentiment_analyzer = SentimentIntensityAnalyzer()


def latin_letter_share(titles):
    """Share of a title's letters that are A-Z, from 0 to 1. Missing for titles with no letters."""
    all_letters = titles.str.count(r"[^\W\d_]")
    return titles.str.count(r"[A-Za-z]") / all_letters.where(all_letters > 0)


def title_sentiment(titles):
    """VADER compound score from -1 to 1, or missing for titles not written mostly in Latin script."""
    scores = titles.map(lambda title: _sentiment_analyzer.polarity_scores(title)["compound"])
    return scores.where(latin_letter_share(titles) >= MIN_LATIN_SHARE_FOR_SENTIMENT)


def add_title_features(videos, title_column="title"):
    """Add title style features and sentiment columns to a DataFrame of videos."""
    titles = videos[title_column].fillna("")
    is_shorts = titles.str.lower().str.contains(r"#shorts?\b")
    sentiment = title_sentiment(titles)
    sentiment_label = pd.Series("not scored", index=videos.index)
    sentiment_label[sentiment.notna()] = "neutral"
    sentiment_label[sentiment >= SENTIMENT_THRESHOLD] = "positive"
    sentiment_label[sentiment <= -SENTIMENT_THRESHOLD] = "negative"
    return videos.assign(
        has_number=titles.str.contains(r"\d"),
        has_question=titles.str.contains("?", regex=False),
        has_exclamation=titles.str.contains("!", regex=False),
        has_caps_word=titles.str.contains(r"\b[A-Z]{3,}\b"),
        has_emoji=titles.str.contains(EMOJI_PATTERN),
        has_shorts_tag=is_shorts,
        has_other_hashtag=titles.str.contains("#", regex=False) & ~is_shorts,
        has_pipe=titles.str.contains("|", regex=False),
        title_words=titles.str.split().str.len(),
        sentiment=sentiment,
        sentiment_label=sentiment_label,
    )
