import datetime
import json
from io import StringIO

import pandas as pd

from streampulse.app_data import APP_DATA_DIR, connect_app_database

EXAMPLE_ANSWERS_PATH = APP_DATA_DIR / "example_answers.json"
# The app offers these as one-click examples. Their answers are saved so the examples keep working, and cost no
# tokens, when the shared free Groq quota is used up.
EXAMPLE_QUESTIONS = [
    "Which 5 channels spent the most days on the UK trending list?",
    "What is the median number of days a video stays trending in each country?",
    "How many Netflix titles were added each year?",
    "Which categories get the most likes per 1,000 views in India?",
]
SAVED_FIELDS = ["sql", "answer", "unsupported_numbers", "truncated", "attempts"]


def build_example_answers(questions=EXAMPLE_QUESTIONS):
    """Answer each example question live and save the results. Fails loudly rather than saving a failed answer."""
    from streampulse.ask import answer_question

    saved = {"generated_on": datetime.date.today().isoformat(), "answers": {}}
    with connect_app_database() as connection:
        for question in questions:
            result = answer_question(question, connection.cursor())
            if result["error"]:
                raise RuntimeError(f"Could not answer {question!r}: {result['error']}")
            saved["answers"][question] = {
                **{field: result[field] for field in SAVED_FIELDS},
                # orient="table" stores column types, so dates come back as dates and the chart picks the same kind.
                "rows": result["rows"].to_json(orient="table", index=False),
            }
    EXAMPLE_ANSWERS_PATH.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return saved


def load_example_answers():
    """Saved example answers keyed by question, each with its rows as a DataFrame, plus the date they were made."""
    if not EXAMPLE_ANSWERS_PATH.exists():
        return {}, None
    saved = json.loads(EXAMPLE_ANSWERS_PATH.read_text(encoding="utf-8"))
    answers = {
        question: {**answer, "rows": pd.read_json(StringIO(answer["rows"]), orient="table"), "error": None}
        for question, answer in saved["answers"].items()
    }
    return answers, saved["generated_on"]


if __name__ == "__main__":
    saved = build_example_answers()
    for question, answer in saved["answers"].items():
        print(f"{question}\n  {answer['answer'][:150]}\n  unsupported numbers: {answer['unsupported_numbers']}")
