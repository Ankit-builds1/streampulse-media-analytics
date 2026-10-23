import re
import uuid

import pandas as pd

from streampulse.powerbi_export import POWERBI_DATA_DIR, POWERBI_DIR

MODEL_DIR = POWERBI_DIR / "StreamPulse.SemanticModel" / "definition"
MEASURES_PATH = POWERBI_DIR / "measures.dax"
DATA_FOLDER_PARAMETER = "DataFolder"

# Types pandas cannot infer from a CSV, or would infer wrongly (ids that look like numbers).
COLUMN_TYPES = {
    "fact_trending_runs": {
        "run_key": "string", "video_id": "string", "channel_id": "string", "published_at_utc": "dateTime",
        "first_trending_date": "date", "last_trending_date": "date",
    },
    "fact_channel_slots": {"channel_id": "string"},
    "dim_channel": {"channel_id": "string"},
    "dim_date": {"date": "date", "month_start": "date", "week_start": "date"},
    "netflix_titles": {"show_id": "string", "date_added": "date", "seasons": "double", "duration_minutes": "double"},
    "spikes": {"trending_date": "date"},
    "topic_monthly": {"month": "date"},
}
# One-to-many relationships as (many side, one side).
RELATIONSHIPS = [
    ("fact_trending_runs.country", "dim_country.country"),
    ("fact_channel_slots.country", "dim_country.country"),
    ("fact_country_overlap.country", "dim_country.country"),
    ("spikes.country", "dim_country.country"),
    ("topic_monthly.country", "dim_country.country"),
    ("fact_trending_runs.category", "dim_category.category"),
    ("spikes.category", "dim_category.category"),
    ("fact_trending_runs.channel_id", "dim_channel.channel_id"),
    ("fact_channel_slots.channel_id", "dim_channel.channel_id"),
    ("fact_trending_runs.first_trending_date", "dim_date.date"),
    ("spikes.trending_date", "dim_date.date"),
]
SORT_BY = {
    ("dim_date", "month"): "month_start",
    ("dim_date", "weekday"): "weekday_number",
    ("fact_trending_runs", "upload_weekday_name"): "upload_weekday_local",
}
HIDDEN_COLUMNS = {
    "fact_trending_runs": {"run_key", "full_run_known", "completed_run", "upload_weekday_local"},
    "dim_country": {"country_color"},
    "dim_date": {"weekday_number", "month_number"},
}
COLUMN_FORMATS = {
    ("spikes", "new_videos"): "0", ("spikes", "new_videos_raw"): "0", ("spikes", "baseline_median"): "0",
    ("spikes", "robust_z"): "0.0", ("fact_trending_runs", "peak_views"): "#,0",
}
MEASURE_FORMATS = {
    "% Trended By Next Day": "0.0%", "Share Of Country Runs %": "0.0%", "Upload Slot Share %": "0.0%",
    "Top 10 Channel Share %": "0.0%", "IMDb Match Rate %": "0.0%",
    "Median Likes per 1k Views": "0.0", "Average Days On List": "0.0", "Median IMDb Rating": "0.0",
    "Median Comments per 1k Views": "0.00",
}
M_TYPES = {"string": "type text", "int64": "Int64.Type", "double": "type number", "date": "type date",
           "dateTime": "type datetime"}


