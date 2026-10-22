import duckdb

from streampulse.load import PROJECT_ROOT

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DATABASE_PATH = PROJECT_ROOT / "data" / "streampulse.duckdb"

# Timestamps are stored as plain UTC values. DuckDB shows timestamp-with-time-zone columns in the
# laptop's local zone, which would quietly shift publish hours depending on whose machine runs the query.
CREATE_TRENDING = """
CREATE OR REPLACE TABLE trending AS
SELECT * REPLACE (
    CAST(trending_date AT TIME ZONE 'UTC' AS DATE) AS trending_date,
    published_at AT TIME ZONE 'UTC' AS published_at
)
FROM read_parquet(?)
"""

CREATE_NETFLIX_TITLES = """
CREATE OR REPLACE TABLE netflix_titles AS
SELECT * EXCLUDE (title_key) REPLACE (CAST(date_added AS DATE) AS date_added)
FROM read_parquet(?)
"""

# One row per video per country. Most questions are about videos, not daily list rows,
# and repeating this aggregation in every query invites small inconsistencies.
CREATE_TRENDING_VIDEOS = """
CREATE OR REPLACE VIEW trending_videos AS
SELECT
    country,
    video_id,
    any_value(title) AS title,
    any_value(channel_id) AS channel_id,
    any_value(channel_title) AS channel_title,
    any_value(category) AS category,
    min(published_at) AS published_at,
    min(trending_date) AS first_trending_date,
    max(trending_date) AS last_trending_date,
    count(*) AS days_trending,
    max(view_count) AS peak_views,
    arg_max(likes, view_count) AS likes_at_peak,
    arg_max(comment_count, view_count) AS comments_at_peak,
    bool_or(ratings_disabled) AS ratings_disabled,
    bool_or(comments_disabled) AS comments_disabled
FROM trending
GROUP BY country, video_id
"""


def build_database(database_path=DATABASE_PATH, processed_dir=PROCESSED_DIR):
    """Create the DuckDB file from the processed parquet files, replacing any existing tables."""
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(CREATE_TRENDING, [str(processed_dir / "trending.parquet")])
        connection.execute(CREATE_NETFLIX_TITLES, [str(processed_dir / "netflix_imdb.parquet")])
        connection.execute(CREATE_TRENDING_VIDEOS)


def connect(database_path=DATABASE_PATH, read_only=True):
    """Open the StreamPulse database. Read-only by default so analysis code cannot change the data."""
    return duckdb.connect(str(database_path), read_only=read_only)


if __name__ == "__main__":
    build_database()
    with connect() as connection:
        for table_name in ["trending", "netflix_titles", "trending_videos"]:
            row_count = connection.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]
            print(f"{table_name}: {row_count:,} rows")
