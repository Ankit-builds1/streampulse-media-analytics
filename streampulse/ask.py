import datetime
import re
import threading

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px

from streampulse.charts import COUNTRY_COLORS, SINGLE_SERIES_COLOR
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


ANSWER_PROMPT = """You explain the result of a database query to a business reader in 1 to 3 plain sentences.
Use only numbers that appear in the result table, written the same way or rounded. Do not calculate new
numbers, do not guess causes, and do not mention SQL. If the result is empty, say that no data matched.
If the result says the question is not answerable, say so briefly."""
MAX_ROWS_IN_ANSWER_PROMPT = 30
NUMBER_PATTERN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


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


def write_answer(question, rows):
    """Ask the LLM to state the result in plain words, using only numbers from the result rows."""
    table_text = rows.head(MAX_ROWS_IN_ANSWER_PROMPT).to_csv(index=False)
    user_prompt = f"Question: {question}\n\nResult table ({len(rows)} rows, CSV):\n{table_text}"
    return complete(ANSWER_PROMPT, user_prompt).strip()


def unsupported_numbers(answer, rows, question=""):
    """Numbers in the answer that do not match any value in the rows or the question, allowing for rounding."""
    numeric_cells = rows.select_dtypes(include="number").to_numpy(dtype=float, na_value=np.nan).ravel()
    known_values = list(numeric_cells[~np.isnan(numeric_cells)])
    known_values += [float(number.replace(",", "")) for number in NUMBER_PATTERN.findall(question)]
    # Dates and text cells can hold numbers too, such as the year in 2019-05-01.
    for text_value in rows.astype(str).to_numpy().ravel():
        known_values += [float(number.replace(",", "")) for number in NUMBER_PATTERN.findall(text_value)]

    unsupported = []
    for number_text in NUMBER_PATTERN.findall(answer):
        number = float(number_text.replace(",", ""))
        decimals = len(number_text.split(".")[1]) if "." in number_text else 0
        rounding_tolerance = 0.5 * 10 ** -decimals
        # A share can be written as a percentage, so 0.5186 in the table supports 51.86% in the answer.
        matches = any(
            abs(number - value) <= rounding_tolerance or abs(number - 100 * value) <= rounding_tolerance
            or abs(number - value / 1e6) <= rounding_tolerance or abs(number - value / 1e3) <= rounding_tolerance
            for value in known_values
        )
        if not matches:
            unsupported.append(number_text)
    return unsupported


def _is_time_column(rows, column):
    if pd.api.types.is_datetime64_any_dtype(rows[column]):
        return True
    first_value = rows[column].dropna().iloc[0] if rows[column].notna().any() else None
    if isinstance(first_value, (datetime.date, datetime.datetime)):
        return True
    name = column.lower()
    time_words = ("year", "month", "week", "date")
    return (name in {*time_words, "day"} or name.endswith(tuple(f"_{word}" for word in time_words))
            or name.startswith(tuple(f"{word}_" for word in time_words)))


def _is_count_column(column):
    name = column.lower()
    return name in {"count", "n", "rows"} or name.endswith(("_count", "_rows")) or name.startswith(("count_", "number_of_"))


def choose_chart(rows):
    """Pick a chart for a result: a line over time, a bar per label, or None when a chart would not help."""
    if rows is None or len(rows) < 2:
        return None
    time_columns = [column for column in rows.columns if _is_time_column(rows, column)]
    value_columns = [column for column in rows.select_dtypes(include="number").columns if column not in time_columns]
    label_columns = [column for column in rows.columns if column not in time_columns and column not in value_columns]
    if not value_columns:
        return None
    # Queries often add a row count next to the measure that was asked for, and an id next to a name.
    # Chart the measure and label with the name; fall back to the count or id when nothing else exists.
    value_columns = sorted(value_columns, key=_is_count_column)
    label_columns = sorted(label_columns, key=lambda column: column.lower().endswith("_id"))
    # Countries keep their usual colors, so a result with a country column is split by country.
    color_column = "country" if "country" in label_columns else None
    if time_columns:
        return {"kind": "line", "x": time_columns[0], "y": value_columns[0], "color": color_column}
    if label_columns and len(rows) <= MAX_ROWS_IN_ANSWER_PROMPT:
        label_column = next((column for column in label_columns if column != "country"), label_columns[0])
        return {"kind": "bar", "x": value_columns[0], "y": label_column, "color": color_column}
    return None


def build_chart(rows, chart_choice):
    """Plotly figure for a chart choice from choose_chart."""
    color_column = chart_choice["color"]
    color_settings = (
        {"color": color_column, "color_discrete_map": COUNTRY_COLORS} if color_column
        else {"color_discrete_sequence": [SINGLE_SERIES_COLOR]}
    )
    if chart_choice["kind"] == "line":
        figure = px.line(rows.sort_values(chart_choice["x"]), x=chart_choice["x"], y=chart_choice["y"],
                         markers=True, **color_settings)
    else:
        figure = px.bar(rows, x=chart_choice["x"], y=chart_choice["y"], orientation="h",
                        barmode="group", **color_settings)
        figure.update_yaxes(categoryorder="array", categoryarray=list(rows[chart_choice["y"]])[::-1])
    figure.update_layout(template="plotly_white", margin={"l": 10, "r": 10, "t": 30, "b": 10})
    return figure


def answer_question(question, connection=None):
    """Full Ask the Data flow: SQL, rows, a plain-English answer, unsupported numbers and a chart if one fits."""
    result = ask_data(question, connection)
    result.update({"answer": None, "unsupported_numbers": [], "chart": None})
    if result["error"] is None:
        result["answer"] = write_answer(question, result["rows"])
        result["unsupported_numbers"] = unsupported_numbers(result["answer"], result["rows"], question)
        chart_choice = choose_chart(result["rows"])
        if chart_choice:
            result["chart"] = build_chart(result["rows"], chart_choice)
    return result
