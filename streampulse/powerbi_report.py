import hashlib
import json
import shutil

from streampulse.powerbi_export import POWERBI_DIR

REPORT_DIR = POWERBI_DIR / "StreamPulse.Report"
DEFINITION_DIR = REPORT_DIR / "definition"
THEME_PATH = POWERBI_DIR / "streampulse_theme.json"
VISUAL_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.14.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
PAGES_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json"
PAGE_WIDTH, PAGE_HEIGHT = 1280, 720
TEXT_COLOR, MUTED_TEXT = "#FAFAFA", "#9BA3AF"
COUNTRY_BAR_COLORS = {"GB": "#1BAF7A", "IN": "#2A78D6", "US": "#EB6834"}
# Headers people read instead of column names.
DISPLAY_NAMES = {
    "country": "Country", "country_name": "Country", "category": "Category", "channel_title": "Channel",
    "upload_weekday_name": "Weekday", "upload_hour_local": "Upload hour", "country_period": "Country and period",
    "also_trending_in": "Also trending in", "days_trending": "Days on the list", "main_country": "Country",
    "year_added": "Year added", "type": "Type", "week_start": "Week", "month_start": "Month",
    "trending_date": "Date", "new_videos": "New videos", "robust_z": "Robust z", "explanation": "AI note",
    "top_titles": "Top titles", "date": "Date",
}


def object_id(*parts):
    """A stable 20-character name, so regenerating keeps the same files."""
    return hashlib.sha1("/".join(parts).encode()).hexdigest()[:20]


def literal(value):
    return {"expr": {"Literal": {"Value": value}}}


def column(table, name):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def measure(name):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": name}}


def projection(field):
    kind = "Column" if "Column" in field else "Measure"
    entity = field[kind]["Expression"]["SourceRef"]["Entity"]
    prop = field[kind]["Property"]
    shown = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if kind == "Column" and prop in DISPLAY_NAMES:
        shown["displayName"] = DISPLAY_NAMES[prop]
    return shown


def title(text):
    # The automatic subtitle only repeats the field names ("Trending Runs by country and country").
    return {"title": [{"properties": {"show": literal("true"), "text": literal(f"'{text}'")}}],
            "subTitle": [{"properties": {"show": literal("false")}}]}


def visual(page, key, visual_type, position, roles=None, title_text=None, objects=None, sort=None,
           categorical_axis=False):
    """One visual container. roles maps a data role (Category, Y, Values...) to a list of fields."""
    x, y, width, height = position
    body = {"visualType": visual_type, "drillFilterOtherVisuals": True}
    if roles:
        body["query"] = {"queryState": {role: {"projections": [projection(field) for field in fields]}
                                        for role, fields in roles.items()}}
        if sort:
            field, direction = sort
            body["query"]["sortDefinition"] = {"sort": [{"field": field, "direction": direction}]}
    objects = dict(objects or {})
    if visual_type == "tableEx":
        objects["total"] = [{"properties": {"totals": literal("false")}}]
    if categorical_axis:
        objects["categoryAxis"] = [{"properties": {"axisType": literal("'Categorical'")}}]
    if objects:
        body["objects"] = objects
    container = {"$schema": VISUAL_SCHEMA, "name": object_id(page, key),
                 "position": {"x": x, "y": y, "z": 0, "height": height, "width": width, "tabOrder": 0},
                 "visual": body}
    if title_text:
        body["visualContainerObjects"] = title(title_text)
    return container


def text_box(page, key, position, paragraphs):
    """A text box. paragraphs is a list of (text, size_pt, bold, colour)."""
    runs = [{"textRuns": [{"value": text, "textStyle": {"fontSize": f"{size}pt", "color": colour,
                                                        **({"fontWeight": "bold"} if bold else {})}}]}
            for text, size, bold, colour in paragraphs]
    container = visual(page, key, "textbox", position,
                       objects={"general": [{"properties": {"paragraphs": runs}}]})
    container["visual"]["visualContainerObjects"] = {"background": [{"properties": {"show": literal("false")}}],
                                                     "border": [{"properties": {"show": literal("false")}}]}
    return container


def header(page, title_text, subtitle):
    return text_box(page, "header", (20, 8, 1240, 64),
                    [(title_text, 20, True, TEXT_COLOR), (subtitle, 11, False, MUTED_TEXT)])


def slicer(page, key, position, field, header_text, mode="Dropdown"):
    # The slicer's own header labels it, which leaves more room for the box than a separate visual title.
    return visual(page, key, "slicer", position, {"Values": [field]},
                  objects={"data": [{"properties": {"mode": literal(f"'{mode}'")}}],
                           "header": [{"properties": {"show": literal("true"), "text": literal(f"'{header_text}'")}}]})


