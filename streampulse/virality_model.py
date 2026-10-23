import json
import os

# MLflow prints a setup hint for AI coding tools on every import; it is noise in this project's output.
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import lightgbm as lgb
import mlflow
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error, roc_auc_score

from streampulse.load import PROJECT_ROOT
from streampulse.virality import CATEGORICAL_FEATURES, FEATURES_PATH
from streampulse.virality_scoring import (  # noqa: F401  (re-exported for notebooks that import them from here)
    CATEGORIES_PATH, CLASSIFIER_PATH, FEATURE_COLUMNS, MODELS_DIR, REGRESSOR_PATH, feature_matrix, load_saved_models,
)

RESULTS_PATH = PROJECT_ROOT / "evals" / "virality_results.csv"
MLFLOW_DATABASE = PROJECT_ROOT / "mlflow.db"
MLFLOW_ARTIFACTS = PROJECT_ROOT / "mlruns"
EXPERIMENT_NAME = "virality"

SHARED_LIGHTGBM_PARAMS = {
    "n_estimators": 2000,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 50,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "verbose": -1,
}
EARLY_STOPPING_ROUNDS = 100


def training_categories(train_rows):
    """The categories seen in training for each categorical feature, so every split is encoded the same way."""
    return {column: sorted(train_rows[column].dropna().unique().tolist()) for column in CATEGORICAL_FEATURES}


def baseline_scores(train_rows, rows):
    """Channel history alone: the channel's past long-run rate and mean days, or the country's training average."""
    country_long_run_rate = train_rows.groupby("country")["long_runner"].mean()
    country_median_days = train_rows.groupby("country")["days_trending"].median()
    long_run_score = rows["channel_prior_long_run_rate"].fillna(rows["country"].map(country_long_run_rate))
    predicted_days = rows["channel_prior_mean_days"].fillna(rows["country"].map(country_median_days))
    return long_run_score, predicted_days


def classifier_metrics(actual, score):
    return {
        "roc_auc": roc_auc_score(actual, score),
        "pr_auc": average_precision_score(actual, score),
        "brier": brier_score_loss(actual, np.clip(score, 0, 1)),
        "actual_positive_rate": float(np.mean(actual)),
        "mean_predicted_probability": float(np.mean(score)),
    }


def regressor_metrics(actual, predicted):
    return {
        "mae_days": mean_absolute_error(actual, predicted),
        "rmse_days": float(np.sqrt(np.mean((np.asarray(actual) - np.asarray(predicted)) ** 2))),
    }


def fit_classifier(train_matrix, train_target, validation_matrix, validation_target):
    """LightGBM classifier with early stopping on the validation period."""
    model = lgb.LGBMClassifier(objective="binary", **SHARED_LIGHTGBM_PARAMS)
    model.fit(
        train_matrix, train_target,
        eval_X=validation_matrix, eval_y=validation_target, eval_metric="auc",
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    return model


def fit_regressor(train_matrix, train_target, validation_matrix, validation_target):
    """LightGBM regressor for days on the list, with early stopping on the validation period."""
    # Days on the list is a count, so a Poisson objective fits its shape better than squared error.
    model = lgb.LGBMRegressor(objective="poisson", **SHARED_LIGHTGBM_PARAMS)
    model.fit(
        train_matrix, train_target,
        eval_X=validation_matrix, eval_y=validation_target, eval_metric="l1",
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    return model


def use_project_mlflow():
    """Point MLflow at the project's own database and artifact folder."""
    mlflow.set_tracking_uri(f"sqlite:///{MLFLOW_DATABASE.as_posix()}")
    if mlflow.get_experiment_by_name(EXPERIMENT_NAME) is None:
        mlflow.create_experiment(EXPERIMENT_NAME, artifact_location=MLFLOW_ARTIFACTS.as_uri())
    mlflow.set_experiment(EXPERIMENT_NAME)


def evaluate_all(features):
    """Train both LightGBM models, score them and the baselines on validation and test, and log to MLflow."""
    splits = {name: rows for name, rows in features.groupby("split")}
    train_rows = splits["train"]
    categories = training_categories(train_rows)
    matrices = {name: feature_matrix(rows, categories) for name, rows in splits.items()}

    classifier = fit_classifier(matrices["train"], train_rows["long_runner"],
                                matrices["validation"], splits["validation"]["long_runner"])
    regressor = fit_regressor(matrices["train"], train_rows["days_trending"],
                              matrices["validation"], splits["validation"]["days_trending"])

    result_rows = []
    for split_name in ["validation", "test"]:
        rows = splits[split_name]
        baseline_long_run, baseline_days = baseline_scores(train_rows, rows)
        scored = {
            ("classifier", "baseline"): classifier_metrics(rows["long_runner"], baseline_long_run),
            ("classifier", "lightgbm"): classifier_metrics(
                rows["long_runner"], classifier.predict_proba(matrices[split_name])[:, 1]),
            ("regressor", "baseline"): regressor_metrics(rows["days_trending"], baseline_days),
            ("regressor", "lightgbm"): regressor_metrics(rows["days_trending"], regressor.predict(matrices[split_name])),
        }
        for (task, model_name), metrics in scored.items():
            result_rows.append({"task": task, "model": model_name, "split": split_name, **metrics})
    results = pd.DataFrame(result_rows)

    use_project_mlflow()
    for (task, model_name), task_results in results.groupby(["task", "model"]):
        with mlflow.start_run(run_name=f"{model_name} {task}"):
            mlflow.log_params({"task": task, "model": model_name, "features": len(FEATURE_COLUMNS),
                               "train_rows": len(train_rows)})
            if model_name == "lightgbm":
                fitted = classifier if task == "classifier" else regressor
                mlflow.log_params({**SHARED_LIGHTGBM_PARAMS, "best_iteration": fitted.best_iteration_})
            for _, row in task_results.iterrows():
                for metric_name, value in row.drop(["task", "model", "split"]).dropna().items():
                    mlflow.log_metric(f"{row['split']}_{metric_name}", float(value))
    return classifier, regressor, categories, results


def save_models(classifier, regressor, categories):
    """Save both boosters and the training categories so other features can score new videos."""
    MODELS_DIR.mkdir(exist_ok=True)
    classifier.booster_.save_model(str(CLASSIFIER_PATH))
    regressor.booster_.save_model(str(REGRESSOR_PATH))
    CATEGORIES_PATH.write_text(json.dumps(categories, indent=2), encoding="utf-8")


if __name__ == "__main__":
    features = pd.read_parquet(FEATURES_PATH)
    classifier, regressor, categories, results = evaluate_all(features)
    save_models(classifier, regressor, categories)
    RESULTS_PATH.parent.mkdir(exist_ok=True)
    results.to_csv(RESULTS_PATH, index=False)
    print(f"best iterations: classifier {classifier.best_iteration_}, regressor {regressor.best_iteration_}")
    print(results.round(3).to_string(index=False))
