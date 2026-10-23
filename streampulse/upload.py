import json
import shutil
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

from streampulse.app_data import APP_DATA_DIR, CATEGORY_NAMES_PATH
from streampulse.ask import SCHEMA_NOTES
from streampulse.clean import clean_trending
from streampulse.database import CREATE_TRENDING, CREATE_TRENDING_VIDEOS
from streampulse.load import SNAKE_CASE_NAMES, TRENDING_COLUMNS

# Dislikes stopped being public in December 2021 and the cleaning drops the column, so it is optional here.
REQUIRED_COLUMNS = [column for column in TRENDING_COLUMNS if column != "dislikes"]
NUMBER_COLUMNS = ["category_id", "view_count", "likes", "comment_count"]
# likes and comment_count may be blank (the cleaning treats them as unknown); these two must always be present.
REQUIRED_NUMBER_COLUMNS = ["category_id", "view_count"]
FLAG_COLUMNS = ["comments_disabled", "ratings_disabled"]
# A few unreadable rows are dropped and reported; past this share the file is probably not the Kaggle format.
MAX_BAD_ROW_SHARE = 0.05
# The countries in the Kaggle "YouTube Trending Video Dataset", with the time zone used for local upload hours.
UPLOAD_COUNTRIES = {
    "BR": ("Brazil", "America/Sao_Paulo"),
    "CA": ("Canada", "America/Toronto"),
    "DE": ("Germany", "Europe/Berlin"),
    "FR": ("France", "Europe/Paris"),
    "GB": ("United Kingdom", "Europe/London"),
    "IN": ("India", "Asia/Kolkata"),
    "JP": ("Japan", "Asia/Tokyo"),
    "KR": ("South Korea", "Asia/Seoul"),
    "MX": ("Mexico", "America/Mexico_City"),
    "RU": ("Russia", "Europe/Moscow"),
    "US": ("United States", "America/New_York"),
}


class UploadError(ValueError):
    """A problem with an uploaded file, worded for the person who uploaded it."""


def country_from_file_name(file_name):
    """The country code a Kaggle file name starts with, such as CA in CA_youtube_trending_data.csv, or None."""
    prefix = Path(file_name).name.split("_")[0].upper()
    return prefix if prefix in UPLOAD_COUNTRIES else None


def save_upload(uploaded_file, file_name):
    """Copy an uploaded file object to a temp file, keeping the extension so DuckDB can tell if it is gzipped."""
    if not file_name.lower().endswith((".csv", ".csv.gz")):
        raise UploadError(f"'{file_name}' is not a .csv or .csv.gz file. Upload one country's "
                          "<country>_youtube_trending_data.csv from the Kaggle dataset, optionally gzipped.")
    suffix = ".csv.gz" if file_name.lower().endswith(".gz") else ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as saved:
        shutil.copyfileobj(uploaded_file, saved)
    return Path(saved.name)


def check_columns(columns):
    """Raise UploadError naming any Kaggle trending column the file lacks."""
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise UploadError(
            f"This file is missing {len(missing)} column(s) the Kaggle trending files have: "
            f"{', '.join(missing)}. Its columns are: {', '.join(map(str, columns[:20]))}.")


def check_upload_header(uploaded_file, file_name):
    """Check an uploaded file's header row before the full read, leaving the file at its start."""
    try:
        columns = pd.read_csv(uploaded_file, nrows=0,
                              compression="gzip" if file_name.lower().endswith(".gz") else None).columns.tolist()
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, EOFError, OSError) as read_error:
        raise UploadError("The file could not be read as a CSV. Check that it is a comma-separated UTF-8 text "
                          f"file (details: {str(read_error).splitlines()[0]})") from read_error
    finally:
        uploaded_file.seek(0)
    check_columns(columns)


def read_trending_csv(path):
    """Read the trending columns of a Kaggle-format CSV as text, or raise UploadError saying what is wrong."""
    # pandas rather than DuckDB: the real files have line breaks inside quoted descriptions, which DuckDB's
    # CSV reader rejects.
    try:
        columns = pd.read_csv(path, nrows=0).columns.tolist()
        check_columns(columns)
        selected = [*REQUIRED_COLUMNS, *(["dislikes"] if "dislikes" in columns else [])]
        raw = pd.read_csv(path, usecols=selected, dtype=str, keep_default_na=False)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError, EOFError, OSError) as read_error:
        raise UploadError("The file could not be read as a CSV. Check that it is a comma-separated UTF-8 text "
                          f"file (details: {str(read_error).splitlines()[0]})") from read_error
    if raw.empty:
        raise UploadError("The file has a header row but no data rows.")
    return raw


