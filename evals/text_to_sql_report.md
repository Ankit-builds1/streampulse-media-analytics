# Ask the Data: Text-to-SQL evaluation

Model: `openai/gpt-oss-120b` on Groq, temperature 0. Run with `python -m streampulse.ask_eval`.
Questions and answer key: `text_to_sql_questions.json`. Every answer: `text_to_sql_results.csv`.

## Method

- 20 questions: 6 easy, 8 medium, 4 hard, and 2 trick questions that should be refused (one asks for dislikes,
  which the data does not have; one asks to delete data).
- Each question has a hand-written reference query. Its answers were checked against the Phase 3 analyses before
  use.
- A model answer passes if it has the same number of rows as the reference and every reference column is matched
  by some column in the answer. Column names do not matter, extra columns are allowed, numbers may differ by
  rounding (0.5%), and a share may be written as a percentage. Row order only matters for top-N and year-by-year
  questions. A trick question passes if the system refuses.
- Only the SQL result is graded, not the written answer.
- The full set was run 3 times, because the model can write a different query for the same question.

## Results

| | Passed | Accuracy |
|---|---|---|
| Run 1 | 20 / 20 | 100% |
| Run 2 | 18 / 20 | 90% |
| Run 3 | 20 / 20 | 100% |
| **All runs** | **58 / 60** | **96.7%** |

| Difficulty | Passed |
|---|---|
| Easy | 18 / 18 |
| Medium | 24 / 24 |
| Hard | 10 / 12 |
| Trick (refusal) | 6 / 6 |

Median time per question 1.45 seconds, 90th percentile 4.9 seconds. 3 of 60 answers needed the automatic retry
after a SQL error; 2 of those then passed.

## Failures

Both failures are real model errors, and both were in run 2.

1. **Genre split with a broken regex (question 17).** The model split Netflix's genre list with
   `regexp_split_to_array(listed_in, ',\\s*')`. The doubled backslash makes the pattern look for a literal
   backslash, so nothing was split and "Anime Series, International TV Shows" was treated as one genre. The same
   mistake appeared in 2 of the 6 attempts at this question across both evaluation rounds.
2. **Join fan-out (question 18).** To average days from upload to first trend, the model joined `trending_videos`
   (one row per video) to `trending` (one row per video per day). Each video was counted once for every day it
   trended, 42,725 rows instead of about 7,300 videos, giving 1.32 days instead of 1.41.

## What the evaluation changed

- The first round scored 95%, but one of its three failures was the grader, not the model: for "which month",
  the model correctly answered year 2022 and month 8 in two columns, while the reference had a single "2022-08"
  column. Questions can now list more than one correct reference shape.
- The prompt was not changed to fix the failures above. Tuning the prompt on these 20 questions would make this
  score look better without showing whether the system improved. A fix for comma-separated lists should be tested
  on new questions.

## Limitations

- 20 questions is a small test set, and they were written by the same person who wrote the prompt.
- Columns are compared one at a time, so for unordered multi-column answers the pairing of values across columns
  is not checked.
- The written answer and the chart are not graded here; the number check in `streampulse/ask.py` covers the answer
  text separately.
