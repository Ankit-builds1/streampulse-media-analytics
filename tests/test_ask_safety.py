import duckdb
import pytest

from streampulse import ask
from streampulse.database import DATABASE_PATH

pytestmark = pytest.mark.skipif(not DATABASE_PATH.exists(), reason="build the database first: python -m streampulse.database")


@pytest.fixture(scope="module")
def connection():
    with ask.connect_for_questions() as question_connection:
        yield question_connection


@pytest.mark.parametrize("sql", [
    "DELETE FROM trending",
    "DROP TABLE trending",
    "INSERT INTO trending (video_id) VALUES ('x')",
    "UPDATE trending SET likes = 0",
    "CREATE TABLE copy_of_trending AS SELECT * FROM trending",
    "COPY trending TO 'stolen.csv'",
    "ATTACH 'other.duckdb' AS other",
    "INSTALL httpfs",
    "SET enable_external_access = true",
    "SELECT 1; DROP TABLE trending",
])
def test_rejects_anything_but_one_select(connection, sql):
    with pytest.raises(ValueError):
        ask.run_read_only(connection, sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('requirements.txt')",
    "SELECT * FROM read_text('C:/Windows/win.ini')",
    "SELECT * FROM read_parquet('data/processed/trending.parquet')",
])
def test_select_cannot_read_files(connection, sql):
    with pytest.raises(duckdb.Error):
        ask.run_read_only(connection, sql)


def test_select_and_with_queries_run(connection):
    rows, truncated = ask.run_read_only(
        connection,
        "WITH per_country AS (SELECT country, count(*) AS videos FROM trending_videos GROUP BY country) "
        "SELECT * FROM per_country ORDER BY videos DESC",
    )
    assert list(rows["country"]) == ["IN", "GB", "US"]
    assert not truncated


def test_large_results_are_cut_off(connection):
    rows, truncated = ask.run_read_only(connection, "SELECT video_id FROM trending")
    assert len(rows) == ask.MAX_ROWS
    assert truncated


def test_slow_query_is_interrupted(monkeypatch):
    monkeypatch.setattr(ask, "QUERY_TIMEOUT_SECONDS", 1)
    with ask.connect_for_questions() as slow_connection:
        with pytest.raises(duckdb.Error):
            ask.run_read_only(slow_connection, "SELECT count(*) FROM trending AS a, trending AS b")


@pytest.mark.parametrize("reply, expected", [
    ("```sql\nSELECT 1;\n```", "SELECT 1"),
    ("Here you go:\n```SQL\nSELECT country FROM trending\n```\nThis counts rows.", "SELECT country FROM trending"),
    ("SELECT 2;", "SELECT 2"),
])
def test_extract_sql(reply, expected):
    assert ask.extract_sql(reply) == expected


def test_schema_lists_every_table(connection):
    schema = ask.describe_schema(connection)
    for table_name in ["trending(", "trending_videos(", "netflix_titles("]:
        assert table_name in schema
