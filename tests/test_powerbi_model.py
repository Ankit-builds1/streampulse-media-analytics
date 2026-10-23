from streampulse.powerbi_model import MEASURES_PATH, parse_measures, quote

SAMPLE_DAX = """// Comment lines are skipped.

Trending Runs = COUNTROWS ( fact_trending_runs )

// A VAR line also looks like "Name =", but belongs to the measure above it.
Top 10 Channel Share % =
VAR TopTenChannels =
    TOPN ( 10, VALUES ( fact_channel_slots[channel_id] ), [Channel Slots] )
RETURN
    DIVIDE ( CALCULATE ( [Channel Slots], TopTenChannels ), [Channel Slots] )

Trending Runs (Full Weeks) =
IF ( MIN ( dim_date[week_start] ) < DATE ( 2020, 8, 17 ), BLANK (), [Trending Runs] )
"""


def test_measures_split_on_names_not_on_var_lines():
    measures = dict(parse_measures(SAMPLE_DAX))
    assert list(measures) == ["Trending Runs", "Top 10 Channel Share %", "Trending Runs (Full Weeks)"]
    assert measures["Top 10 Channel Share %"].startswith("VAR TopTenChannels =")
    assert measures["Top 10 Channel Share %"].endswith("[Channel Slots] )")


def test_every_measure_in_the_project_file_has_an_expression():
    measures = parse_measures(MEASURES_PATH.read_text(encoding="utf-8"))
    assert len(measures) == 23
    assert all(expression and "//" not in expression for _, expression in measures)


def test_names_with_spaces_or_symbols_are_quoted_for_tmdl():
    assert quote("Channels") == "Channels"
    assert quote("% Trended By Next Day") == "'% Trended By Next Day'"
