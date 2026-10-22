-- Analysis queries for data/streampulse.duckdb (build it with: python -m streampulse.database).
-- YouTube trending covers 2020-08-12 to 2024-04-15. The Netflix catalog is from September 2021.
-- trending has one row per video per country per day. trending_videos has one row per video per country.
-- Comments contain no semicolons, so the file can be split into separate statements safely.


-- 1. How much data is there per country, and over what period?
SELECT
    country,
    count(*) AS list_rows,
    count(DISTINCT video_id) AS videos,
    count(DISTINCT channel_id) AS channels,
    min(trending_date) AS first_day,
    max(trending_date) AS last_day
FROM trending
GROUP BY country
ORDER BY country;


-- 2. What are the five biggest categories in each country's trending videos?
SELECT
    country,
    category,
    count(*) AS videos,
    round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY country), 1) AS pct_of_country
FROM trending_videos
GROUP BY country, category
QUALIFY row_number() OVER (PARTITION BY country ORDER BY count(*) DESC) <= 5
ORDER BY country, videos DESC;


-- 3. How long does a video stay on the trending list in each country?
-- Videos already trending on the first day or still trending on the last day have runs cut off by
-- the dataset window, so they are left out here. The survival analysis in Phase 3 keeps them.
SELECT
    country,
    count(*) AS videos,
    median(days_trending) AS median_days,
    round(avg(days_trending), 2) AS mean_days,
    round(100.0 * avg(CAST(days_trending = 1 AS INTEGER)), 1) AS pct_one_day_only,
    max(days_trending) AS max_days
FROM trending_videos
WHERE first_trending_date > DATE '2020-08-12'
  AND last_trending_date < DATE '2024-04-15'
GROUP BY country
ORDER BY mean_days DESC;


-- 4. Which categories stay trending longest in each country? (categories with at least 200 videos)
SELECT
    country,
    category,
    count(*) AS videos,
    median(days_trending) AS median_days,
    round(avg(days_trending), 2) AS mean_days
FROM trending_videos
WHERE first_trending_date > DATE '2020-08-12'
  AND last_trending_date < DATE '2024-04-15'
GROUP BY country, category
HAVING count(*) >= 200
ORDER BY country, mean_days DESC;


-- 5. How soon after publishing does a video first trend, by category and country?
-- Videos first seen on the first day may have started trending earlier, so they are left out.
WITH time_to_trend AS (
    SELECT
        country,
        category,
        date_diff('day', CAST(published_at AS DATE), first_trending_date) AS days_to_trend
    FROM trending_videos
    WHERE first_trending_date > DATE '2020-08-12'
)
SELECT
    country,
    category,
    count(*) AS videos,
    median(days_to_trend) AS median_days_to_trend,
    round(100.0 * avg(CAST(days_to_trend <= 1 AS INTEGER)), 1) AS pct_within_one_day,
    round(100.0 * avg(CAST(days_to_trend >= 4 AS INTEGER)), 1) AS pct_four_days_or_more
FROM time_to_trend
GROUP BY country, category
HAVING count(*) >= 200
ORDER BY country, pct_within_one_day DESC;


-- 6. Which categories get the most likes and comments per 1,000 views at peak?
-- Videos with ratings or comments turned off have NULL counts, so median() skips them
-- instead of counting them as zero engagement.
SELECT
    category,
    count(*) AS videos,
    round(median(1000.0 * likes_at_peak / peak_views), 1) AS median_likes_per_1k_views,
    round(median(1000.0 * comments_at_peak / peak_views), 2) AS median_comments_per_1k_views
FROM trending_videos
WHERE peak_views > 0
GROUP BY category
HAVING count(*) >= 500
ORDER BY median_likes_per_1k_views DESC;


-- 7. When were trending videos published, in each country's local time? Top five day-hour slots.
-- The US spans several time zones, so Eastern time is used as the single reference.
WITH local_publish AS (
    SELECT
        country,
        timezone(
            CASE country WHEN 'IN' THEN 'Asia/Kolkata' WHEN 'US' THEN 'America/New_York' ELSE 'Europe/London' END,
            published_at AT TIME ZONE 'UTC'
        ) AS published_local
    FROM trending_videos
)
SELECT
    country,
    dayname(published_local) AS publish_day,
    hour(published_local) AS publish_hour,
    count(*) AS videos,
    round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY country), 2) AS pct_of_country
FROM local_publish
GROUP BY country, publish_day, publish_hour
QUALIFY row_number() OVER (PARTITION BY country ORDER BY count(*) DESC) <= 5
ORDER BY country, videos DESC;


-- 8. How many videos trend in more than one country, and in which combinations?
WITH video_countries AS (
    SELECT video_id, string_agg(country, '+' ORDER BY country) AS country_set
    FROM trending_videos
    GROUP BY video_id
)
SELECT
    country_set,
    count(*) AS videos,
    round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct_of_videos
