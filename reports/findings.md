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
- India's data has a break on 2022-10-06 (see analysis 3). India's share trending by the next day is the same on
  both sides of it (86.9% before, 87.9% after), so this finding holds in both periods.

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
- India's average time on the list is the same on both sides of the 2022-10-06 data break (3.24 days before,
  3.03 after), so the India gap is not an artefact of it.

**Limitations.** Days on the list counts appearances, and 7.6% of videos have a gap in their run (dropping off and
returning, or one of the 20 days with no list). The list holds at most 200 videos, so duration also depends on
competition from other videos. The analysis is descriptive: it shows where videos last longer, not why.

## 3. Engagement ratios by category

Notebook: `notebooks/05_engagement.ipynb`

**Question.** For the same number of views, which categories get more likes and comments, and how do countries
compare?

**Method.** Likes and comments per 1,000 views on each video's first trending day, for about 173,000
video-country pairs. Videos with ratings or comments turned off, or hidden view counts, are excluded from the
relevant measure. Medians with distribution-free confidence intervals, Kruskal-Wallis with epsilon squared, and
linear regression on the log scale with category, country-period and log(views), using HC1 robust standard errors.

**Finding.**

- Measuring on the right day matters. Likes per 1,000 views are about 20% lower on a video's peak-views day than
  on its first trending day (US 54.6 vs 42.5). US and UK videos stay on the list longer, so a peak-day comparison
  would understate them against India. The earlier SQL query and EDA chart used the peak day and were updated.
- Category drives likes. Within a country it explains 20% (India) to 37% (UK) of the variation. Averaged over
  countries, Comedy gets 99.5% more likes per view than Entertainment (95% CI 96 to 103), Music 89% more, Sports 44%
  fewer and News & Politics 62% fewer. News & Politics has the fewest likes per view in every country.
- Rankings differ by country: Music and Comedy lead in the US and UK, Gaming (97.5) and Science & Technology (92.7)
  in India, where Entertainment gets 24.9, half its US level.
- Country drives comments. Indian videos get 58% to 63% fewer comments per view than US videos after controls,
  fewer in 11 of 13 categories. The UK is 8% below the US. Ten times more views means 33% fewer comments per 1,000
  views but only 4% fewer likes.
- India's data has a break on 2022-10-06: the daily list stopped holding 200 videos and likes per view dropped from
  about 60 to about 42 per 1,000 that day, in every category. Before the break Indian likes per view matched the US
  (+2.9%); after it they are 29.5% lower. The cause is not in the data.

**Limitations.** The cause of the India break is unknown, so Indian engagement from different periods should not
be compared directly. Only trending videos are included. Likes and comments can be inflated by bots or giveaways.
The regression's category effects are averages over countries.

## 4. Best time to publish

Notebook: `notebooks/06_publish_time.ipynb`

**Question.** Does the day and hour a video is published affect how well it does?

**Method.** The data has only trending videos, so it cannot show whether a time slot changes the chance of
trending, and analysis 1 showed time to trend depends on the list's capture time. The question answered is:
among trending videos, do those published at some local times reach more people? Outcome: log peak views for
172,401 completed runs. Day-by-hour heatmaps of the difference from the country average, raw and after
controlling for category and channel strength (the channel's average log peak views on its other trending
videos, standing in for audience size). Type II ANOVA F-tests with partial eta squared.

**Finding.**

- Raw differences look large: by upload hour, peak views range from about 50% below the country average (India,
  05:00 IST) to about 120% above (UK, 05:00, which is midnight US Eastern). The day-by-hour slot explains 3.2%
  (India) to 6.2% (UK) of the variation.
- Most of it is the channel, not the clock. Channel strength explains 55% to 63% of the variation, over 200 times
  as much as upload hour. After controls, hour effects stay between -11% and +14% and the full slot pattern explains
  0.6% to 1.2%.
- The adjusted effects are still statistically significant (p below 1e-9) but small in practical terms. The one
  pattern that survives is that overnight uploads (00:00 to 05:00 local) do about 5% to 14% better in the US and
  UK, likely because those slots hold scheduled big releases such as Friday-midnight music.
- Business answer: there is no universal best time. Who uploads matters far more than when.

**Limitations.** Only trending videos are included. Channel strength is a proxy from other trending videos, and
4.5% of runs (single-video channels) are left out of the adjusted models. US local time uses Eastern time. The
analysis is observational, so remaining effects can still come from unmeasured factors such as planned launches.

## 5. Title features and trending duration

Notebook: `notebooks/07_title_features.ipynb`

**Question.** Among trending videos, do titles with numbers, questions, capital letters, emoji, hashtags or
strong sentiment stay on the list longer?

**Method.** Nine rule-based title features plus VADER sentiment (positive, neutral, negative; titles not mostly
in Latin script are marked "not scored", 24.8% of Indian titles). Outcome: days on the list for 172,436 completed
runs. Linear regression per country with HC1 robust standard errors, controlling for category, trending year,
India's data period and the channel's typical run length on its other trending videos. A block F-test measures
how much all title terms add together.

