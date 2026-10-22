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
