import json
import re

import pandas as pd
from groq import RateLimitError

from streampulse.ask import NUMBER_PATTERN, connect_for_questions, run_read_only, unsupported_numbers
from streampulse.llm import complete
from streampulse.load import PROJECT_ROOT

REPORT_PATH = PROJECT_ROOT / "reports" / "insight_report.md"
CITATION_PATTERN = re.compile(r"\[(F\d+)\]")

# Every number the report may use comes from one of these queries. Percentages and rounding are done here in
# SQL, so the model only has to copy numbers, never calculate them.
FACT_QUERIES = {
    "F1": ("Data coverage per country: first and last trending day, unique videos and channels", """
        SELECT country, min(first_trending_date) AS first_day, max(last_trending_date) AS last_day,
               count(*) AS unique_videos, count(DISTINCT channel_id) AS channels
        FROM trending_videos GROUP BY country ORDER BY country"""),
    "F2": ("Median days a video stays on the trending list, per country", """
        SELECT country, median(days_trending) AS median_days_on_list
        FROM trending_videos GROUP BY country ORDER BY country"""),
    "F3": ("Among videos that trended (not all uploads), the percent that first reached the list within one day of "
           "upload, per country", """
        SELECT country,
               round(100 * avg(CAST(date_diff('day', CAST(published_at AS DATE), first_trending_date) <= 1 AS INTEGER)), 1)
                   AS pct_trending_by_next_day
        FROM trending_videos WHERE first_trending_date > DATE '2020-08-12' GROUP BY country ORDER BY country"""),
    "F4": ("Top 3 categories by percent of each country's trending videos", """
        SELECT country, category, round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY country), 1) AS pct_of_videos
        FROM trending_videos GROUP BY country, category
        QUALIFY row_number() OVER (PARTITION BY country ORDER BY count(*) DESC) <= 3
        ORDER BY country, pct_of_videos DESC"""),
    "F5": ("Median likes per 1,000 views on the first trending day: the 3 highest and 3 lowest categories with at least 500 videos", """
        WITH first_day AS (
            SELECT category, view_count, trending_date, 1000.0 * likes / view_count AS likes_per_1k_views
            FROM trending
            QUALIFY row_number() OVER (PARTITION BY country, video_id ORDER BY trending_date) = 1),
        ranked AS (
            SELECT category, round(median(likes_per_1k_views), 1) AS median_likes_per_1k_views, count(*) AS videos
            FROM first_day WHERE view_count > 0 AND trending_date > DATE '2020-08-12'
            GROUP BY category HAVING count(*) >= 500)
        (SELECT * FROM ranked ORDER BY median_likes_per_1k_views DESC LIMIT 3)
        UNION ALL
        (SELECT * FROM ranked ORDER BY median_likes_per_1k_views ASC LIMIT 3)"""),
    "F6": ("For each country: what percent of its own trending videos also trended in another country. "
           "Read each row as: pct_of_these_videos percent of base_country's trending videos also trended in "
           "also_trending_in", """
        WITH pairs AS (
            SELECT a.country AS base_country, b.country AS also_trending_in, count(*) AS shared_videos
            FROM trending_videos AS a JOIN trending_videos AS b ON a.video_id = b.video_id AND a.country <> b.country
            GROUP BY ALL)
        SELECT base_country, totals.videos AS base_country_videos, also_trending_in, shared_videos,
               round(100.0 * shared_videos / totals.videos, 1) AS pct_of_these_videos
        FROM pairs JOIN (SELECT country AS base_country, count(*) AS videos FROM trending_videos GROUP BY country) AS totals
             USING (base_country)
        ORDER BY base_country, also_trending_in"""),
    "F7": ("Percent of all trending-list slots held by the top 1 percent of channels, per country", """
        WITH channel_slots AS (SELECT country, channel_id, count(*) AS slots FROM trending GROUP BY ALL),
        ranked AS (SELECT *, row_number() OVER (PARTITION BY country ORDER BY slots DESC) AS channel_rank,
                          count(*) OVER (PARTITION BY country) AS channels FROM channel_slots)
        SELECT country, round(100.0 * sum(slots) FILTER (WHERE channel_rank <= 0.01 * channels) / sum(slots), 1)
                   AS pct_slots_top_1pct_channels
        FROM ranked GROUP BY country ORDER BY country"""),
    "F8": ("Mean (average, not median) number of new videos entering the trending list per day, per country", """
        SELECT country, round(count(*) / count(DISTINCT first_trending_date), 1) AS new_videos_per_day
        FROM trending_videos WHERE first_trending_date > DATE '2020-08-12' GROUP BY country ORDER BY country"""),
    "F9": ("Netflix titles added per year, 2016 to 2021. 2021 only covers 1 January to 25 September, so it must not "
           "be compared with full years as a rise or fall", """
        SELECT year(date_added) AS year_added, count(*) AS titles_added
        FROM netflix_titles WHERE year(date_added) BETWEEN 2016 AND 2021 GROUP BY year_added ORDER BY year_added"""),
    "F10": ("Median IMDb rating of Netflix titles with at least 1,000 IMDb votes, by type", """
        SELECT type, round(median(imdb_rating), 1) AS median_imdb_rating, count(*) AS titles
        FROM netflix_titles WHERE imdb_votes >= 1000 GROUP BY type ORDER BY type"""),
}

