import pandas as pd

from streampulse.analysis import DATA_END, DATA_START, INDIA_LIST_CHANGE
from streampulse.charts import COUNTRY_COLORS, COUNTRY_NAMES
from streampulse.database import connect
from streampulse.load import PROJECT_ROOT

POWERBI_DIR = PROJECT_ROOT / "powerbi"
POWERBI_DATA_DIR = POWERBI_DIR / "data"
EXPECTED_VALUES_PATH = POWERBI_DIR / "expected_values.md"
COUNTRY_TIMEZONES = {"IN": "Asia/Kolkata", "US": "America/New_York", "GB": "Europe/London"}
LOCAL_UPLOAD_SQL = (
    "timezone(CASE country "
    + " ".join(f"WHEN '{code}' THEN '{zone}'" for code, zone in COUNTRY_TIMEZONES.items())
    + " END, published_at AT TIME ZONE 'UTC')"
)

# One row per video per country. The flag columns carry the analysis rules, so DAX measures can filter on them and
# reproduce the numbers in reports/findings.md instead of quietly using a slightly different population.
TRENDING_RUNS_SQL = f"""
    WITH first_day AS (
        SELECT country, video_id, view_count AS first_day_views, likes AS first_day_likes,
               comment_count AS first_day_comments
        FROM trending
        QUALIFY row_number() OVER (PARTITION BY country, video_id ORDER BY trending_date) = 1
    )
    SELECT
        runs.country || '|' || runs.video_id AS run_key,
        runs.country,
        runs.video_id,
        runs.title,
        runs.channel_id,
        runs.category,
        runs.published_at AS published_at_utc,
        isodow({LOCAL_UPLOAD_SQL}) AS upload_weekday_local,
        left(dayname({LOCAL_UPLOAD_SQL}), 3) AS upload_weekday_name,
        hour({LOCAL_UPLOAD_SQL}) AS upload_hour_local,
        runs.first_trending_date,
        runs.last_trending_date,
        runs.days_trending,
        date_diff('day', CAST(runs.published_at AS DATE), runs.first_trending_date) AS days_to_trend,
        CAST(date_diff('day', CAST(runs.published_at AS DATE), runs.first_trending_date) <= 1 AS INTEGER)
            AS trended_by_next_day,
        runs.peak_views,
        first_day.first_day_views,
        first_day.first_day_likes,
        first_day.first_day_comments,
        round(1000.0 * first_day.first_day_likes / nullif(first_day.first_day_views, 0), 3) AS likes_per_1k_views,
        round(1000.0 * first_day.first_day_comments / nullif(first_day.first_day_views, 0), 3)
            AS comments_per_1k_views,
        -- Runs already on the list on the first day of data started earlier, so their start is unknown.
        CAST(runs.first_trending_date > DATE '{DATA_START}' AS INTEGER) AS full_run_known,
        CAST(runs.first_trending_date > DATE '{DATA_START}' AND runs.last_trending_date < DATE '{DATA_END}'
             AS INTEGER) AS completed_run,
        CASE
            WHEN runs.country <> 'IN' THEN runs.country
            WHEN runs.first_trending_date < DATE '{INDIA_LIST_CHANGE}' THEN 'IN before Oct 2022'
            ELSE 'IN from Oct 2022'
        END AS country_period
    FROM trending_videos AS runs
    JOIN first_day USING (country, video_id)
"""

CHANNEL_SLOTS_SQL = """
    SELECT country, channel_id, count(*) AS list_slots, count(DISTINCT video_id) AS trending_videos
    FROM trending
    GROUP BY country, channel_id
"""

CHANNELS_SQL = """
    SELECT channel_id, any_value(channel_title) AS channel_title
    FROM trending_videos
    GROUP BY channel_id
"""

COUNTRY_OVERLAP_SQL = """
    WITH totals AS (SELECT country, count(*) AS videos FROM trending_videos GROUP BY country)
    SELECT a.country, b.country AS also_trending_in, count(*) AS shared_videos,
           round(100.0 * count(*) / any_value(totals.videos), 1) AS pct_of_country_videos
    FROM trending_videos AS a
    JOIN trending_videos AS b ON a.video_id = b.video_id AND a.country <> b.country
    JOIN totals ON totals.country = a.country
    GROUP BY a.country, b.country
"""

NETFLIX_SQL = """
    SELECT show_id, type, title, trim(split_part(country, ',', 1)) AS main_country, date_added,
           year(date_added) AS year_added, release_year, rating, listed_in, duration_minutes, seasons,
           imdb_rating, imdb_votes, CAST(imdb_rating IS NOT NULL AS INTEGER) AS imdb_matched
    FROM netflix_titles
"""


def date_table(first_day, last_day):
    """A calendar table covering the trending data, with sort columns so months and weekdays order correctly."""
    dates = pd.DataFrame({"date": pd.date_range(first_day, last_day, freq="D")})
    return dates.assign(
        year=dates["date"].dt.year,
        month_number=dates["date"].dt.month,
        month=dates["date"].dt.strftime("%b %Y"),
        month_start=dates["date"].dt.to_period("M").dt.to_timestamp(),
        week_start=dates["date"] - pd.to_timedelta(dates["date"].dt.weekday, unit="D"),
        weekday_number=dates["date"].dt.isocalendar().day.astype(int),
        weekday=dates["date"].dt.strftime("%a"),
    )


