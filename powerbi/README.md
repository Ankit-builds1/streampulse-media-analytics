# StreamPulse in Power BI

A seven-page Power BI report built from the same data and rules as the analysis and the Streamlit app. Every
measure has an expected value in [`expected_values.md`](expected_values.md), so the report can be checked against
the Python results instead of trusted.

| File | What it is |
|---|---|
| `data/*.csv` | The tables the report loads. Not committed; rebuild with `python -m streampulse.powerbi_export` |
| `expected_values.md` | What each measure should show with no filters, generated from the same CSVs |
| `measures.dax` | Every DAX measure, with comments on the rules they apply |
| `streampulse_theme.json` | Dark theme matching the app |
| `StreamPulse.pbix` | The finished report (added once built) |

## 1. Setup (about 20 minutes)

1. **Install Power BI Desktop** from the Microsoft Store (free, Windows only).
2. **Export the tables** from the project folder:
   ```
   python -m streampulse.powerbi_export
   ```
   This writes 10 CSVs to `powerbi/data/` and refreshes `expected_values.md`.
3. **Load the CSVs.** Home > Get data > Text/CSV, one file at a time, choosing **Transform data** for the first so
   you can check types. Load all ten:
   `fact_trending_runs`, `fact_channel_slots`, `fact_country_overlap`, `dim_country`, `dim_category`,
   `dim_channel`, `dim_date`, `netflix_titles`, `spikes`, `topic_monthly`.
4. **Check column types** in Power Query (the icon left of each column name), then Close & Apply:

   | Table | Column | Type |
   |---|---|---|
   | fact_trending_runs | `first_trending_date`, `last_trending_date` | Date |
   | fact_trending_runs | `published_at_utc` | Date/Time |
   | fact_trending_runs | `video_id`, `channel_id`, `run_key` | Text (an id like `0123` must not become a number) |
   | fact_trending_runs | `likes_per_1k_views`, `comments_per_1k_views` | Decimal number |
   | dim_date | `date`, `month_start`, `week_start` | Date |
   | netflix_titles | `date_added` | Date |
   | spikes | `trending_date` | Date |
   | topic_monthly | `month` | Date |

5. **Import the theme.** View > Themes > Browse for themes > `streampulse_theme.json`.
6. **Set the page size.** Format page > Canvas settings > 16:9 (1280 x 720), for every page.

## 2. Data model

Open Model view and create these relationships (all one-to-many, single direction, from the dim table to the
fact table). Delete any relationship Power BI created automatically that is not in this list.

| From (one) | To (many) |
|---|---|
| `dim_country[country]` | `fact_trending_runs[country]`, `fact_channel_slots[country]`, `fact_country_overlap[country]`, `spikes[country]`, `topic_monthly[country]` |
| `dim_category[category]` | `fact_trending_runs[category]`, `spikes[category]` |
| `dim_channel[channel_id]` | `fact_trending_runs[channel_id]`, `fact_channel_slots[channel_id]` |
| `dim_date[date]` | `fact_trending_runs[first_trending_date]`, `spikes[trending_date]` |

```
                 dim_date          dim_category
                     \                 /
   dim_country --- fact_trending_runs --- dim_channel
        |   \                               /
        |    fact_channel_slots ----------+
        |    fact_country_overlap, spikes, topic_monthly
   netflix_titles (stands alone)
```

Then:

- **Mark `dim_date` as the date table:** select it > Table tools > Mark as date table > `date`.
- **Sort columns** (select the column > Column tools > Sort by column):
  `dim_date[month]` by `month_start`, `dim_date[weekday]` by `weekday_number`,
  `fact_trending_runs[upload_weekday_name]` by `upload_weekday_local`.
- **Hide technical columns** from report view (right-click > Hide): `run_key`, `full_run_known`, `completed_run`,
  `country_color`, `upload_weekday_local`, `weekday_number`, `month_number`.

## 3. Measures

