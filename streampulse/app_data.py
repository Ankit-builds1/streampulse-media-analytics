import json
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

from streampulse.database import connect
from streampulse.load import PROJECT_ROOT, RAW_YOUTUBE_DIR, TRENDING_COLUMNS, load_category_names
from streampulse.topics import TOPIC_SUMMARY_PATH, VIDEO_TOPICS_PATH
from streampulse.virality import FEATURES_PATH

APP_DATA_DIR = PROJECT_ROOT / "app" / "data"
# Built from the parquet files when the app starts; a temp folder works both locally and on Streamlit Cloud.
APP_DATABASE_PATH = Path(tempfile.gettempdir()) / "streampulse_app.duckdb"
TITLE_OPTIMIZER_SAMPLE_SIZE = 600
CATEGORY_NAMES_PATH = APP_DATA_DIR / "category_names.json"
SAMPLE_UPLOAD_PATH = APP_DATA_DIR / "sample_upload_GB.csv.gz"
SAMPLE_UPLOAD_START = "2024-03-01"

# The deployed app cannot use data/, which is gitignored and too large for the repository. These slimmed copies
# keep the three tables Ask the Data was evaluated on; the daily table drops titles and tags, which are per video.
TABLE_EXPORTS = {
    "trending": """
        SELECT video_id, country, channel_id, category, trending_date, published_at, view_count, likes,
               comment_count, comments_disabled, ratings_disabled
        FROM trending""",
    "trending_videos": "SELECT * FROM trending_videos",
    "netflix_titles": 'SELECT * EXCLUDE (description, "cast", director) FROM netflix_titles',
}


def export_tables(connection):
    for table_name, sql in TABLE_EXPORTS.items():
        connection.execute(f"COPY ({sql}) TO '{APP_DATA_DIR / table_name}.parquet' (FORMAT parquet, COMPRESSION zstd)")


def export_title_optimizer_sample():
    """Test-period runs the title optimizer tab can pick from, with every model feature already computed."""
    features = pd.read_parquet(FEATURES_PATH)
    test_runs = features[features["split"] == "test"]
    sample = test_runs.groupby("country").sample(TITLE_OPTIMIZER_SAMPLE_SIZE // 3, random_state=7)
    sample.to_parquet(APP_DATA_DIR / "title_optimizer_videos.parquet", index=False)


def export_topic_trends():
    """Topic names and monthly counts of new trending videos per topic and country."""
    topic_names = pd.read_csv(TOPIC_SUMMARY_PATH)
    topic_names.to_csv(APP_DATA_DIR / "topics.csv", index=False)
    video_topics = pd.read_parquet(VIDEO_TOPICS_PATH).merge(topic_names[["topic", "name"]], on="topic")
    monthly = (
        video_topics.assign(month=pd.to_datetime(video_topics["first_trending_date"]).dt.to_period("M").dt.to_timestamp(),
                            country=video_topics["countries"].str.split("+"))
        .explode("country")
        .groupby(["month", "country", "topic", "name"]).size().rename("new_videos").reset_index()
    )
    monthly.to_parquet(APP_DATA_DIR / "topic_trends.parquet", index=False)


def export_upload_files():
    """Category names for cleaning uploads, and a small raw Kaggle file visitors can try the upload with."""
    category_names = {str(category_id): name for category_id, name in sorted(load_category_names().items())}
    CATEGORY_NAMES_PATH.write_text(json.dumps(category_names, indent=2), encoding="utf-8")
    # Kept as raw text in the original column layout, so the sample goes through exactly what an upload does.
    raw = pd.read_csv(RAW_YOUTUBE_DIR / "GB_youtube_trending_data.csv", usecols=TRENDING_COLUMNS, dtype=str,
                      keep_default_na=False)
    raw[raw["trending_date"] >= SAMPLE_UPLOAD_START].to_csv(SAMPLE_UPLOAD_PATH, index=False)


def build_app_data():
    """Write every file the Streamlit app reads into app/data."""
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        export_tables(connection)
    export_title_optimizer_sample()
    export_topic_trends()
    export_upload_files()
    for report_name in ["anomalies.csv", "insight_report.md"]:
        (APP_DATA_DIR / report_name).write_bytes((PROJECT_ROOT / "reports" / report_name).read_bytes())


def build_app_database(database_path=APP_DATABASE_PATH):
    """Load the app tables from parquet into a DuckDB file, rebuilding it whenever a parquet file is newer."""
    newest_source = max((APP_DATA_DIR / f"{table_name}.parquet").stat().st_mtime for table_name in TABLE_EXPORTS)
    if database_path.exists() and database_path.stat().st_mtime > newest_source:
        return database_path
    database_path.unlink(missing_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        for table_name in TABLE_EXPORTS:
            connection.execute(
                f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet('{(APP_DATA_DIR / table_name).as_posix()}.parquet')")
    return database_path


def connect_app_database():
    """The app database, opened the same way as Ask the Data's: read-only and unable to touch other files."""
    return duckdb.connect(str(build_app_database()), read_only=True, config={"enable_external_access": False})


if __name__ == "__main__":
    build_app_data()
    for path in sorted(APP_DATA_DIR.iterdir()):
        print(f"{path.name:<32} {path.stat().st_size / 1e6:6.1f} MB")
