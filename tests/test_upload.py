import io

import pandas as pd
import pytest

from streampulse.app_data import SAMPLE_UPLOAD_PATH
from streampulse.ask import SCHEMA_NOTES
from streampulse.upload import (
    UploadError, build_upload_database, check_upload_header, connect_upload_database, country_from_file_name,
    parse_trending,
    read_trending_csv, save_upload, upload_schema_notes,
)


@pytest.fixture(scope="module")
def sample_rows():
    return pd.read_csv(SAMPLE_UPLOAD_PATH, dtype=str, keep_default_na=False).head(200)


def write_csv(rows, folder, name="upload.csv"):
    path = folder / name
    rows.to_csv(path, index=False)
    return path


def test_sample_file_loads_into_a_read_only_database(tmp_path):
    database_path = tmp_path / "upload.duckdb"
    summary = build_upload_database(SAMPLE_UPLOAD_PATH, "GB", database_path)
    assert summary["unreadable_rows"] == 0 and summary["videos"] > 1000
    with connect_upload_database(database_path) as connection:
        assert connection.execute("SELECT DISTINCT country FROM trending_videos").fetchall() == [("GB",)]
        with pytest.raises(Exception):
            connection.execute("DELETE FROM trending")


def test_wrong_extension_is_rejected():
    with pytest.raises(UploadError, match="not a .csv or .csv.gz"):
        save_upload(io.BytesIO(b"a,b\n1,2\n"), "trending.xlsx")


def test_missing_columns_are_named(sample_rows, tmp_path):
    path = write_csv(sample_rows.drop(columns=["view_count", "categoryId"]), tmp_path)
    with pytest.raises(UploadError, match="missing 2 column.*categoryId, view_count"):
        read_trending_csv(path)


def test_non_csv_bytes_are_rejected(tmp_path):
    path = tmp_path / "upload.csv.gz"
    path.write_bytes(b"this is not gzip")
    with pytest.raises(UploadError, match="could not be read as a CSV"):
        read_trending_csv(path)


def test_header_only_file_is_rejected(sample_rows, tmp_path):
    with pytest.raises(UploadError, match="no data rows"):
        read_trending_csv(write_csv(sample_rows.head(0), tmp_path))


def test_mostly_bad_dates_name_the_column_and_an_example(sample_rows):
    rows = sample_rows.copy()
    rows["trending_date"] = "15/04/2024"
    with pytest.raises(UploadError, match="trending_date.*'15/04/2024'"):
        parse_trending(rows, "GB")


def test_a_few_bad_rows_are_dropped_and_counted(sample_rows):
    rows = sample_rows.copy()
    rows.loc[0, "view_count"] = "lots"
    rows.loc[1, "comments_disabled"] = "maybe"
    parsed, dropped = parse_trending(rows, "GB")
    assert dropped == 2 and len(parsed) == len(rows) - 2


def test_unknown_category_ids_get_a_placeholder_name(sample_rows, tmp_path):
    rows = sample_rows.copy()
    rows.loc[:, "categoryId"] = "99"
    summary = build_upload_database(write_csv(rows, tmp_path), "GB", tmp_path / "upload.duckdb")
    assert summary["unknown_categories"] == ["Unknown category 99"]


def test_upload_schema_notes_describe_the_uploaded_country():
    notes = upload_schema_notes("CA", "2024-03-01", "2024-04-15")
    assert "always 'CA'" in notes and "2024-03-01 to 2024-04-15" in notes
    assert "2022-10-06" not in notes and notes != SCHEMA_NOTES


@pytest.mark.parametrize("file_name, expected", [
    ("CA_youtube_trending_data.csv", "CA"),
    ("C:/downloads/kr_youtube_trending_data.csv.gz", "KR"),
    ("trending.csv", None),
    ("XX_youtube_trending_data.csv", None),
])
def test_country_is_read_from_kaggle_file_names(file_name, expected):
    assert country_from_file_name(file_name) == expected


def test_header_check_rejects_other_csv_files_and_rewinds():
    netflix_like = io.BytesIO(b"show_id,type,title\ns1,Movie,Some Film\n")
    with pytest.raises(UploadError, match="missing 12 column"):
        check_upload_header(netflix_like, "netflix_titles.csv")
    assert netflix_like.tell() == 0
