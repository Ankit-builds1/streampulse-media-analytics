# Findings

Each analysis: business question, method, finding with numbers, limitation. YouTube results cover trending
lists in India, the US and the UK from 2020-08-12 to 2024-04-15. Details and charts are in the linked notebooks.

## 1. Time to trend by category and country

Notebook: `notebooks/03_time_to_trend.ipynb`

**Question.** How quickly does a video reach the trending list after upload, and does that depend on category
or country?

**Method.** Days from upload date to first trending day (UTC dates) for 173,025 video-country pairs. Outcome:
trended by the next day. Wilson confidence intervals for shares, Kruskal-Wallis with epsilon squared for group
differences, and logistic regression with category and upload hour as controls.

**Finding.**

- 87.3% of Indian trending videos reached the list by the day after upload, against 57.4% (US) and 57.2% (UK).
- India is ahead in every category: its slowest category (Howto & Style, 82.5%) beats the fastest US or UK
  category (UK Music, 65.9%). Category explains little within a country (epsilon squared 0.009 to 0.021) compared
  with country (0.117).
- About half of India's lead in odds comes from upload timing. The list is captured once a day in the UTC morning,
  Indian creators upload early in the UTC day and US and UK creators late. Controlling for upload hour and
  category, India's odds of trending by the next day fall from 5.5 to 2.7 times the US's (95% CI 2.6 to 2.8).
  The UK and US are about equal (1.06).
- About 95% of videos that trended did so within two days of upload, in all three countries.

**Limitations.** Only videos that trended are in the data, so this shows how fast successful videos got there,
not what makes a video trend. The capture time is not recorded, so time to trend is measured in calendar days,
not hours. The upload-hour control would also absorb any real time-of-day effect.

## 2. Trending duration: survival analysis

Notebook: `notebooks/04_trending_duration.ipynb`

**Question.** Once a video trends, how many days does it stay on the list, and does that differ by country and
category?

**Method.** Kaplan-Meier survival curves of days on the list for 173,025 video-country pairs, with videos still
trending on 2024-04-15 treated as right-censored (589, 0.3%). Log-rank tests across countries and across categories
within each country. Restricted mean survival time over 15 days (RMST) for the size of differences, and the daily
exit rate for the shape of a video's life on the list.

**Finding.**

- Median time on the list is 3 days in India and 6 days in the US and UK (log-rank chi-squared 64,832, p < 0.001).
  RMST: 3.15 days in India against 5.61 (US) and 5.58 (UK).
- The shape differs. In India 18% of videos are gone after one day and the exit rate rises every day after. In the
  US and UK fewer than 5% leave on each of the first three days, then most leave between days 5 and 8.
- The gap holds in every category present in all three countries. India's longest-lasting category (Film &
  Animation, 4.02 days) is shorter than the shortest US or UK category (UK Sports, 4.99 days), so India's short
  trending life is not a category-mix effect.
- Category differences within a country are small: RMST ranges 2.72 to 4.02 days (India), 5.06 to 5.92 (US) and
  4.99 to 5.94 (UK). Sports is the shortest-lived category in the US and UK.
- With so little censoring, Kaplan-Meier confirmed the simple medians from the SQL queries rather than changing them.

**Limitations.** Days on the list counts appearances, and 7.6% of videos have a gap in their run (dropping off and
returning, or one of the 20 days with no list). The list holds at most 200 videos, so duration also depends on
competition from other videos. The analysis is descriptive: it shows where videos last longer, not why.