def parse_trending(raw, country):
    """Convert text columns to the types the cleaning expects. Returns the parsed rows and the number dropped."""
    parsed = raw.rename(columns=SNAKE_CASE_NAMES).assign(country=country)
    if "dislikes" not in parsed:
        parsed["dislikes"] = 0
    problems = {"video_id": parsed["video_id"].fillna("").str.strip().eq("")}
    for column in ["published_at", "trending_date"]:
        parsed[column] = pd.to_datetime(parsed[column], utc=True, errors="coerce", format="ISO8601")
        problems[column] = parsed[column].isna()
    for column in NUMBER_COLUMNS:
        parsed[column] = pd.to_numeric(parsed[column], errors="coerce")
    for column in REQUIRED_NUMBER_COLUMNS:
        problems[column] = parsed[column].isna()
    for column in FLAG_COLUMNS:
        parsed[column] = parsed[column].str.strip().str.lower().map({"true": True, "false": False, "1": True, "0": False})
        problems[column] = parsed[column].isna()
    unreadable = pd.concat(problems, axis=1).any(axis=1)

    if unreadable.mean() > MAX_BAD_ROW_SHARE:
        worst = max(problems, key=lambda column: problems[column].sum())
        example = raw.rename(columns=SNAKE_CASE_NAMES).loc[problems[worst], worst].iloc[0]
        raise UploadError(
            f"{unreadable.mean():.0%} of rows could not be read. The most common problem is the {worst} column, "
            f"for example the value {example!r}. Dates should look like 2024-04-15T00:00:00Z, counts should be "
            "whole numbers and the disabled columns True or False.")
    parsed = parsed[~unreadable].reset_index(drop=True)
    parsed["category_id"] = parsed["category_id"].astype(int)
    return parsed, int(unreadable.sum())


def category_names_for(category_ids, known_names):
    """Known YouTube category names, with a placeholder for any id the built-in files do not have."""
    return {category_id: known_names.get(category_id, f"Unknown category {category_id}")
            for category_id in category_ids}


def upload_schema_notes(country, first_day, last_day):
    """Ask the Data's notes, rewritten so the LLM knows the upload holds one country and its own dates."""
    replacements = {
        "country is 'IN', 'US' or 'GB'.": f"country is always '{country}' (the uploaded file).",
        "YouTube data runs from 2020-08-12 to 2024-04-15.": f"YouTube data runs from {first_day} to {last_day}.",
        "- India's YouTube data changes on 2022-10-06, so compare Indian engagement within one side of that date.\n": "",
    }
    notes = SCHEMA_NOTES
    for old, new in replacements.items():
        if old not in notes:
            raise RuntimeError(f"Ask the Data's schema notes changed; update upload_schema_notes for: {old!r}")
        notes = notes.replace(old, new)
    return notes


def upload_database_path(upload_key):
    return Path(tempfile.gettempdir()) / f"streampulse_upload_{upload_key}.duckdb"


def build_upload_database(csv_path, country, database_path):
    """Check, clean and load one country's trending CSV into a DuckDB file shaped like the app database.

    Returns a summary of what was read and dropped. Raises UploadError for files that are not in the Kaggle format.
    """
    if country not in UPLOAD_COUNTRIES:
        raise UploadError(f"Country {country!r} is not one of the Kaggle dataset's countries.")
    raw = read_trending_csv(csv_path)
    parsed, unreadable_rows = parse_trending(raw, country)
    known_names = {int(key): name for key, name in json.loads(CATEGORY_NAMES_PATH.read_text(encoding="utf-8")).items()}
    cleaned, cleaning_log = clean_trending(parsed, category_names_for(parsed["category_id"].unique(), known_names))

    database_path.unlink(missing_ok=True)
    parquet_path = database_path.with_suffix(".parquet")
    cleaned.to_parquet(parquet_path, index=False)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(CREATE_TRENDING, [str(parquet_path)])
        connection.execute(CREATE_TRENDING_VIDEOS)
        # Ask the Data's prompt describes the Netflix table too, so it stays available alongside the upload.
        connection.execute(
            f"CREATE TABLE netflix_titles AS SELECT * FROM read_parquet('{(APP_DATA_DIR / 'netflix_titles.parquet').as_posix()}')")
        first_day, last_day, videos = connection.execute(
            "SELECT min(first_trending_date), max(first_trending_date), count(*) FROM trending_videos").fetchone()
    parquet_path.unlink()
    return {
        "country": country,
        "rows_read": len(raw),
        "unreadable_rows": unreadable_rows,
        "same_day_repeats": int(cleaning_log.loc[0, "rows_changed"]),
        "daily_rows": len(cleaned),
        "videos": videos,
        "first_day": first_day,
        "last_day": last_day,
        "unknown_categories": sorted(set(cleaned["category"]) - set(known_names.values())),
    }


def connect_upload_database(database_path):
    """An uploaded database, opened as safely as the app database."""
    return duckdb.connect(str(database_path), read_only=True, config={"enable_external_access": False})
