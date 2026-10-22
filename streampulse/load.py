import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_YOUTUBE_DIR = PROJECT_ROOT / "data" / "raw" / "youtube"
COUNTRIES = ("IN", "US", "GB")

# description and thumbnail_link are left out: the analysis uses neither,
# and description alone is most of the memory used by the raw files.
TRENDING_COLUMNS = [
    "video_id", "title", "publishedAt", "channelId", "channelTitle", "categoryId",
    "trending_date", "tags", "view_count", "likes", "dislikes", "comment_count",
    "comments_disabled", "ratings_disabled",
]
SNAKE_CASE_NAMES = {
    "publishedAt": "published_at",
    "channelId": "channel_id",
    "channelTitle": "channel_title",
    "categoryId": "category_id",
}


def load_trending(countries=COUNTRIES, raw_dir=RAW_YOUTUBE_DIR):
    """Load raw trending rows for the given countries into one DataFrame with a country column."""
    country_frames = [
        pd.read_csv(raw_dir / f"{country}_youtube_trending_data.csv", usecols=TRENDING_COLUMNS)
        .rename(columns=SNAKE_CASE_NAMES)
        .assign(country=country)
        for country in countries
    ]
    trending = pd.concat(country_frames, ignore_index=True)
    trending["published_at"] = pd.to_datetime(trending["published_at"], utc=True)
    trending["trending_date"] = pd.to_datetime(trending["trending_date"], utc=True)
    return trending


def load_category_names(countries=COUNTRIES, raw_dir=RAW_YOUTUBE_DIR):
    """Map YouTube category id to category name, merged across the country files."""
    # The IN and GB files have no entry for id 29, so a single country's file is not enough.
    category_names = {}
    for country in countries:
        with open(raw_dir / f"{country}_category_id.json", encoding="utf-8") as category_file:
            for item in json.load(category_file)["items"]:
                category_names[int(item["id"])] = item["snippet"]["title"]
    return category_names
