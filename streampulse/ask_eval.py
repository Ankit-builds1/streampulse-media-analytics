import json
import time

import numpy as np
import pandas as pd

from streampulse.ask import ask_data, connect_for_questions, run_read_only
from streampulse.load import PROJECT_ROOT

EVALS_DIR = PROJECT_ROOT / "evals"
QUESTIONS_PATH = EVALS_DIR / "text_to_sql_questions.json"
RESULTS_PATH = EVALS_DIR / "text_to_sql_results.csv"
NOT_ANSWERABLE = "not answerable from this data"


def _as_numbers(values):
    try:
        return pd.to_numeric(pd.Series(values), errors="raise").astype(float).to_numpy()
    except (ValueError, TypeError):
        return None


def _as_text(values):
    # Dates and timestamps compare on the date only, so 2024-04-15 matches 2024-04-15 00:00:00.
    return [str(value).strip().lower()[:10] if hasattr(value, "year") else str(value).strip().lower()
            for value in values]


def columns_match(reference_values, candidate_values, ordered):
    """True if two columns hold the same values, allowing rounding and a share written as a percentage."""
    reference_numbers, candidate_numbers = _as_numbers(reference_values), _as_numbers(candidate_values)
    if reference_numbers is not None and candidate_numbers is not None:
        if not ordered:
            reference_numbers, candidate_numbers = np.sort(reference_numbers), np.sort(candidate_numbers)
        return any(
            np.allclose(reference_numbers, candidate_numbers * scale, rtol=0.005, atol=0.011)
            for scale in (1, 100, 0.01)
        )
    reference_text, candidate_text = _as_text(reference_values), _as_text(candidate_values)
    if not ordered:
        reference_text, candidate_text = sorted(reference_text), sorted(candidate_text)
    return reference_text == candidate_text


def results_match(reference_rows, candidate_rows, ordered):
    """True if the candidate has the same number of rows and every reference column is matched by some candidate column.

    Extra candidate columns, such as a row count or an id, are allowed. Columns are compared one at a time,
    so for unordered results the row pairing across columns is not checked.
    """
    if candidate_rows is None or len(candidate_rows) != len(reference_rows):
        return False
    return all(
        any(columns_match(reference_rows[reference_column], candidate_rows[candidate_column], ordered)
            for candidate_column in candidate_rows.columns)
        for reference_column in reference_rows.columns
    )


def is_refusal(result):
    """True if the system declined: the query was rejected, or it returned the 'not answerable' message."""
    if result["error"] and result["error"].startswith("Rejected"):
        return True
    rows = result["rows"]
    return rows is not None and rows.shape == (1, 1) and str(rows.iat[0, 0]).strip().lower() == NOT_ANSWERABLE


def run_evaluation(runs=3, pause_seconds=1.0):
    """Ask every test question `runs` times and score each answer against its reference query."""
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    rows = []
    with connect_for_questions() as connection:
        for run in range(1, runs + 1):
            for question in questions:
                start = time.time()
                result = ask_data(question["question"], connection)
                seconds = time.time() - start
                if question.get("expected") == "refuse":
                    passed = is_refusal(result)
                else:
                    # Some answers have more than one correct shape, such as "2022-08" or year 2022 and month 8.
                    reference_queries = [question["reference_sql"], *question.get("alternative_reference_sql", [])]
                    passed = result["error"] is None and any(
                        results_match(run_read_only(connection, reference_sql)[0], result["rows"], question["ordered"])
                        for reference_sql in reference_queries
                    )
                rows.append({
                    "run": run,
                    "id": question["id"],
                    "difficulty": question["difficulty"],
                    "question": question["question"],
                    "passed": passed,
                    "attempts": result["attempts"],
                    "seconds": round(seconds, 2),
                    "error": result["error"],
                    "model_sql": result["sql"],
                })
                time.sleep(pause_seconds)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    results = run_evaluation()
    results.to_csv(RESULTS_PATH, index=False)
    per_run = results.groupby("run")["passed"].mean().mul(100)
    print(f"Accuracy per run: {per_run.round(1).to_dict()}  mean {per_run.mean():.1f}%")
    print(results.groupby("difficulty")["passed"].mean().mul(100).round(1).to_string())
    failures = results[~results["passed"]]
    print(f"\n{len(failures)} failed answers out of {len(results)}:")
    print(failures[["run", "id", "question", "error"]].to_string(index=False))