REPORT_PROMPT = """You write a one-page business summary of a YouTube trending and Netflix catalog analysis for a
media company's content team. Use only the facts given. Every sentence that contains a number must end with the
fact ID in brackets, such as [F2]. Copy numbers exactly as they appear in the facts or round them; never
calculate new numbers such as differences, ratios or totals. Do not guess causes.

Write a summary, not a list of every number: pick the 3 or 4 most important patterns, use at most 15 numbers in
the whole report, and compare countries within one sentence instead of one sentence per country. Keep each
number's exact meaning from its fact description; for example "by the day after upload" means within one day,
not on the next day. Takeaways must follow directly from the facts and cite them; describe what a pattern
suggests a team should look at, and never claim that doing something will cause a result.

Structure, in Markdown:
# StreamPulse insight report
One opening sentence giving the first and last trending dates from F1.
## What trends
## How long it lasts
## How markets differ
## Netflix catalog
## What this means for content teams
(2 to 3 bullet points of practical takeaways, still citing facts for any number)

Keep it under 350 words. Plain, direct language; no hype words."""


def gather_facts(connection):
    """Run every fact query. Returns {fact_id: (description, rows)}."""
    return {fact_id: (description, run_read_only(connection, sql)[0])
            for fact_id, (description, sql) in FACT_QUERIES.items()}


def facts_as_text(facts):
    return "\n\n".join(f"[{fact_id}] {description}\n{rows.to_csv(index=False)}"
                       for fact_id, (description, rows) in facts.items())


def normalize_report(report):
    """Make citations and numbers checkable: some replies cite as 【F1】 and write 2,015 as "2 015" with a thin space."""
    report = report.replace("【", "[").replace("】", "]")
    return re.sub(r"(?<=\d)[    ](?=\d{3}\b)", "", report)


def verify_report(report, facts):
    """Problems found in a report: numbers that are in no fact, and citations to facts that do not exist."""
    all_fact_rows = pd.concat([rows for _, rows in facts.values()], ignore_index=True)
    # Numbers in the fact descriptions, such as "top 3" or "at least 1,000 votes", may be repeated too.
    descriptions = " ".join(description for description, _ in facts.values())
    # Strip citations first so the "2" in [F2] is not checked as a number.
    report_without_citations = CITATION_PATTERN.sub("", report)
    problems = [f"number not in any fact: {number}"
                for number in unsupported_numbers(report_without_citations, all_fact_rows, descriptions)]
    problems += [f"cites a fact that does not exist: [{fact_id}]"
                 for fact_id in sorted(set(CITATION_PATTERN.findall(report)) - set(facts))]
    return problems


