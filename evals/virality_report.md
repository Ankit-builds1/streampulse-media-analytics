# Virality predictor: evaluation

Notebook: `notebooks/12_virality_model.ipynb`. Features: `streampulse/virality.py`. Training: `streampulse/virality_model.py`
(`python -m streampulse.virality`, then `python -m streampulse.virality_model`). Metrics: `virality_results.csv`.

## Task

The data only contains videos that trended, so "will it trend?" cannot be learned. The task was reframed to staying
power, predicted on the morning a video first appears on the list:

- **Classifier:** will the run reach the top quarter of run lengths for its country (7+ days in the US and UK, 5+ in
  India, set from training data only)?
- **Regressor:** how many days will it stay on the list?

Features use only what is known that morning. Channel history counts only runs that ended before the run started;
`tests/test_virality.py` checks this rule, including a run that starts the same day another ends.

## Data split

| Split | First trending date | Runs | Long-runner rate |
|---|---|---|---|
| Train | Aug 2020 to Dec 2022 | 114,560 | 21.0% |
| Validation (early stopping) | Jan to Jun 2023 | 23,267 | 22.4% |
| Test | Jul 2023 to Apr 2024 | 34,609 | 28.2% |

## Results on the test period

| | Baseline (channel history) | LightGBM |
|---|---|---|
| Long-runner ROC-AUC | 0.698 | 0.790 |
| Long-runner PR-AUC | 0.465 | 0.605 |
| Days on list, mean absolute error | 1.21 | 1.08 |

| Country | AUC LightGBM / baseline | Long-runner rate actual / predicted | Days error LightGBM / baseline | Long-runners in top 10% of scores |
|---|---|---|---|---|
| India | 0.883 / 0.781 | 17.0% / 18.7% | 0.88 / 1.06 | 72% |
| US | 0.724 / 0.639 | 42.0% / 17.0% | 1.39 / 1.39 | 79% |
| UK | 0.738 / 0.620 | 35.8% / 28.0% | 1.15 / 1.33 | 76% |

## What drives predictions

Share of mean absolute SHAP value on 5,000 test runs (LightGBM's exact SHAP values, checked against the `shap`
library):

| Feature group | Classifier | Regressor |
|---|---|---|
| Channel history | 36% | 32% |
| First-day performance | 36% | 26% |
| Market and category | 15% | 34% |
| Upload timing | 7% | 4% |
| Title and tags | 6% | 4% |

## Limitations

- **Drift.** US and UK runs grew longer in 2023 and 2024. The model still ranks them better than the baseline, but
  its probabilities are too low for those countries and its US day estimates are no better than the baseline.
  Retraining on recent data would be needed before use.
- It predicts staying power once trending, not whether a video will trend.
- `days_to_trend` partly reflects when the daily list was captured, not only how fast a video caught on.
- SHAP values describe what the model uses, not causes.
