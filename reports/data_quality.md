# Data quality summary

What was wrong with the raw data, what was fixed, and what was left as a known limitation.
Counts come from `reports/cleaning_log.csv`, `reports/netflix_cleaning_log.csv`,
`reports/netflix_imdb_match.csv` and `notebooks/01_raw_data_first_look.ipynb`. Rebuild with
`python -m streampulse.clean` and `python -m streampulse.netflix`.

## Coverage

| Source | Period | Raw rows | Clean rows |
|---|---|---|---|
| YouTube trending (IN, US, GB) | 2020-08-12 to 2024-04-15 | 788,855 | 777,826 |
| Netflix catalog | added 2008-01-01 to 2021-09-25 | 8,807 | 8,802 |
| IMDb ratings | snapshot downloaded 2026-10-22 | 563,682 rated movies and series | used for matching only |

The YouTube dataset is described as updated daily, but it stopped on 2024-04-15. Every YouTube
finding describes that period, not today.

## YouTube trending

One row is one video on one country's trending list on one day. A video that trends for six days
appears six times.

| Country | Raw rows | Clean rows | Unique videos | Unique channels |
|---|---|---|---|---|
| IN | 251,277 | 248,111 | 78,847 | 4,521 |
| US | 268,787 | 264,717 | 47,142 | 8,302 |
| GB | 268,791 | 264,998 | 47,607 | 7,571 |

### Fixed

| Problem | Rows | What was done and why |
|---|---|---|
| Same video listed twice on the same day | 11,029 | Kept the snapshot with the most views. In 94.8% of the pairs the view counts differ, so these are two snapshots of the same day, not copies. Views only grow, so the higher count is the later one. This also removed the 282 exact duplicate rows. |
| `view_count` is 0 | 190 | Set to missing. These 26 videos (Google Doodles, The Royal Family, YouTube announcements) hide their view counter; a trending video was not unwatched. |
| Likes are 0 because ratings are disabled | 5,274 | Set likes to missing. Counting them as 0 would drag down like ratios for categories that disable ratings more often. |
| Comment count is 0 because comments are disabled | 9,888 | Set to missing, same reason. |
| Tags are the text `[None]` | 130,680 | Replaced with an empty string: the video has no tags. |
| `dislikes` is 0 for every row after 2021-12-13 | all rows | Column dropped. YouTube stopped publishing dislike counts. |
| Missing channel title | 1 | Filled from other rows of the same channel. |
| Category id 29 has no name in the IN and GB category files | 0 rows lost | Category names merged from all three country files. |

### Known issues, not fixed

- **20 missing days per country.** No list exists for those days. Trending duration is slightly
  undercounted for videos whose run spans a gap.
- **Views going down.** 1,766 day-to-day decreases in view count for the same video. YouTube removes
  invalid views after audits, so this is platform behaviour, not a data error.
- **Zero comments without the disabled flag.** 2,584 rows. These may be genuine zeros and are kept.
- **Extreme view counts.** The median trending video has 0.77M (GB) to 0.95M (IN) views; the maximum
  is 1.4B (Discord's April 2024 "Loot Boxes" video, which was promoted inside the Discord app). Kept,
  because it is real. Analyses use medians and log scales.
- **India's list is often shorter than 200 videos a day**, while US and GB are almost always 200.
  India also has the most unique videos (78,847 vs about 47,000). This looks like faster turnover,
  which is a question for the analysis, not a cleaning problem.
- **India's data has a break on 2022-10-06: YouTube Shorts left the trending list.** Found during the
  engagement analysis, explained during topic discovery. On 5 October 2022, 79 of India's 200 trending videos
  were Shorts (titles tagged #shorts); from 6 October there were none, the list stopped holding a steady 200
  videos, and median likes per 1,000 views dropped from about 60 to about 42. Shorts left the US and UK lists
  earlier, around April 2022. Time to trend and time on the list in India did not change. Engagement analyses
  treat India as two periods.
- **Encoding.** A check for broken characters flagged 13 rows, but on inspection all were correct
  text (for example SÃO PAULO). No fix needed.

## Netflix catalog and IMDb ratings

### Fixed

| Problem | Rows | What was done |
|---|---|---|
| Duration written in the `rating` column ("74 min") and `duration` empty | 3 | Moved to `duration`; rating set to missing. |
| `date_added` with a leading space | 88 | Stripped, then parsed as a date. |
| Same title listed twice, differing in capitalisation and `date_added` | 5 | Kept the earliest `date_added`. Matched on normalised title, type, year, duration and country. Country is in the key because two different 2019 shows are both called "What If". |
| `date_added` missing | 10 | Left missing. |

### Matching to IMDb

Netflix has no IMDb id, so titles are matched on normalised title (lowercase, no accents or
punctuation, "&" as "and") plus type. Year rules:

- Movies: IMDb year within one year of Netflix `release_year`.
- TV shows: series start year on or before Netflix `release_year`. For TV, Netflix records the
  latest season's year, not the first (Narcos is listed as 2017; it started in 2015).
- If several IMDb titles fit, the one with the most votes is used.

| Type | Titles | Matched | Match rate |
|---|---|---|---|
| Movie | 6,127 | 5,204 | 84.9% |
| TV Show | 2,675 | 2,260 | 84.5% |
| All | 8,802 | 7,464 | 84.8% |

A random sample of 30 matches was checked by hand and all 30 were correct.

### Known issues, not fixed

- **15% of titles have no rating.** Typical causes: Netflix-specific names ("Petta (Telugu Version)"),
  longer marketing titles ("Indiana Jones and the Raiders of the Lost Ark" vs "Raiders of the Lost
  Ark"), niche content with no IMDb rating, and 10 titles in non-Latin script.
- **Some matches are wrong.** 3 IMDb ids are attached to two different Netflix titles, so one title
  in each pair has the wrong rating: "In Laws" / "The In-Laws", "Veronica" / "Verónica" (two different
  2017 films) and "WHAT / IF" / "What If?" (two different 2019 shows). Title matching cannot tell
  same-name works apart when the year also fits.
- **Low vote counts.** 535 matched titles have fewer than 100 IMDb votes, so their ratings are noisy.
  The analysis sets a minimum vote count and states it.
- **Different time points.** The catalog is from September 2021, the ratings from October 2026.
- **Missing metadata kept as missing:** director 2,633, country 831, cast 825, rating 7.

## Rules for the analysis

- Exclude missing likes, comments and views from ratios; never treat them as 0.
- Do not use dislikes.
- Use medians for view counts.
- State the period for every YouTube finding (Aug 2020 to Apr 2024).
- State the minimum IMDb vote count used in any rating comparison.
