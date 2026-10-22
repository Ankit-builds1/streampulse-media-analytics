# StreamPulse

Content performance analytics on YouTube trending data (India, US, UK), with IMDb ratings and the Netflix catalog for context.

Work in progress.

## Data

Raw data is not committed. Download the files below and place them in `data/raw/` as shown.

**YouTube Trending Video Dataset** (Kaggle, rsrishav)
https://www.kaggle.com/datasets/rsrishav/youtube-trending-video-dataset

Download only these six files from the dataset page into `data/raw/youtube/`:

- `IN_youtube_trending_data.csv`, `IN_category_id.json`
- `US_youtube_trending_data.csv`, `US_category_id.json`
- `GB_youtube_trending_data.csv`, `GB_category_id.json`

**IMDb non-commercial datasets**
https://developer.imdb.com/non-commercial-datasets/

Download these two files into `data/raw/imdb/` and keep them gzipped; pandas reads them directly.

- https://datasets.imdbws.com/title.basics.tsv.gz
- https://datasets.imdbws.com/title.ratings.tsv.gz

IMDb data is for personal and non-commercial use only.

**Netflix Movies and TV Shows** (Kaggle, shivamb)
https://www.kaggle.com/datasets/shivamb/netflix-shows

Download `netflix_titles.csv` into `data/raw/netflix/`.

Expected layout:

```
data/raw/
  youtube/   IN_, US_, GB_ trending CSVs and category JSONs
  imdb/      title.basics.tsv.gz, title.ratings.tsv.gz
  netflix/   netflix_titles.csv
```