**Finding.**

- Titles alone explain 1.5% (US) to 3.7% (India) of the variation in days on the list. After controls, all title
  terms together explain 0.13% to 0.39% of what is left, while the channel's typical run length explains 7% to 18%.
- Raw gaps shrink after controls: US `#shorts` titles run 0.88 days shorter raw and 0.25 days adjusted.
- No adjusted effect exceeds a quarter of a day. The largest is `#shorts`: 0.25 days shorter in the US but 0.22
  days longer in India. Only question marks point the same way in all three countries (0.04 to 0.08 days
  shorter), significant in India and the US only.
- Sentiment has no consistent effect: positive and negative titles run slightly longer than neutral ones in the
  US, negative titles run 0.15 days shorter in India, and the UK shows no clear effect.
- With 33 coefficients tested, one or two pass p < 0.05 by chance, so single-country effects are weak evidence.
- Business answer: common title advice does not keep a video trending. The Phase 4 title optimizer should be
  framed around clarity and click appeal, not time on the list.

**Limitations.** Only trending videos are included, so titles may still matter for whether a video trends at all.
VADER misses non-Latin titles and most Hinglish. The features are simple rules ("caps word" also counts acronyms).
Single-video channels are excluded from the controlled models.

## 6. India vs US vs UK: category mix and overlap

Notebook: `notebooks/08_country_comparison.ipynb`

**Question.** Can the three markets be treated as one audience, or does each need its own content plan?

**Method.** Chi-square test of independence on the country-by-category table of 173,596 video-country pairs,
with Cramer's V and Pearson residuals. Overlap as shared videos and the Jaccard index, by pair and by quarter.
Share of each category's videos that trend in more than one country. Day difference in first trending date for
shared videos.

**Finding.**

- The category mix differs significantly (chi-squared 26,029, df 28, p < 0.001, Cramer's V 0.27). India differs
  strongly from the US (V 0.37) and the UK (V 0.39); the US and UK differ little (V 0.12).
- India over-indexes on Entertainment (42.9% of its trending videos against about 20%) and People & Blogs (16.2%
  against about 9%). The US leans to Gaming (20.0%) and Music (15.6%), the UK to Sports (20.4%) and Gaming (16.5%).
- The US and UK share 24,447 trending videos, 52% of each country's list (Jaccard 0.35 for videos, 0.47 for
  channels), and that held in every quarter (0.32 to 0.37). India shares 2.2% of its videos with the US and 2.5%
  with the UK.
- Gaming (38% of its videos trend in more than one country), Film & Animation (31%) and Science & Technology (26%)
  travel best; News & Politics (9%), People & Blogs (10%) and Entertainment (11%) stay local. What crosses into
  India is global gaming, K-pop, global creators and brand launches (Clash of Clans, BTS, MrBeast, Marvel, Apple).
- Neither the US nor the UK leads: shared videos start trending on the same day 74% of the time. India's list picks
  up shared videos first in about 25% of cases against 8% the other way.
- Business answer: one plan can serve the US and UK; India needs its own, built on local entertainment and creators.

**Limitations.** Categories are broad and self-chosen. India's longer daily intake makes overlap shares
asymmetric. "Which country is first" uses list dates and inherits the capture-timing issue from analysis 1.

## 7. Channel concentration

Notebook: `notebooks/09_channel_concentration.ipynb`

**Question.** Is the trending list open to many creators, or do a few channels take most of the space?

**Method.** Each video appearance on a day's list is one slot; a channel's share is its slot count. Lorenz curves
and Gini coefficients per country with 95% bootstrap confidence intervals, yearly Gini for the full years 2021 to
2023, and Gini within each category. Only channels that trended at least once are counted.

**Finding.**

- Gini is 0.67 to 0.69 in every country over the whole period: India 0.683 (95% CI 0.666 to 0.699), US 0.674
  (0.664 to 0.684), UK 0.689 (0.676 to 0.703). The intervals overlap.
- 7% to 9% of trending channels hold half of all list slots; the top 1% hold 15% to 18%; the bottom half hold
  7% to 9%.
- India's list is led by TV networks and Pakistani drama channels, the US by sports leagues and broadcasters and
  MrBeast, the UK by football media and the Sidemen. India's top 10 channels hold 7.9% of slots against 5.3% (UK)
  and 3.5% (US).
- Within a single year India is the most concentrated (Gini 0.59 to 0.63 against 0.55 to 0.58), and US and UK
  concentration barely moved from 2021 to 2023.
- Sports is the most concentrated category in the US and UK (0.74); News & Politics is among the least (0.56 to
  0.64).

**Limitations.** Channels that never trended are not in the data, so concentration across all of YouTube is
higher. Gini depends on the time window, so only equal windows are compared.
