# Auto insight report: evaluation

Code: `streampulse/insight_report.py`. Run with `python -m streampulse.insight_report`; output in
`reports/insight_report.md`.

## How it works

1. Ten fixed SQL queries (`FACT_QUERIES`) produce every number the report may use. Percentages and rounding are done
   in SQL, so the model only copies numbers.
2. The LLM (`openai/gpt-oss-120b`) writes a one-page summary and must cite a fact ID, such as `[F3]`, in every
   sentence that contains a number.
3. Checks, in order:
   - **Number check (code, exact):** every number in the report must match a value in the facts, allowing for
     rounding, or appear in a fact description. Citations must point to facts that exist. Full-width citation
     brackets and thin-space thousands are normalised first.
   - **Length check (code):** an empty or near-empty reply fails.
   - **Sentence audit (LLM):** a second call checks each sentence against its cited fact for the right country,
     direction, unit and wording, and flags uncited or causal claims.
4. Any failure goes back to the model with the problems listed, up to 3 attempts. Problems still present are printed
   at the end of the report, never hidden.

## Results

Four complete runs before the free daily token limit was reached:

| Run | Attempts | Problems left | Words |
|---|---|---|---|
| 1 | 3 | 0 | 195 |
| 2 | 2 | 0 | 189 |
| 3 | 1 | 0 | 220 |
| 4 | 1 | 0 | 245 |

Problems that caused rejected attempts included causal claims ("so content that performs in one market often
trends in the other") and takeaways without a cited fact.

## What went wrong during development

- **A fact dump.** The first prompt produced 77 numbers in one-sentence-per-country lists. The prompt now asks for
  the 3 or 4 main patterns and at most 15 numbers.
- **Right number, wrong meaning.** "Only 2.5% of UK videos appear in India" passed the number check, but 2.5% is the
  share of India's videos that also trended in the UK. The overlap fact now names its direction in its column names,
  and the sentence audit was added.
- **An empty report passed.** One reply was empty, which has no numbers to fail on. A length check now catches it.
- **Citations the checks could not see.** One reply cited facts as `【F1】`; these are now normalised to `[F1]`.

## Limitations

- The number check is exact; the sentence audit is an LLM and can miss errors. A manual read of run 4 found two
  claims it passed: "rapid catalog growth before the pandemic period" (the pandemic is not in any fact) and a
  suggestion to test content in one market before another (not supported by the facts). The report still needs a
  human read before it is shared.
- Each run uses up to 6 calls to the larger model, about 10,000 to 25,000 tokens, which matters on the free tier's
  200,000-token daily limit.