Home > Enter data > name the table `_Measures` > Load. Select it, then add each measure from
[`measures.dax`](measures.dax) with **New measure** (one measure per paste). Set formats in Measure tools:

| Measure | Format |
|---|---|
| `% Trended By Next Day`, `Share Of Country Runs %`, `Upload Slot Share %`, `Top 10 Channel Share %`, `IMDb Match Rate %` | Percentage, 1 decimal |
| `Median Likes per 1k Views`, `Average Days On List`, `Median IMDb Rating` | Decimal, 1 decimal |
| `Median Comments per 1k Views` | Decimal, 2 decimals |
| Counts, `Median Days On List`, `Median Peak Views` | Whole number, thousands separator |

**Quick check before building pages:** put a Card with `Trending Runs` on a blank page. It must show 173,596. Put
a Table with `dim_country[country]` and `% Trended By Next Day`: 87.3%, 57.4%, 57.2%. If both match
`expected_values.md`, the model is right. Delete the test page.

## 4. Country colours

Theme colours go to series in alphabetical order (GB, IN, US), which would make the UK blue. To keep India blue,
the US orange and the UK green as in the app: on any bar or column chart split by country, Format visual >
Columns (or Bars) > Colors > **fx** > Format style **Field value** > based on field **First country_color**. For
line charts with country in the legend, set the three colours by hand under Lines > Colors: IN `#2A78D6`,
US `#EB6834`, GB `#1BAF7A`.

## 5. Pages

Every page has the same header: a text box with the page title (Segoe UI Semibold 20) and one line saying what the
page answers, plus a **slicer panel** on the left (synced across pages with View > Sync slicers):
`dim_country[country_name]` (tile style), `dim_category[category]` (dropdown) and `dim_date[date]` (between).
Netflix and Spikes pages do not use the date slicer.

### Page 1. Overview

*What trends, where, and how fast.*

| Visual | Fields | Check (no filters) |
|---|---|---|
| 4 Cards (top row) | `Trending Runs`, `Channels`, `% Trended By Next Day`, `Median Days On List` | 173,596 / 14,953 / 70.9%* / 5 |
| Clustered column | X: `dim_country[country_name]`, Y: `Trending Runs`, colours by field value | IN 78,847, US 47,142, GB 47,607 |
| Line chart (full width) | X: `dim_date[week_start]`, Y: `Trending Runs`, Legend: `dim_country[country]`. Filter pane: `week_start` between 17 Aug 2020 and 8 Apr 2024 | No drop at either end |
| Text box | "Median of 3 days in India against 6 in the US and UK; India's lead in speed is half upload timing." | |

\* The all-country card mixes three countries; the analysis reports them separately. The weekly chart is cut to
full weeks because the first and last weeks of the data are partial and would look like sudden drops.

### Page 2. Speed and staying power

*How quickly videos reach the list, and how long they stay.*

| Visual | Fields | Check |
|---|---|---|
| Clustered bar | Y: `dim_country[country_name]`, X: `% Trended By Next Day` | 87.3%, 57.4%, 57.2% |
| Matrix (heatmap) | Rows: `dim_category[category]`, Columns: `dim_country[country]`, Values: `% Trended By Next Day`; Cell elements > Background color on, gradient from `#161B22` to `#2A78D6` | Among categories with 100+ runs, India's slowest (Howto & Style, 82.5%) beats the fastest US or UK one (UK Music, 65.9%). Tiny categories such as Nonprofits & Activism are noisy |
| Clustered column | X: `dim_category[category]`, Y: `Average Days On List`, Legend: country | India lowest in every category |
| Column chart | X: `fact_trending_runs[days_trending]` (new group, bin size 1, up to 20), Y: `Trending Runs`, small multiples: country | India peaks early; US and UK around days 5 to 8 |

### Page 3. Engagement

*Which categories get likes and comments for the same views.*

