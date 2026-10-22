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
