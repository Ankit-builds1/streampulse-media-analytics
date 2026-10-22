import pandas as pd

from streampulse.load import PROJECT_ROOT, load_category_names, load_trending

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
CLEANING_LOG_PATH = PROJECT_ROOT / "reports" / "cleaning_log.csv"
SAME_DAY_KEY = ["country", "video_id", "trending_date"]


def drop_same_day_repeats(trending):
    """Keep one row per video, country and trending day: the snapshot with the most views."""
    # Repeats are two snapshots of the same day with different counts. Views only grow,
    # so the larger count is the later snapshot.
    return (
        trending.sort_values("view_count", ascending=False)
        .drop_duplicates(SAME_DAY_KEY)
        .sort_index()
    )


def mark_hidden_view_counts(trending):
    """Set view_count to missing where it is 0, since those videos hide their view counter."""
    trending = trending.copy()
    view_counts = trending["view_count"].astype("Int64")
    trending["view_count"] = view_counts.mask(view_counts.eq(0))
    return trending


def fill_missing_channel_titles(trending):
    """Fill missing channel titles from other rows of the same channel."""
    trending = trending.copy()
    known_titles = (
        trending.dropna(subset=["channel_title"])
        .drop_duplicates("channel_id")
        .set_index("channel_id")["channel_title"]
    )
    trending["channel_title"] = trending["channel_title"].fillna(trending["channel_id"].map(known_titles))
    return trending


def mark_disabled_engagement(trending):
    """Set likes and comment_count to missing where the uploader turned that feature off."""
    trending = trending.copy()
    likes = trending["likes"].astype("Int64")
    comment_counts = trending["comment_count"].astype("Int64")
    trending["likes"] = likes.mask(trending["ratings_disabled"])
    trending["comment_count"] = comment_counts.mask(trending["comments_disabled"])
    return trending


def clean_tags(trending):
    """Replace the "[None]" placeholder with an empty string, meaning the video has no tags."""
    trending = trending.copy()
    trending["tags"] = trending["tags"].replace("[None]", "")
    return trending


def add_category_names(trending, category_names):
    """Add a category column with the name for each category_id."""
    trending = trending.copy()
    trending["category"] = trending["category_id"].map(category_names)
    unmapped_ids = trending.loc[trending["category"].isna(), "category_id"].unique()
    if len(unmapped_ids) > 0:
        raise ValueError(f"No category name for ids: {sorted(unmapped_ids)}")
    return trending


def clean_trending(raw_trending, category_names):
    """Apply every cleaning rule in order. Returns the cleaned rows and a table of rows changed per rule."""
    # Dedupe must run before hidden views become missing, because it sorts on view_count.
    deduped = drop_same_day_repeats(raw_trending)
    hidden_views_marked = mark_hidden_view_counts(deduped)
    channel_titles_filled = fill_missing_channel_titles(hidden_views_marked)
    engagement_marked = mark_disabled_engagement(channel_titles_filled)
    tags_cleaned = clean_tags(engagement_marked)
    with_categories = add_category_names(tags_cleaned, category_names)
    # Public dislike counts stopped on 2021-12-13 and are 0 afterwards in every country.
    cleaned_trending = with_categories.drop(columns="dislikes").reset_index(drop=True)

    cleaning_log = pd.DataFrame(
        [
            ("drop same-day repeats", len(raw_trending) - len(deduped)),
            ("view_count 0 to missing (hidden counter)", hidden_views_marked["view_count"].isna().sum()),
            ("fill missing channel_title", channel_titles_filled["channel_title"].notna().sum()
             - hidden_views_marked["channel_title"].notna().sum()),
            ("likes to missing (ratings disabled)", engagement_marked["ratings_disabled"].sum()),
            ("comment_count to missing (comments disabled)", engagement_marked["comments_disabled"].sum()),
            ("tags [None] to empty", engagement_marked["tags"].eq("[None]").sum()),
            ("drop dislikes column", len(cleaned_trending)),
        ],
        columns=["rule", "rows_changed"],
    )
    return cleaned_trending, cleaning_log


if __name__ == "__main__":
    raw_trending = load_trending()
    cleaned_trending, cleaning_log = clean_trending(raw_trending, load_category_names())

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    CLEANING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned_trending.to_parquet(PROCESSED_DIR / "trending.parquet", index=False)
    cleaning_log.to_csv(CLEANING_LOG_PATH, index=False)

    print(f"raw rows: {len(raw_trending):,}  cleaned rows: {len(cleaned_trending):,}")
    print(cleaning_log.to_string(index=False))