def build_tables():
    """Every table the Power BI report uses, keyed by file name."""
    with connect() as connection:
        tables = {
            "fact_trending_runs": connection.execute(TRENDING_RUNS_SQL).df(),
            "fact_channel_slots": connection.execute(CHANNEL_SLOTS_SQL).df(),
            "fact_country_overlap": connection.execute(COUNTRY_OVERLAP_SQL).df(),
            "dim_channel": connection.execute(CHANNELS_SQL).df(),
            "netflix_titles": connection.execute(NETFLIX_SQL).df(),
        }
    runs = tables["fact_trending_runs"]
    tables["dim_country"] = pd.DataFrame({
        "country": list(COUNTRY_NAMES),
        "country_name": list(COUNTRY_NAMES.values()),
        "country_color": [COUNTRY_COLORS[code] for code in COUNTRY_NAMES],
        "timezone": [COUNTRY_TIMEZONES[code] for code in COUNTRY_NAMES],
    })
    tables["dim_category"] = pd.DataFrame({"category": sorted(runs["category"].unique())})
    tables["dim_date"] = date_table(runs["first_trending_date"].min(), runs["last_trending_date"].max())
    tables["spikes"] = pd.read_csv(PROJECT_ROOT / "reports" / "anomalies.csv")
    tables["topic_monthly"] = pd.read_parquet(PROJECT_ROOT / "app" / "data" / "topic_trends.parquet")
    return tables


def expected_values(tables):
    """Numbers each report visual should show, computed with the same rules as the DAX measures."""
    runs = tables["fact_trending_runs"]
    known = runs[runs["full_run_known"] == 1]
    slots = tables["fact_channel_slots"]
    top_ten_share = slots.groupby("country").apply(
        lambda country: 100 * country.nlargest(10, "list_slots")["list_slots"].sum() / country["list_slots"].sum(),
        include_groups=False,
    )
    overlap = tables["fact_country_overlap"].set_index(["country", "also_trending_in"])["shared_videos"]
    netflix = tables["netflix_titles"]
    rated = netflix[netflix["imdb_votes"] >= 1000]
    lines = [
        "# Expected values",
        "",
        "Generated by `python -m streampulse.powerbi_export` from the same CSVs Power BI loads. With no filters",
        "applied, each visual should show these numbers. If one differs, the measure or a relationship is wrong.",
        "",
        "## All countries",
        "",
        "| Measure | Expected |",
        "|---|---|",
        f"| Trending Runs | {len(runs):,} |",
        f"| Channels | {runs['channel_id'].nunique():,} |",
        f"| Runs With Known Start | {len(known):,} |",
        f"| % Trended By Next Day (countries combined) | {100 * known['trended_by_next_day'].mean():.1f}% |",
        f"| Median Days On List (countries combined) | {known['days_trending'].median():.0f} |",
        "",
        "## By country",
        "",
        "| Measure | India (IN) | United States (US) | United Kingdom (GB) |",
        "|---|---|---|---|",
    ]

    def by_country(values, number_format):
        return " | ".join(format(values[code], number_format) for code in ["IN", "US", "GB"])

    rows = {
        "Trending Runs": (runs.groupby("country").size(), ","),
        "% Trended By Next Day": (100 * known.groupby("country")["trended_by_next_day"].mean(), ".1f"),
        "Median Days On List": (known.groupby("country")["days_trending"].median(), ".0f"),
        "Top 10 Channel Share %": (top_ten_share, ".1f"),
    }
    lines += [f"| {name} | {by_country(values, number_format)} |" for name, (values, number_format) in rows.items()]
    engagement = known[known["first_day_views"] > 0].groupby("country_period")
    lines += [
        "",
        "## Engagement on the first trending day (runs with a known start)",
        "",
        "| Country period | Median Likes per 1k Views | Median Comments per 1k Views |",
        "|---|---|---|",
    ]
    for period, group in engagement:
        lines.append(f"| {period} | {group['likes_per_1k_views'].median():.1f} | "
                     f"{group['comments_per_1k_views'].median():.2f} |")
    lines += [
        "",
        "## Markets, Netflix",
        "",
        "| Measure | Expected |",
        "|---|---|",
        f"| Videos shared by the US and UK | {overlap[('US', 'GB')]:,} |",
        f"| Share of India's videos also trending in the US | {100 * overlap[('IN', 'US')] / (runs['country'] == 'IN').sum():.1f}% |",
        f"| Netflix titles | {len(netflix):,} |",
        f"| Netflix titles added in 2019 | {(netflix['year_added'] == 2019).sum():,} |",
        f"| IMDb Match Rate % | {100 * netflix['imdb_matched'].mean():.1f}% |",
        f"| Median IMDb Rating, all titles (1,000+ votes) | {rated['imdb_rating'].median():.1f} |",
        f"| Median IMDb rating, movies (1,000+ votes) | {rated.loc[rated['type'] == 'Movie', 'imdb_rating'].median():.1f} |",
        f"| Median IMDb rating, TV shows (1,000+ votes) | {rated.loc[rated['type'] == 'TV Show', 'imdb_rating'].median():.1f} |",
        f"| Spikes flagged | {len(tables['spikes']):,} |",
    ]
    return "\n".join(lines) + "\n"


def export_for_powerbi():
    """Write every table to powerbi/data as CSV and the expected values to powerbi/expected_values.md."""
    POWERBI_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tables = build_tables()
    for name, table in tables.items():
        # UTF-8 with a byte-order mark, so Power BI reads Hindi, Tamil and other non-Latin titles correctly.
        table.to_csv(POWERBI_DATA_DIR / f"{name}.csv", index=False, encoding="utf-8-sig")
    EXPECTED_VALUES_PATH.write_text(expected_values(tables), encoding="utf-8")
    return tables


if __name__ == "__main__":
    for name, table in export_for_powerbi().items():
        size_mb = (POWERBI_DATA_DIR / f"{name}.csv").stat().st_size / 1e6
        print(f"{name:<22} {len(table):>9,} rows  {size_mb:6.1f} MB")
    print(EXPECTED_VALUES_PATH.read_text(encoding="utf-8"))