FROM video_countries
GROUP BY country_set
ORDER BY videos DESC;


-- 9. How concentrated is each country's trending list? Share of trending days held by the
-- top 10 channels and by the top 1% of channels.
WITH channel_days AS (
    SELECT country, channel_id, count(*) AS trending_days
    FROM trending
    GROUP BY country, channel_id
),
ranked_channels AS (
    SELECT
        *,
        row_number() OVER (PARTITION BY country ORDER BY trending_days DESC) AS channel_rank,
        count(*) OVER (PARTITION BY country) AS channels_in_country,
        sum(trending_days) OVER (PARTITION BY country) AS country_trending_days
    FROM channel_days
)
SELECT
    country,
    any_value(channels_in_country) AS channels,
    round(100.0 * sum(trending_days) FILTER (WHERE channel_rank <= 10) / any_value(country_trending_days), 1)
        AS pct_days_top_10_channels,
    round(100.0 * sum(trending_days) FILTER (WHERE channel_rank <= 0.01 * channels_in_country)
        / any_value(country_trending_days), 1) AS pct_days_top_1pct_channels
FROM ranked_channels
GROUP BY country
ORDER BY country;


-- 10. Which channels spend the most days on each country's trending list?
SELECT
    country,
    any_value(channel_title) AS channel_title,
    count(*) AS trending_days,
    count(DISTINCT video_id) AS videos
FROM trending
GROUP BY country, channel_id
QUALIFY row_number() OVER (PARTITION BY country ORDER BY count(*) DESC) <= 5
ORDER BY country, trending_days DESC;


-- 11. Does India's list turn over faster? Average number of new videos entering the list per day.
WITH new_videos_per_day AS (
    SELECT country, first_trending_date, count(*) AS new_videos
    FROM trending_videos
    WHERE first_trending_date > DATE '2020-08-12'
    GROUP BY country, first_trending_date
)
SELECT
    country,
    year(first_trending_date) AS year,
    round(avg(new_videos), 1) AS avg_new_videos_per_day
FROM new_videos_per_day
GROUP BY country, year
ORDER BY country, year;


-- 12. How do title styles differ by country? Share of trending titles with a question mark,
-- a digit, an all-caps word of three or more letters, and a "|" separator.
SELECT
    country,
    count(*) AS videos,
    round(100.0 * avg(CAST(contains(title, '?') AS INTEGER)), 1) AS pct_question,
    round(100.0 * avg(CAST(regexp_matches(title, '[0-9]') AS INTEGER)), 1) AS pct_digit,
    round(100.0 * avg(CAST(regexp_matches(title, '\b[A-Z]{3,}\b') AS INTEGER)), 1) AS pct_caps_word,
    round(100.0 * avg(CAST(contains(title, '|') AS INTEGER)), 1) AS pct_pipe
FROM trending_videos
GROUP BY country
ORDER BY country;


-- 13. How fast did the Netflix catalog grow? Titles added per year, by type.
-- 2021 only runs to 25 September.
SELECT
    year(date_added) AS year_added,
    count(*) FILTER (WHERE type = 'Movie') AS movies,
    count(*) FILTER (WHERE type = 'TV Show') AS tv_shows,
    count(*) AS total
FROM netflix_titles
WHERE date_added IS NOT NULL
GROUP BY year_added
ORDER BY year_added;


-- 14. Which production countries supply the most Netflix titles, before and after 2018?
-- A title made by several countries counts once for each of them.
WITH title_countries AS (
    SELECT date_added, trim(unnest(string_split(country, ','))) AS production_country
    FROM netflix_titles
    WHERE country IS NOT NULL
)
SELECT
    production_country,
    count(*) AS titles,
    count(*) FILTER (WHERE year(date_added) <= 2017) AS added_by_2017,
    count(*) FILTER (WHERE year(date_added) >= 2018) AS added_2018_on
FROM title_countries
WHERE production_country <> ''
GROUP BY production_country
ORDER BY titles DESC
LIMIT 10;


-- 15. Which Netflix genres rate highest on IMDb?
-- Only titles with at least 1,000 IMDb votes, and genres with at least 50 such titles.
WITH title_genres AS (
    SELECT imdb_rating, trim(unnest(string_split(listed_in, ','))) AS genre
    FROM netflix_titles
    WHERE imdb_votes >= 1000
)
SELECT
    genre,
    count(*) AS titles,
    round(median(imdb_rating), 2) AS median_imdb_rating,
    round(avg(imdb_rating), 2) AS mean_imdb_rating
FROM title_genres
GROUP BY genre
HAVING count(*) >= 50
ORDER BY median_imdb_rating DESC;
