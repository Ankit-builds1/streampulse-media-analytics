# Anomaly detection: evaluation

Code: `streampulse/anomalies.py`. Run with `python -m streampulse.anomalies`; output in `reports/anomalies.csv`.

## Method

- **Series:** new videos entering each country's trending list per day, per category (3 countries x 15 categories,
  59,490 country-category-days). After one of the 20 days with no list, two days of new videos land on one date, so
  counts are divided by the gap (474 series-days adjusted).
- **Score:** a robust z-score against the previous 28 list days only, using the median and median absolute deviation
  (MAD) so earlier spikes do not hide later ones. The day itself is never in its own baseline. MAD has a floor of one
  video so near-empty categories do not produce huge scores.
- **Flag:** z of 4 or more and at least 8 new videos, so a jump from 1 to 4 videos in a quiet category is not flagged.
- **Explanation:** the smaller Groq model (`openai/gpt-oss-20b`) reads up to 15 titles that entered the list that day
  and writes one or two sentences on what they have in common. The reply must be JSON with under 60 words, or it is
  retried once and then left empty. The top 5 titles are saved next to each explanation so it can be checked.

## Results

284 spikes flagged (US 92, UK 112, India 80), about 0.5% of country-category-days. Only 3 fall in the weeks after
India's 6 October 2022 list change.

The 20 largest spikes all have an explanation, and most match the titles behind them, for example:

| Spike | Explanation (summarised) |
|---|---|
| India, News & Politics, 24 Aug 2023 (18 new videos vs a usual 2) | Chandrayaan-3 landing on the Moon |
| UK, News & Politics, 9 Sep 2022 (13 vs 0) | Death of Queen Elizabeth II |
| UK, News & Politics, 21 Dec 2020 (14 vs 0) | Tier 4 COVID restrictions announced |
| India, Sports, 24 Oct 2022 (12 vs 1) | India vs Pakistan, T20 World Cup |
| UK, News & Politics, 25 Feb 2022 (10 vs 0) | Russian invasion of Ukraine |
| UK, Sports, 14 Nov 2022 (26 vs 5) | Mostly UFC 281, with some football |

## What went wrong during development

- **Echoed input.** In the first run, 11 of 20 replies repeated the whole prompt as Markdown (200 to 330 words). Asking
  for a short JSON answer and checking it in code fixed this: 20 of 20 usable in the final run.
- **Forced themes.** A UK music spike on 28 Oct 2023 was described as "both titles are Taylor Swift songs" when only 2
  of 15 were; the rest were unrelated releases. The prompt now says to call a spike mixed when most titles do not share
  a theme, and that spike is now described as a mix.
- **A changed date.** One note called an NFL "2023 Super Wild Card Weekend" the 2024 Wild Card; the rule against
  changing facts was made explicit.
- **Rate limits.** Explaining 20 spikes in a row hit the small model's per-minute token limit; the Groq client now
  retries up to 5 times and waits as long as Groq asks.

## Limitations

- Explanations describe the titles, not causes, and an LLM can still overstate a theme; the saved titles are there to
  check against.
- The threshold (z of 4, at least 8 videos) was chosen by judgment, not tuned against labelled events, so there is no
  precision or recall figure.
- Only spikes are detected, not drops.