def lineage_tag(*parts):
    """A stable id, so regenerating the model does not change every line in git."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "streampulse/" + "/".join(parts)))


def quote(name):
    return f"'{name}'" if re.search(r"[^A-Za-z0-9_]", name) else name


def column_types(table_name):
    """TMDL data type of each column in an exported CSV."""
    sample = pd.read_csv(POWERBI_DATA_DIR / f"{table_name}.csv", encoding="utf-8-sig", nrows=5000)
    overrides = COLUMN_TYPES.get(table_name, {})
    types = {}
    for column, dtype in sample.dtypes.items():
        if column in overrides:
            types[column] = overrides[column]
        elif pd.api.types.is_integer_dtype(dtype):
            types[column] = "int64"
        elif pd.api.types.is_float_dtype(dtype):
            types[column] = "double"
        else:
            types[column] = "string"
    return types


def partition_source(table_name, types):
    """Power Query that reads one CSV and sets every column type, with en-US so decimals parse the same anywhere."""
    type_list = ", ".join(f'{{"{column}", {M_TYPES[data_type]}}}' for column, data_type in types.items())
    return [
        "let",
        f'    Source = Csv.Document(File.Contents({DATA_FOLDER_PARAMETER} & "{table_name}.csv"), '
        '[Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        f'    Typed = Table.TransformColumnTypes(Promoted, {{{type_list}}}, "en-US")',
        "in",
        "    Typed",
    ]


def table_tmdl(table_name):
    types = column_types(table_name)
    lines = [f"table {table_name}", f"\tlineageTag: {lineage_tag(table_name)}"]
    if table_name == "dim_date":
        lines.append("\tdataCategory: Time")
    lines.append("")
    for column, data_type in types.items():
        tmdl_type = "dateTime" if data_type in ("date", "dateTime") else data_type
        lines += [f"\tcolumn {quote(column)}", f"\t\tdataType: {tmdl_type}"]
        if data_type == "date":
            lines.append("\t\tformatString: dd mmm yyyy")
        elif (table_name, column) in COLUMN_FORMATS:
            lines.append(f"\t\tformatString: {COLUMN_FORMATS[(table_name, column)]}")
        if table_name == "dim_date" and column == "date":
            lines.append("\t\tisKey")
        if column in HIDDEN_COLUMNS.get(table_name, set()):
            lines.append("\t\tisHidden")
        if (table_name, column) in SORT_BY:
            lines.append(f"\t\tsortByColumn: {SORT_BY[(table_name, column)]}")
        lines += [f"\t\tlineageTag: {lineage_tag(table_name, column)}", "\t\tsummarizeBy: none",
                  f"\t\tsourceColumn: {column}", ""]
    lines += [f"\tpartition {table_name} = m", "\t\tmode: import", "\t\tsource ="]
    lines += [f"\t\t\t\t{line}" for line in partition_source(table_name, types)]
    return "\n".join(lines) + "\n"


def parse_measures(dax_text):
    """(name, expression) pairs from measures.dax, where each measure starts with 'Name =' at the line start."""
    measures, name, body = [], None, []
    for line in dax_text.splitlines():
        if line.startswith("//") or (not line.strip() and name is None):
            continue
        # VAR lines also look like "Name =", but they belong to the measure above.
        start = re.match(r"^(?!VAR\b)([A-Za-z0-9%][A-Za-z0-9 %()]*?) =\s*(.*)$", line)
        if start and not line.startswith((" ", "\t")):
            if name:
                measures.append((name, "\n".join(body).strip()))
            name, body = start.group(1), [start.group(2)] if start.group(2) else []
        elif name is not None:
            body.append(line)
    if name:
        measures.append((name, "\n".join(body).strip()))
    return [(name, re.sub(r"\n\s*//.*$", "", expression, flags=re.MULTILINE).strip()) for name, expression in measures]


def measures_tmdl():
    lines = ["table _Measures", f"\tlineageTag: {lineage_tag('_Measures')}", ""]
    for name, expression in parse_measures(MEASURES_PATH.read_text(encoding="utf-8")):
        expression_lines = [line for line in expression.splitlines() if line.strip()]
        lines.append(f"\tmeasure {quote(name)} =")
        lines += [f"\t\t\t{line}" for line in expression_lines]
        lines += [f"\t\tformatString: {MEASURE_FORMATS.get(name, '#,0')}",
                  f"\t\tlineageTag: {lineage_tag('_Measures', name)}", ""]
    # A table needs a column; this hidden one makes Power BI show _Measures as a measure table.
    lines += ["\tcolumn Placeholder", "\t\tdataType: string", "\t\tisHidden",
              f"\t\tlineageTag: {lineage_tag('_Measures', 'Placeholder')}", "\t\tsummarizeBy: none",
              "\t\tsourceColumn: Placeholder", "",
              "\tpartition _Measures = m", "\t\tmode: import", "\t\tsource =",
              "\t\t\t\tlet", "\t\t\t\t    Source = #table(type table [Placeholder = text], {})", "\t\t\t\tin",
              "\t\t\t\t    Source"]
    return "\n".join(lines) + "\n"


def relationships_tmdl():
    lines = []
    for many_side, one_side in RELATIONSHIPS:
        lines += [f"relationship {lineage_tag('relationship', many_side, one_side)}",
                  f"\tfromColumn: {many_side}", f"\ttoColumn: {one_side}", ""]
    return "\n".join(lines)


def expressions_tmdl():
    folder = str(POWERBI_DATA_DIR) + "\\"
    return (f'expression {DATA_FOLDER_PARAMETER} = "{folder}" '
            'meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
            f"\tlineageTag: {lineage_tag('expression', DATA_FOLDER_PARAMETER)}\n\n"
            "\tannotation PBI_ResultType = Text\n")


def write_model():
    """Write the tables, measures, relationships and data folder parameter as TMDL files."""
    table_names = sorted(path.stem for path in POWERBI_DATA_DIR.glob("*.csv"))
    tables_dir = MODEL_DIR / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    for old_file in tables_dir.glob("*.tmdl"):
        old_file.unlink()
    for table_name in table_names:
        (tables_dir / f"{table_name}.tmdl").write_text(table_tmdl(table_name), encoding="utf-8")
    (tables_dir / "_Measures.tmdl").write_text(measures_tmdl(), encoding="utf-8")
    (MODEL_DIR / "relationships.tmdl").write_text(relationships_tmdl(), encoding="utf-8")
    (MODEL_DIR / "expressions.tmdl").write_text(expressions_tmdl(), encoding="utf-8")
    model_path = MODEL_DIR / "model.tmdl"
    model_lines = [line for line in model_path.read_text(encoding="utf-8").splitlines()
                   if not line.startswith("ref table ")]
    model_lines += [f"ref table {quote(name)}" for name in ["_Measures", *table_names]]
    model_path.write_text("\n".join(model_lines) + "\n", encoding="utf-8")
    return table_names


if __name__ == "__main__":
    names = write_model()
    print(f"wrote {len(names)} tables, {len(parse_measures(MEASURES_PATH.read_text(encoding='utf-8')))} measures, "
          f"{len(RELATIONSHIPS)} relationships to {MODEL_DIR}")
