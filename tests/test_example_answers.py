import pandas as pd

from streampulse.ask import choose_chart
from streampulse.example_answers import EXAMPLE_QUESTIONS, load_example_answers


def test_every_example_question_has_a_saved_answer():
    answers, generated_on = load_example_answers()
    assert set(EXAMPLE_QUESTIONS) <= set(answers) and generated_on


def test_saved_answers_are_complete_and_passed_the_number_check():
    answers, _ = load_example_answers()
    for question in EXAMPLE_QUESTIONS:
        answer = answers[question]
        assert answer["error"] is None and answer["answer"] and answer["sql"].lower().lstrip().startswith(("select", "with"))
        assert isinstance(answer["rows"], pd.DataFrame) and not answer["rows"].empty
        assert answer["unsupported_numbers"] == []


def test_saved_rows_keep_numeric_types_so_charts_still_work():
    answers, _ = load_example_answers()
    rows = answers["What is the median number of days a video stays trending in each country?"]["rows"]
    assert rows.select_dtypes(include="number").shape[1] >= 1
    assert choose_chart(rows) is not None
