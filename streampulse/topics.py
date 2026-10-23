import json
import re

import numpy as np
import pandas as pd

from streampulse.database import connect
from streampulse.llm import complete
from streampulse.load import PROJECT_ROOT

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
EMBEDDINGS_PATH = PROCESSED_DIR / "title_embeddings.npy"
EMBEDDED_VIDEOS_PATH = PROCESSED_DIR / "title_embeddings_videos.parquet"
VIDEO_TOPICS_PATH = PROCESSED_DIR / "video_topics.parquet"
TOPIC_SUMMARY_PATH = PROJECT_ROOT / "reports" / "topics.csv"

# Titles are in English, Hindi, Hinglish, Korean and more, so an English-only model would treat most
# non-English titles as noise. This model covers 50+ languages (not Tamil or Telugu) and runs on a CPU.
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
MIN_TOPIC_SIZE = 300
RANDOM_STATE = 42


def load_video_titles(connection):
    """One row per unique video with its title, category, first trending date and the countries it trended in."""
    return connection.execute("""
        SELECT
            video_id,
            any_value(title) AS title,
            any_value(category) AS category,
            min(first_trending_date) AS first_trending_date,
            string_agg(DISTINCT country, '+' ORDER BY country) AS countries
        FROM trending_videos
        GROUP BY video_id
        ORDER BY video_id
    """).df()


def embed_titles(videos, batch_size=256):
    """Sentence embeddings for every title, cached on disk because computing them takes several minutes."""
    if EMBEDDINGS_PATH.exists() and EMBEDDED_VIDEOS_PATH.exists():
        cached_ids = pd.read_parquet(EMBEDDED_VIDEOS_PATH)["video_id"]
        if cached_ids.equals(videos["video_id"].reset_index(drop=True)):
            return np.load(EMBEDDINGS_PATH)
    # Imported here rather than at the top: it loads PyTorch, which takes seconds, and the cached path above
    # (and anything that only reads saved topics, like the app) never needs it.
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)
    embeddings = model.encode(videos["title"].tolist(), batch_size=batch_size, show_progress_bar=False,
                              normalize_embeddings=True)
    np.save(EMBEDDINGS_PATH, embeddings)
    videos[["video_id"]].to_parquet(EMBEDDED_VIDEOS_PATH, index=False)
    return embeddings


def fit_topic_model(titles, embeddings, min_topic_size=MIN_TOPIC_SIZE):
    """BERTopic with fixed random seeds. Returns the fitted model and one topic number per title (-1 = no topic)."""
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    topic_model = BERTopic(
        umap_model=UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=RANDOM_STATE),
        hdbscan_model=HDBSCAN(min_cluster_size=min_topic_size, metric="euclidean", cluster_selection_method="eom",
                              prediction_data=True),
        # Topic keywords only: English stop words and very rare words are dropped from the descriptions.
        vectorizer_model=CountVectorizer(stop_words="english", min_df=10, ngram_range=(1, 2)),
        calculate_probabilities=False,
    )
    topic_numbers, _ = topic_model.fit_transform(titles, embeddings)
    return topic_model, np.asarray(topic_numbers)


def build_topics(connection):
    """Embed every unique title, fit BERTopic, and save each video's topic and a summary of every topic."""
    videos = load_video_titles(connection)
    embeddings = embed_titles(videos)
    topic_model, topic_numbers = fit_topic_model(videos["title"].tolist(), embeddings)
    video_topics = videos.assign(topic=topic_numbers)
    video_topics.to_parquet(VIDEO_TOPICS_PATH, index=False)

    topic_info = topic_model.get_topic_info()
    summary = pd.DataFrame({
        "topic": topic_info["Topic"],
        "videos": topic_info["Count"],
        "keywords": [", ".join(word for word, _ in (topic_model.get_topic(topic) or [])[:8]) for topic in topic_info["Topic"]],
        "example_titles": [" || ".join(titles[:3]) for titles in topic_info["Representative_Docs"]],
    })
    return video_topics, summary


if __name__ == "__main__":
    with connect() as connection:
        video_topics, summary = build_topics(connection)
    TOPIC_SUMMARY_PATH.parent.mkdir(exist_ok=True)
    summary.to_csv(TOPIC_SUMMARY_PATH, index=False)
    outlier_share = (video_topics["topic"] == -1).mean()
    print(f"{summary['topic'].ge(0).sum()} topics; {100 * outlier_share:.1f}% of videos in no topic (-1)")
    print(summary.head(40).to_string(index=False))


NAMING_PROMPT = """You name topics found by clustering YouTube trending video titles. For each topic you get its
keywords and example titles, which may be in Hindi, Tamil, Korean or other languages. Give each topic a short
English name of 2 to 5 words that a content team would understand, such as "Premier League highlights" or "Hindi
TV serial promos". If the examples do not share one theme, name the largest group and add "(mixed)". Reply with
only a JSON object mapping each topic number (as a string) to its name."""
TOPICS_PER_NAMING_CALL = 10
EXAMPLE_TITLES_PER_TOPIC = 8


def name_topics(summary, video_topics, seed=RANDOM_STATE):
    """Ask the LLM for a short name for every topic, using its keywords and a sample of its titles."""
    names = {}
    topics = summary[summary["topic"] >= 0]
    for start in range(0, len(topics), TOPICS_PER_NAMING_CALL):
        batch = topics.iloc[start:start + TOPICS_PER_NAMING_CALL]
        lines = []
        for row in batch.itertuples():
            topic_titles = video_topics.loc[video_topics["topic"] == row.topic, "title"]
            examples = topic_titles.sample(min(EXAMPLE_TITLES_PER_TOPIC, len(topic_titles)), random_state=seed)
            lines.append(f"Topic {row.topic}\nKeywords: {row.keywords}\nTitles:\n" + "\n".join(f"- {title}" for title in examples))
        reply = complete(NAMING_PROMPT, "\n\n".join(lines), light=True)
        json_object = re.search(r"\{.*\}", reply, re.DOTALL)
        batch_names = json.loads(json_object.group(0)) if json_object else {}
        names.update({int(topic): str(name).strip() for topic, name in batch_names.items()})
    topic_names = summary["topic"].map(names).fillna("Unnamed").where(summary["topic"] >= 0, "No clear topic")
    # Topics are named in separate batches, so two can get the same name; charts need every name to be unique.
    repeated = topic_names.duplicated(keep=False) & (summary["topic"] >= 0)
    topic_names[repeated] = topic_names[repeated] + " (topic " + summary["topic"][repeated].astype(str) + ")"
    return summary.assign(name=topic_names)
