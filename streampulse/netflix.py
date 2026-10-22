import re
import unicodedata

import pandas as pd

from streampulse.load import PROJECT_ROOT, load_imdb_rated_titles, load_netflix

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
NETFLIX_KIND = {"Movie": "movie", "TV Show": "tv"}
IMDB_KIND = {"movie": "movie", "tvMovie": "movie", "tvSpecial": "movie", "tvSeries": "tv", "tvMiniSeries": "tv"}


def normalize_title(title):
    """Lowercase and strip accents and punctuation, so 'Blood & Water' and 'blood and water' compare equal."""
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    ascii_title = ascii_title.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", ascii_title).strip()


def clean_netflix(raw_netflix):
    """Fix shifted durations and parse dates and durations. Returns the cleaned catalog and a log of changes."""
    netflix = raw_netflix.copy()

    # A few titles have their duration in the rating column and nothing in duration.
    duration_in_rating = netflix["rating"].str.fullmatch(r"\d+ min", na=False) & netflix["duration"].isna()
    netflix.loc[duration_in_rating, "duration"] = netflix.loc[duration_in_rating, "rating"]
    netflix.loc[duration_in_rating, "rating"] = pd.NA

    padded_dates = netflix["date_added"].str.startswith(" ", na=False)
    netflix["date_added"] = pd.to_datetime(netflix["date_added"].str.strip(), format="%B %d, %Y")

    duration_number = netflix["duration"].str.extract(r"(\d+)")[0].astype("Int64")
    netflix["duration_minutes"] = duration_number.where(netflix["type"] == "Movie")
    netflix["seasons"] = duration_number.where(netflix["type"] == "TV Show")

    netflix["kind"] = netflix["type"].map(NETFLIX_KIND)
    netflix["title_key"] = netflix["title"].astype(str).map(normalize_title)

    # Some titles were listed twice, differing only in capitalisation and date_added. Keep the first
    # date it was added. Country is part of the key because two different shows share "What If" (2019).
    # Non-Latin titles normalize to "", so they keep their original text or they would all collide.
    rows_before_dedupe = len(netflix)
    dedupe_title = netflix["title_key"].where(netflix["title_key"] != "", netflix["title"])
    netflix = (
        netflix.assign(dedupe_title=dedupe_title)
        .sort_values("date_added")
        .drop_duplicates(["dedupe_title", "type", "release_year", "duration", "country"])
        .sort_index()
        .drop(columns="dedupe_title")
        .reset_index(drop=True)
    )

    cleaning_log = pd.DataFrame(
        [
            ("duration moved out of rating column", duration_in_rating.sum()),
            ("date_added leading space stripped", padded_dates.sum()),
            ("date_added missing", netflix["date_added"].isna().sum()),
            ("duplicate listing dropped", rows_before_dedupe - len(netflix)),
        ],
        columns=["rule", "rows_changed"],
    )
    return netflix, cleaning_log


def match_imdb_ratings(netflix, rated_titles):
    """Attach IMDb id, rating, votes and genres to each Netflix title that has a plausible match."""
    imdb_candidates = pd.concat([
        rated_titles.assign(title_key=rated_titles["primary_title"].fillna("").map(normalize_title)),
        rated_titles.assign(title_key=rated_titles["original_title"].fillna("").map(normalize_title)),
    ]).drop_duplicates(["tconst", "title_key"])
    imdb_candidates["kind"] = imdb_candidates["title_type"].map(IMDB_KIND)
    # Titles written only in non-Latin script normalize to "", and "" would match every other such title.
    imdb_candidates = imdb_candidates[imdb_candidates["title_key"] != ""]

    candidate_pairs = netflix[netflix["title_key"] != ""].merge(
        imdb_candidates[["tconst", "title_key", "kind", "start_year", "imdb_rating", "imdb_votes", "imdb_genres"]],
        on=["title_key", "kind"],
    )
    year_gap = candidate_pairs["release_year"] - candidate_pairs["start_year"]
    # Movies: festival and release years often differ by one. TV: Netflix release_year is the latest
    # season, so the series can have started in any earlier year.
    plausible_movie = candidate_pairs["kind"].eq("movie") & year_gap.abs().le(1).fillna(False)
    plausible_tv = candidate_pairs["kind"].eq("tv") & year_gap.ge(0).fillna(False)
    best_matches = (
        candidate_pairs[plausible_movie | plausible_tv]
        .sort_values("imdb_votes", ascending=False)
        .drop_duplicates("show_id")
    )
    return netflix.merge(
        best_matches[["show_id", "tconst", "imdb_rating", "imdb_votes", "imdb_genres"]],
        on="show_id",
        how="left",
    )


def summarize_matches(matched_netflix):
    """Count titles and IMDb matches by Netflix type, plus an overall row."""
    by_type = matched_netflix.groupby("type").agg(titles=("show_id", "size"), matched=("tconst", "count"))
    by_type.loc["All"] = by_type.sum()
    by_type["match_rate"] = (by_type["matched"] / by_type["titles"]).round(3)
    return by_type.reset_index()


if __name__ == "__main__":
    netflix, cleaning_log = clean_netflix(load_netflix())
    matched_netflix = match_imdb_ratings(netflix, load_imdb_rated_titles())
    match_summary = summarize_matches(matched_netflix)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    matched_netflix.to_parquet(PROCESSED_DIR / "netflix_imdb.parquet", index=False)
    cleaning_log.to_csv(REPORTS_DIR / "netflix_cleaning_log.csv", index=False)
    match_summary.to_csv(REPORTS_DIR / "netflix_imdb_match.csv", index=False)

    print(cleaning_log.to_string(index=False))
    print()
    print(match_summary.to_string(index=False))
