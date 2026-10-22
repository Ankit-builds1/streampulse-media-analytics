import re
import threading

import duckdb
import pandas as pd

from streampulse.database import DATABASE_PATH
from streampulse.llm import complete

MAX_ROWS = 200
QUERY_TIMEOUT_SECONDS = 15
MAX_ATTEMPTS = 2

# Column names and types come from the database itself; these notes add what the names alone do not say.
SCHEMA_NOTES = """
- trending: one row per video per country per day it was on the trending list.
  country is 'IN', 'US' or 'GB'. trending_date is a DATE; published_at is a TIMESTAMP in UTC.
  likes is NULL when ratings are disabled and comment_count is NULL when comments are disabled; treat NULL as
  unknown, never as zero. tags are separated by '|' and are '' when a video has no tags.
- trending_videos: one row per video per country. days_trending is the number of days on the list,
  peak_views the highest view count, likes_at_peak and comments_at_peak are taken on that day.
- netflix_titles: one row per Netflix title. type is 'Movie' or 'TV Show'. country and listed_in (genres)
  are comma-separated lists of full names, such as 'United States, India'. imdb_rating and imdb_votes are
  NULL for titles with no IMDb match. rating is the age rating, such as 'TV-MA', not a quality score.
- view_count, likes and comment_count in trending are running totals on that day, so never sum them across days.
  For any per-video measure, use trending_videos, which has one row per video and country.
- Some channels changed their name during the period. Group channels by channel_id and show
  any_value(channel_title) as the name.
- When ranking groups by an average, median or ratio, only keep groups with at least 30 rows and include
  the row count as a column, so small groups do not win by chance.
- YouTube data runs from 2020-08-12 to 2024-04-15. The Netflix catalog runs to 2021-09-25.
- India's YouTube data changes on 2022-10-06, so compare Indian engagement within one side of that date.
- Dislike counts are not available. Use median for view counts, which are very skewed.
"""

SYSTEM_PROMPT = """You write one DuckDB SQL query that answers a question about YouTube trending data and a
Netflix catalog. Use only the tables and columns listed below. Write a single SELECT statement (a WITH clause
is allowed). Never modify data. Use readable column aliases. Round decimals to 2 places. If the question cannot
be answered from these tables, return exactly: SELECT 'not answerable from this data' AS answer

Tables:
{schema}

Notes:
{notes}

Reply with only the SQL inside a ```sql code block."""


def connect_for_questions():
    """Read-only connection with file system access turned off, so a query cannot read or write other files."""
    return duckdb.connect(str(DATABASE_PATH), read_only=True, config={"enable_external_access": False})


def describe_schema(connection):
    """One line per table or view listing its columns and types."""
    columns = connection.execute("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
        ORDER BY table_name, ordinal_position
    """).fetchall()
    tables = {}
    for table_name, column_name, data_type in columns:
        tables.setdefault(table_name, []).append(f"{column_name} {data_type}")
    return "\n".join(f"{table_name}({', '.join(table_columns)})" for table_name, table_columns in tables.items())


def extract_sql(reply):
    """Pull the SQL out of a model reply, with or without a code block, without a trailing semicolon."""
    code_block = re.search(r"```(?:sql)?\s*(.*?)```", reply, re.DOTALL | re.IGNORECASE)
    sql = code_block.group(1) if code_block else reply
    return sql.strip().rstrip(";").strip()


def check_read_only(connection, sql):
    """Raise ValueError unless the text is exactly one SELECT statement."""
    statements = connection.extract_statements(sql)
    if len(statements) != 1:
        raise ValueError(f"Expected one SQL statement, got {len(statements)}.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise ValueError(f"Only SELECT queries are allowed, got {statements[0].type.name}.")


def run_read_only(connection, sql):
    """Run a checked SELECT with a row limit and a time limit. Returns the rows and whether they were cut off."""
    check_read_only(connection, sql)
    timer = threading.Timer(QUERY_TIMEOUT_SECONDS, connection.interrupt)
    timer.start()
    try:
        result = connection.execute(sql)
        column_names = [column[0] for column in result.description]
        fetched = result.fetchmany(MAX_ROWS + 1)
    finally:
        timer.cancel()
    rows = pd.DataFrame(fetched[:MAX_ROWS], columns=column_names)
    return rows, len(fetched) > MAX_ROWS


def generate_sql(question, schema, previous_attempt=None):
    """Ask the LLM for a query. On a retry, include the failed query and its error so it can fix it."""
    user_prompt = question
    if previous_attempt:
        failed_sql, error_message = previous_attempt
        user_prompt += (
            f"\n\nThis query failed:\n```sql\n{failed_sql}\n```\nError: {error_message}\n"
            "Write a corrected query."
        )
    system_prompt = SYSTEM_PROMPT.format(schema=schema, notes=SCHEMA_NOTES.strip())
    return extract_sql(complete(system_prompt, user_prompt))


def ask_data(question, connection=None):
    """Turn a question into SQL, run it safely and return the question, SQL, rows, cut-off flag, attempts and error."""
    connection = connection or connect_for_questions()
    schema = describe_schema(connection)
    previous_attempt = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        sql = generate_sql(question, schema, previous_attempt)
        try:
            rows, truncated = run_read_only(connection, sql)
            return {"question": question, "sql": sql, "rows": rows, "truncated": truncated,
                    "attempts": attempt, "error": None}
        except ValueError as unsafe_query:
            # An unsafe query is never retried: the model asked for something it must not do.
            return {"question": question, "sql": sql, "rows": None, "truncated": False,
                    "attempts": attempt, "error": f"Rejected: {unsafe_query}"}
        except duckdb.Error as query_error:
            previous_attempt = (sql, str(query_error).splitlines()[0])
    return {"question": question, "sql": sql, "rows": None, "truncated": False,
            "attempts": MAX_ATTEMPTS, "error": previous_attempt[1]}
