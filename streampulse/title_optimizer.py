import json
import re

import pandas as pd

from streampulse.ask import NUMBER_PATTERN
from streampulse.llm import complete
from streampulse.load import PROJECT_ROOT
from streampulse.titles import TITLE_FEATURES, add_title_features
from streampulse.virality import FEATURES_PATH
from streampulse.virality_scoring import feature_matrix, load_saved_models

YOUTUBE_TITLE_LIMIT = 100
SUGGESTION_COUNT = 3
# Labels that tell viewers what kind of video they will get. Adding one the original does not have, such as
# "Live Performance" on a music video, misleads them about the content.
FORMAT_LABELS = [
    "official", "live", "full song", "lyrics", "lyric", "trailer", "teaser", "exclusive", "reaction", "highlights",
    "review", "behind the scenes", "compilation", "remix", "cover", "unboxing", "tutorial", "explained",
]

# Grounded in reports/findings.md (analyses 5 and 6) and evals/virality_report.md.
SUGGESTION_PROMPT = """You suggest better YouTube titles for a video that is already trending. Use these findings
from an analysis of 172,000 trending runs in India, the US and the UK (2020 to 2024):

- Title style has only a small effect on how long a trending video stays on the list. Who made the video and how
  its first day went matter far more. Aim for clarity and appeal, not tricks.
- Titles with a question mark ran slightly shorter in all three countries.
- Emoji, capital-letter words, numbers, exclamation marks and title length showed no consistent effect across
  countries.
- Indian trending titles often use the "|" separator to list the show, people and channel; US and UK titles use it
  less.

Rules:
- Keep the title accurate to the original. Do not add numbers, names, places, prices or claims that are not in the
  original title.
- Keep the same language and script as the original.
- Each title must be at most 100 characters and different from the original and from each other.

Return exactly {count} suggestions as a JSON list inside a ```json code block, each with "title" and "reason"
(one short sentence on what changed and why)."""


def suggest_titles(original_title, country, category, count=SUGGESTION_COUNT):
    """Ask the LLM for alternative titles. Returns a list of {"title", "reason"} dictionaries."""
    user_prompt = f"Country: {country}\nCategory: {category}\nOriginal title: {original_title}"
    reply = complete(SUGGESTION_PROMPT.format(count=count), user_prompt, temperature=0.7)
    json_block = re.search(r"```(?:json)?\s*(.*?)```", reply, re.DOTALL)
    suggestions = json.loads(json_block.group(1) if json_block else reply)
    return [{"title": str(item["title"]).strip(), "reason": str(item.get("reason", "")).strip()}
            for item in suggestions][:count]


def suggestion_problems(original_title, suggested_title):
    """Reasons a suggested title should not be used as it stands. An empty list means no problems found."""
    problems = []
    original_numbers = {number.replace(",", "") for number in NUMBER_PATTERN.findall(original_title)}
    added_numbers = [number for number in NUMBER_PATTERN.findall(suggested_title)
                     if number.replace(",", "") not in original_numbers]
    if added_numbers:
        problems.append(f"adds numbers not in the original: {', '.join(added_numbers)}")
    added_labels = [label for label in FORMAT_LABELS
                    if re.search(rf"\b{label}\b", suggested_title, re.IGNORECASE)
                    and not re.search(rf"\b{label}\b", original_title, re.IGNORECASE)]
    if added_labels:
        problems.append(f"adds a format label not in the original: {', '.join(added_labels)}")
    if len(suggested_title) > YOUTUBE_TITLE_LIMIT:
        problems.append(f"longer than {YOUTUBE_TITLE_LIMIT} characters")
    if suggested_title.strip().lower() == original_title.strip().lower():
        problems.append("same as the original")
    return problems


def score_titles(video_row, titles, models=None):
    """Score titles for one trending run, changing only the title and keeping every other feature as it was."""
    classifier, regressor, categories = models or load_saved_models()
    variants = pd.DataFrame([video_row] * len(titles)).reset_index(drop=True)
    variants["title"] = titles
    variants = add_title_features(variants.drop(columns=[*TITLE_FEATURES, "sentiment", "sentiment_label"]))
    matrix = feature_matrix(variants, categories)
    return pd.DataFrame({
        "title": titles,
        "long_run_probability": classifier.predict(matrix),
        "predicted_days": regressor.predict(matrix),
    })


def optimize_title(video_row, models=None):
    """Suggest titles for a trending run and score them against the original with the virality model."""
    suggestions = suggest_titles(video_row["title"], video_row["country"], video_row["category"])
    scores = score_titles(video_row, [video_row["title"], *[item["title"] for item in suggestions]], models)
    scores["source"] = ["original"] + ["suggestion"] * len(suggestions)
    scores["reason"] = [""] + [item["reason"] for item in suggestions]
    scores["problems"] = [[]] + [suggestion_problems(video_row["title"], item["title"]) for item in suggestions]
    original_probability = scores.loc[0, "long_run_probability"]
    scores["change_in_probability"] = scores["long_run_probability"] - original_probability
    return scores


def load_video_row(video_id, country):
    """One run's feature row from the virality feature table."""
    features = pd.read_parquet(FEATURES_PATH)
    matching = features[(features["video_id"] == video_id) & (features["country"] == country)]
    if matching.empty:
        raise ValueError(f"No completed trending run for video {video_id} in {country}.")
    return matching.iloc[0]


def evaluate_sample(videos_per_country=5, seed=3):
    """Run the optimizer on a sample of test-period videos and summarise how the suggestions scored."""
    features = pd.read_parquet(FEATURES_PATH)
    sample = features[features["split"] == "test"].groupby("country").sample(videos_per_country, random_state=seed)
    models = load_saved_models()
    all_scores = []
    for _, video_row in sample.iterrows():
        scores = optimize_title(video_row, models)
        all_scores.append(scores.assign(country=video_row["country"], video_id=video_row["video_id"],
                                        category=video_row["category"]))
    return pd.concat(all_scores, ignore_index=True)


if __name__ == "__main__":
    results = evaluate_sample()
    results["problems"] = results["problems"].map("; ".join)
    results.to_csv(PROJECT_ROOT / "evals" / "title_optimizer_results.csv", index=False)
    suggestions = results[results["source"] == "suggestion"]
    best_clean = suggestions[suggestions["problems"] == ""].groupby("video_id")["change_in_probability"].max()
    print(f"{results['video_id'].nunique()} videos, {len(suggestions)} suggestions, "
          f"{(suggestions['problems'] != '').sum()} flagged by the checks")
    print(f"best suggestion per video: mean change {100 * best_clean.mean():+.2f} points, "
          f"improved {100 * (best_clean > 0).mean():.0f}% of videos, largest {100 * best_clean.max():+.2f} points")