| Visual | Fields | Check |
|---|---|---|
| Clustered bar | Y: `dim_category[category]`, X: `Median Likes per 1k Views`, sorted descending | News & Politics lowest in every country |
| Clustered bar | Y: `fact_trending_runs[country_period]`, X: `Median Comments per 1k Views` | US 3.71, GB 3.36, India about 1.4 to 1.6 |
| Table | `country_period`, `Median Likes per 1k Views`, `Median Comments per 1k Views` | Matches `expected_values.md` |
| Text box (callout) | "On 6 Oct 2022 YouTube Shorts left India's trending list (79 of 200 videos the day before, none after), so India is split at that date." | |

### Page 4. Publish time

*When trending videos were uploaded, in each country's local time.*

| Visual | Fields | Check |
|---|---|---|
| Matrix (heatmap) | Rows: `upload_weekday_name`, Columns: `upload_hour_local`, Values: `Upload Slot Share %`; background colour gradient; turn off row and column totals | Cells add up to 100% for the selected country |
| Clustered column | X: `upload_hour_local`, Y: `Median Peak Views`, Legend: country | Shows the raw gap the analysis then explained away |
| Text box (callout) | "No universal best time: the channel explains over 200 times as much of a video's views as its upload hour; adjusted hour effects stay between -11% and +14%." | |

Select one country in the slicer for the heatmap; mixing time zones in one grid hides the pattern.

### Page 5. Markets and creators

*Is it one audience or three, and who holds the list.*

| Visual | Fields | Check |
|---|---|---|
| 100% stacked bar | Y: `dim_country[country_name]`, X: `Trending Runs`, Legend: `dim_category[category]` (top 8 by Top N filter) | India: Entertainment 42.9% |
| Matrix | Rows: `fact_country_overlap[country]`, Columns: `also_trending_in`, Values: `Shared Videos` | US and GB share 24,447 |
| Clustered column | X: `dim_country[country_name]`, Y: `Top 10 Channel Share %` | IN 7.9%, US 3.5%, GB 5.3% |
| Table | `dim_channel[channel_title]`, `Channel Slots`; Filter: `channel_title` Top N 15 by `Channel Slots` | Changes with the country slicer |

### Page 6. Netflix catalog

*How the catalog grew and whether its ratings changed.*

| Visual | Fields | Check |
|---|---|---|
| 3 Cards | `Netflix Titles`, `IMDb Match Rate %`, `Median IMDb Rating` | 8,802 / 84.8% / 6.7 |
| Stacked column | X: `netflix_titles[year_added]` (filter 2015 to 2021), Y: `Netflix Titles`, Legend: `type` | 2019: 2,015 titles |
| Line chart | X: `year_added`, Y: `Median IMDb Rating`, Legend: `type` | TV shows above movies every year (7.4 vs 6.4 overall) |
| Bar | Y: `main_country` (Top N 10 by `Netflix Titles`), X: `Netflix Titles` | United States first, India second |

Note on the page: 2021 covers January to September only.

### Page 7. Spikes

*Days when a category suddenly got far more new trending videos, with an AI note on what the titles shared.*

| Visual | Fields | Check |
|---|---|---|
| Card | `Spikes Flagged` | 284 |
| Scatter | X: `spikes[trending_date]`, Y: `robust_z`, Legend: country, Size: `new_videos` | Tallest point: India, News & Politics, 24 Aug 2023 (Chandrayaan-3 Moon landing, z 10.8) |
| Table | `trending_date`, `country`, `category`, `new_videos`, `baseline_median`, `explanation`, `top_titles`; sort by `robust_z` descending; word wrap on | Explanations read next to the titles they describe |

## 6. Finish

1. Compare every check above with [`expected_values.md`](expected_values.md) once more, with all slicers cleared.
2. Save as `powerbi/StreamPulse.pbix`. It stores its own compressed copy of the data, so it opens without the CSVs.
3. Export each page as an image (File > Export > Export to PDF, or a screenshot of each page at full size) and save
   them as `images/powerbi_overview.png`, `images/powerbi_speed.png` and so on, for the main README.
4. Commit the `.pbix`, the page images, and anything changed in this folder.