def card(page, key, position, measure_name):
    # Display units of 1 show 14,953 rather than 15K.
    return visual(page, key, "card", position, {"Values": [measure(measure_name)]},
                  objects={"labels": [{"properties": {"labelDisplayUnits": literal("1D")}}]})


def country_bars(page, key, visual_type, position, measure_name, title_text):
    """One thick bar per country in its app colour, instead of a legend series that makes thin clustered bars."""
    colours = [{"properties": {"fill": {"solid": {"color": literal(f"'{colour}'")}}},
                "selector": {"data": [{"scopeId": {"Comparison": {
                    "ComparisonKind": 0, "Left": column("dim_country", "country"),
                    "Right": {"Literal": {"Value": f"'{code}'"}}}}}]}}
               for code, colour in COUNTRY_BAR_COLORS.items()]
    return visual(page, key, visual_type, position,
                  {"Category": [column("dim_country", "country")], "Y": [measure(measure_name)]}, title_text,
                  objects={"dataPoint": colours})


def gradient_matrix(page, key, position, rows, columns, measure_name, title_text):
    """A matrix whose cells are shaded from the page colour to blue by the measure's value."""
    shading = {"solid": {"color": {"expr": {"FillRule": {
        "Input": measure(measure_name),
        "FillRule": {"linearGradient2": {
            "min": {"color": {"Literal": {"Value": "'#161B22'"}}},
            "max": {"color": {"Literal": {"Value": "'#2A78D6'"}}},
            "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'asZero'"}}},
        }},
    }}}}}
    objects = {
        "values": [{"properties": {"backColor": shading},
                    "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                 "metadata": f"_Measures.{measure_name}"}}],
        "subTotals": [{"properties": {"rowSubtotals": literal("false"), "columnSubtotals": literal("false")}}],
    }
    return visual(page, key, "pivotTable", position,
                  {"Rows": [rows], "Columns": [columns], "Values": [measure(measure_name)]}, title_text, objects)


def country_slicers(page, with_dates=True):
    visuals = [slicer(page, "country", (20, 78, 230, 70), column("dim_country", "country_name"), "Country"),
               slicer(page, "category", (260, 78, 230, 70), column("dim_category", "category"), "Category")]
    if with_dates:
        visuals.append(slicer(page, "dates", (500, 78, 420, 70), column("dim_date", "date"),
                              "First trending date", mode="Between"))
    return visuals


COUNTRY = column("dim_country", "country")
CATEGORY = column("dim_category", "category")


def overview_page():
    page = "overview"
    return "Overview", [
        header(page, "StreamPulse: what trends, where, and how fast",
               "YouTube trending lists in India, the US and the UK, 12 Aug 2020 to 15 Apr 2024"),
        *country_slicers(page),
        card(page, "runs", (20, 152, 300, 110), "Trending Runs"),
        card(page, "channels", (333, 152, 300, 110), "Channels"),
        card(page, "next_day", (646, 152, 300, 110), "% Trended By Next Day"),
        card(page, "median_days", (959, 152, 300, 110), "Median Days On List"),
        country_bars(page, "runs_by_country", "clusteredColumnChart", (20, 275, 400, 430), "Trending Runs",
                     "Trending videos by country"),
        visual(page, "weekly", "lineChart", (435, 275, 825, 430),
               {"Category": [column("dim_date", "week_start")], "Y": [measure("Trending Runs (Full Weeks)")],
                "Series": [COUNTRY]},
               "New trending videos per week (full weeks only)"),
    ]


def speed_page():
    page = "speed"
    return "Speed and staying power", [
        header(page, "Speed and staying power",
               "India's videos reach the list fastest and leave it fastest; the gap holds in every category"),
        *country_slicers(page),
        country_bars(page, "next_day", "clusteredBarChart", (20, 152, 400, 240), "% Trended By Next Day",
                     "Share trending by the day after upload"),
        gradient_matrix(page, "next_day_matrix", (20, 402, 400, 305), CATEGORY, COUNTRY,
                        "% Trended By Next Day", "Trending by next day: category by country"),
        visual(page, "days_by_category", "clusteredColumnChart", (435, 152, 825, 270),
               {"Category": [CATEGORY], "Y": [measure("Average Days On List")], "Series": [COUNTRY]},
               "Average days on the list by category"),
        visual(page, "days_distribution", "clusteredColumnChart", (435, 432, 825, 275),
               {"Category": [column("fact_trending_runs", "days_trending")], "Y": [measure("Runs Up To 20 Days")],
                "Series": [COUNTRY]},
               "How many days videos stay (up to 20)", categorical_axis=True),
    ]


def engagement_page():
    page = "engagement"
    period = column("fact_trending_runs", "country_period")
    return "Engagement", [
        header(page, "Engagement on the first trending day",
               "Category drives likes; country drives comments"),
        *country_slicers(page),
        visual(page, "likes_by_category", "clusteredBarChart", (20, 152, 620, 555),
               {"Category": [CATEGORY], "Y": [measure("Median Likes per 1k Views")], "Series": [COUNTRY]},
               "Median likes per 1,000 views by category",
               sort=(measure("Median Likes per 1k Views"), "Descending")),
        visual(page, "comments_by_period", "clusteredBarChart", (655, 152, 605, 215),
               {"Category": [period], "Y": [measure("Median Comments per 1k Views")]},
               "Median comments per 1,000 views"),
        visual(page, "engagement_table", "tableEx", (655, 377, 605, 195),
               {"Values": [period, measure("Median Likes per 1k Views"), measure("Median Comments per 1k Views")]},
               "First-day engagement by country and period"),
        text_box(page, "shorts_note", (655, 582, 605, 125), [
            ("Why India is split in two", 12, True, TEXT_COLOR),
            ("On 6 Oct 2022 YouTube Shorts left India's trending list: 79 of 200 videos the day before, none after. "
             "Shorts get more likes per view, so Indian engagement is compared within one side of that date.",
             10, False, MUTED_TEXT),
        ]),
    ]


def publish_time_page():
    page = "publish_time"
    runs = "fact_trending_runs"
    return "Publish time", [
        header(page, "When trending videos were uploaded",
               "Local time in each country. Pick one country: mixing time zones hides the pattern"),
        *country_slicers(page),
        gradient_matrix(page, "slots", (20, 152, 1240, 330), column(runs, "upload_weekday_name"),
                        column(runs, "upload_hour_local"), "Upload Slot Share %",
                        "Share of trending videos by upload weekday and hour"),
        visual(page, "peak_by_hour", "clusteredColumnChart", (20, 492, 820, 215),
               {"Category": [column(runs, "upload_hour_local")], "Y": [measure("Median Peak Views")],
                "Series": [COUNTRY]},
               "Median peak views by upload hour (raw, before controls)", categorical_axis=True),
        text_box(page, "caveat", (855, 492, 405, 215), [
            ("No universal best time", 12, True, TEXT_COLOR),
            ("The channel explains over 200 times as much of a video's views as its upload hour. After controlling "
             "for channel and category, hour effects stay between -11% and +14%.", 10, False, MUTED_TEXT),
        ]),
    ]


def markets_page():
    page = "markets"
    return "Markets and creators", [
        header(page, "One audience or three, and who holds the list",
               "The US and UK behave like one market; India is separate"),
        *country_slicers(page, with_dates=False),
        visual(page, "category_mix", "hundredPercentStackedBarChart", (20, 152, 620, 290),
               {"Category": [column("dim_country", "country_name")], "Y": [measure("Trending Runs")],
                "Series": [CATEGORY]},
               "Category mix of each country's trending videos"),
        visual(page, "overlap", "pivotTable", (655, 152, 605, 185),
               {"Rows": [column("fact_country_overlap", "country")],
                "Columns": [column("fact_country_overlap", "also_trending_in")],
                "Values": [measure("Shared Videos")]},
               "Videos that trended in both countries",
               objects={"subTotals": [{"properties": {"rowSubtotals": literal("false"),
                                                      "columnSubtotals": literal("false")}}]}),
        country_bars(page, "top_ten_share", "clusteredColumnChart", (655, 347, 605, 180),
                     "Top 10 Channel Share %", "Share of list slots held by the top 10 channels"),
        visual(page, "top_channels", "tableEx", (20, 452, 620, 255),
               {"Values": [column("dim_channel", "channel_title"), measure("Channel Slots")]},
               "Channels with the most list slots", sort=(measure("Channel Slots"), "Descending")),
        text_box(page, "markets_note", (655, 532, 605, 175), [
            ("What it means", 12, True, TEXT_COLOR),
            ("The US and UK share 24,447 trending videos (52% of each list); India shares about 2%. "
             "One content plan can serve the US and UK, India needs its own. 7% to 9% of trending channels hold "
             "half of all list slots in every country.", 10, False, MUTED_TEXT),
        ]),
    ]


def netflix_page():
    page = "netflix"
    netflix = "netflix_titles"
    return "Netflix catalog", [
        header(page, "Netflix catalog growth and IMDb ratings",
               "Titles added 2015 to Sep 2021 (2021 is a partial year); ratings for titles with 1,000+ IMDb votes"),
        card(page, "titles", (20, 80, 400, 100), "Netflix Titles"),
        card(page, "match_rate", (440, 80, 400, 100), "IMDb Match Rate %"),
        card(page, "median_rating", (860, 80, 400, 100), "Median IMDb Rating"),
        visual(page, "added_by_year", "columnChart", (20, 192, 620, 265),
               {"Category": [column(netflix, "year_added")], "Y": [measure("Netflix Titles 2015 On")],
                "Series": [column(netflix, "type")]},
               "Titles added per year"),
        visual(page, "rating_by_year", "lineChart", (655, 192, 605, 265),
               {"Category": [column(netflix, "year_added")], "Y": [measure("Median IMDb Rating 2015 On")],
                "Series": [column(netflix, "type")]},
               "Median IMDb rating of titles added each year"),
        visual(page, "top_countries", "clusteredColumnChart", (20, 467, 1240, 240),
               {"Category": [column(netflix, "main_country")], "Y": [measure("Netflix Titles Top 10 Countries")]},
               "Top 10 production countries", sort=(measure("Netflix Titles Top 10 Countries"), "Descending")),
    ]


def spikes_page():
    page = "spikes"
    spikes = "spikes"
    return "Spikes", [
        header(page, "Unusual spikes in new trending videos",
               "Days when a category got far more new trending videos than in the previous 28 days, with an AI note"),
        card(page, "spikes", (20, 80, 250, 100), "Spikes Flagged"),
        slicer(page, "country", (290, 80, 260, 100), column("dim_country", "country_name"), "Country"),
        slicer(page, "category", (570, 80, 260, 100), CATEGORY, "Category"),
        visual(page, "spikes_by_month", "columnChart", (20, 192, 1240, 210),
               {"Category": [column("dim_date", "month_start")], "Y": [measure("Spikes Flagged")],
                "Series": [COUNTRY]},
               "Spikes per month"),
        visual(page, "spike_table", "tableEx", (20, 412, 1240, 295),
               {"Values": [column(spikes, "trending_date"), column(spikes, "country"), column(spikes, "category"),
                           column(spikes, "new_videos"), column(spikes, "robust_z"), column(spikes, "explanation"),
                           column(spikes, "top_titles")]},
               "Spikes with the AI note and the titles behind it", sort=(column(spikes, "robust_z"), "Descending")),
    ]


PAGES = [overview_page, speed_page, engagement_page, publish_time_page, markets_page, netflix_page, spikes_page]


def register_theme():
    """Copy the theme into the report and point report.json at it as the custom theme."""
    resources_dir = REPORT_DIR / "StaticResources" / "RegisteredResources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(THEME_PATH, resources_dir / THEME_PATH.name)
    report_path = DEFINITION_DIR / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    base_versions = report["themeCollection"]["baseTheme"]["reportVersionAtImport"]
    report["themeCollection"]["customTheme"] = {"name": THEME_PATH.name, "reportVersionAtImport": base_versions,
                                                "type": "RegisteredResources"}
    packages = [package for package in report["resourcePackages"] if package["name"] != "RegisteredResources"]
    packages.append({"name": "RegisteredResources", "type": "RegisteredResources",
                     "items": [{"name": THEME_PATH.name, "path": THEME_PATH.name, "type": "CustomTheme"}]})
    report["resourcePackages"] = packages
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def write_report():
    """Replace every report page with the generated ones."""
    pages_dir = DEFINITION_DIR / "pages"
    shutil.rmtree(pages_dir, ignore_errors=True)
    page_names = []
    for build_page in PAGES:
        display_name, visuals = build_page()
        page_name = object_id("page", build_page.__name__)
        page_dir = pages_dir / page_name
        (page_dir / "visuals").mkdir(parents=True)
        page = {"$schema": PAGE_SCHEMA, "name": page_name, "displayName": display_name,
                "displayOption": "FitToPage", "height": PAGE_HEIGHT, "width": PAGE_WIDTH}
        (page_dir / "page.json").write_text(json.dumps(page, indent=2), encoding="utf-8")
        for container in visuals:
            visual_dir = page_dir / "visuals" / container["name"]
            visual_dir.mkdir()
            (visual_dir / "visual.json").write_text(json.dumps(container, indent=2, ensure_ascii=False),
                                                    encoding="utf-8")
        page_names.append(page_name)
    pages_meta = {"$schema": PAGES_SCHEMA, "pageOrder": page_names, "activePageName": page_names[0]}
    (pages_dir / "pages.json").write_text(json.dumps(pages_meta, indent=2), encoding="utf-8")
    register_theme()
    return page_names


if __name__ == "__main__":
    names = write_report()
    print(f"wrote {len(names)} pages to {DEFINITION_DIR / 'pages'}")
