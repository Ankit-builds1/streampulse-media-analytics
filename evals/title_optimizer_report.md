# Title optimizer: evaluation

Code: `streampulse/title_optimizer.py`. Run with `python -m streampulse.title_optimizer`; the latest run is saved in
`title_optimizer_results.csv`.

## How it works

1. The LLM (`openai/gpt-oss-120b` on Groq, temperature 0.7) suggests 3 alternative titles. Its instructions include
   findings from analysis 5 and the virality model: title style has a small effect, question marks were linked to
   slightly shorter runs in all three countries, other style features showed no consistent effect, and Indian
   titles commonly use the "|" separator. It is told to keep the title accurate, keep the original language and add
   no new numbers, names or claims.
2. Each suggestion is scored by the virality model with every other feature of the video unchanged, so the score
   difference comes from the title alone. A test checks that scoring the original title reproduces the model's
   prediction for that video exactly.
3. Code checks each suggestion and flags it if it adds a number not in the original, adds a format label the
   original does not have (such as "Live Performance" or "Official"), exceeds YouTube's 100-character limit, or
   repeats the original.

## Results

15 videos from the test period (5 per country), 3 suggestions each, run three times because suggestions vary:

| Run | Mean gain of the best clean suggestion | Videos with a higher-scoring suggestion | Largest gain |
|---|---|---|---|
| 1 | +0.95 percentage points | 80% | +3.8 points |
| 2 | +0.46 | 67% | +2.5 |
| 3 | +0.64 | 67% | +3.8 |

Gains are in the model's predicted probability of becoming a long-runner. They are small, as expected: titles and
tags account for about 6% of the model's explanations (`virality_report.md`).

## What went wrong

- **Suggestions that change what the video claims to be.** For a K-pop music video titled "SOOJIN - BLACK FOREST",
  one run suggested "(Live Performance)" and "| Full Song"; for a gym video, "Behind the Scenes". The prompt forbids
  new claims, but the model added them anyway. A check for common format labels was added after run 1; it flags the
  most common cases, but it cannot catch every new claim made in words, so suggestions still need a human check.
- **The model scores style, not meaning.** It only sees title features such as question marks, "|", capital words,
  emoji, length and sentiment. Rewordings that keep the same features get identical scores, so the score cannot judge
  whether a title is clearer or more interesting.

## Limitations

- No real-world test: the gains are model predictions, not measured results from publishing different titles.
- The virality model under-predicts long runs for 2023-2024 US and UK videos (drift), so absolute probabilities there
  are too low; the comparison between titles of the same video is what matters.
- 15 videos per run is a small sample.