AUDIT_PROMPT = """You check a report against the facts it cites. For every sentence or bullet, decide whether it
states its cited fact correctly: right numbers, right countries, right direction
(which country's share it is), right unit (videos, slots, titles, days) and no claim the fact does not support.
Also flag any sentence or bullet that states a fact or recommendation without citing a fact ID, and any that
claims one thing causes another. Reply with only a JSON list inside a ```json code block, one item per incorrect sentence, each with "sentence"
(quoted exactly) and "problem" (one short sentence). Reply with an empty list [] if every sentence is correct."""


def audit_sentences(report, facts):
    """A second LLM pass that checks each cited sentence against its facts. Returns problem descriptions."""
    reply = complete(AUDIT_PROMPT, f"Facts:\n{facts_as_text(facts)}\n\nReport:\n{report}")
    json_block = re.search(r"```(?:json)?\s*(.*?)```", reply, re.DOTALL)
    findings = json.loads(json_block.group(1) if json_block else reply)
    return [f"misstated: \"{item['sentence']}\" ({item['problem']})" for item in findings]


def write_report(facts, previous_attempt=None):
    """Ask the LLM for the report. On a retry, include the earlier draft and its problems."""
    user_prompt = facts_as_text(facts)
    if previous_attempt:
        draft, problems = previous_attempt
        user_prompt += ("\n\nYour previous draft had these problems:\n- " + "\n- ".join(problems)
                        + f"\n\nPrevious draft:\n{draft}\n\nWrite a corrected report.")
    return complete(REPORT_PROMPT, user_prompt).strip()


def build_report(connection=None, max_attempts=3):
    """Write and verify the report. Returns the report text, the problems found in each attempt and the facts."""
    connection = connection or connect_for_questions()
    facts = gather_facts(connection)
    problems_by_attempt = []
    previous_attempt = None
    for _ in range(max_attempts):
        report = normalize_report(write_report(facts, previous_attempt))
        # An empty reply has no numbers to fail the checks, so it has to be caught on its own.
        if len(report.split()) < 50:
            problems = ["the report is empty or too short"]
        else:
            # The number check is exact but only sees numbers; the audit catches wrong meanings, such as a share
            # attributed to the wrong country, but is itself an LLM and can be wrong, so its findings are reported.
            problems = verify_report(report, facts) or audit_sentences(report, facts)
        problems_by_attempt.append(problems)
        if not problems:
            break
        previous_attempt = (report, problems)
    return report, problems_by_attempt, facts


if __name__ == "__main__":
    try:
        report, problems_by_attempt, facts = build_report()
    except RateLimitError as error:
        wait = re.search(r"try again in ((?:\d+h)?(?:\d+m)?\d+)(?:\.\d+)?s", str(error))
        raise SystemExit(
            "Groq's free token limit for this model is used up, so the report was not written and the old one is "
            f"unchanged. Try again in {wait.group(1) + 's' if wait else 'a while'}."
        )
    remaining_problems = problems_by_attempt[-1]
    numbers_checked = len(NUMBER_PATTERN.findall(CITATION_PATTERN.sub("", report)))
    footer = (f"\n\n---\nGenerated by `python -m streampulse.insight_report`. Every number above was checked "
              f"against {len(facts)} SQL fact queries in `streampulse/insight_report.py` ({numbers_checked} numbers), "
              f"and every cited sentence was checked against its fact by a second LLM pass. "
              f"{len(problems_by_attempt)} attempt(s); {len(remaining_problems)} problem(s) remaining.\n")
    for attempt, problems in enumerate(problems_by_attempt[:-1], start=1):
        footer += f"Attempt {attempt} was rejected: {'; '.join(problems)}\n"
    if remaining_problems:
        footer += "Unverified: " + "; ".join(remaining_problems) + "\n"
    REPORT_PATH.write_text(report + footer, encoding="utf-8")
    print(report + footer)
