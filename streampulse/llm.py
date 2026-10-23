import os
from functools import lru_cache

from dotenv import load_dotenv
from groq import Groq

from streampulse.load import PROJECT_ROOT

DEFAULT_MODEL = "openai/gpt-oss-120b"
# Short, simple tasks (naming topics, one-paragraph notes) use a smaller model. Groq counts its free daily
# token limit per model, so this also keeps the main model's quota for the harder tasks.
DEFAULT_LIGHT_MODEL = "openai/gpt-oss-20b"

load_dotenv(PROJECT_ROOT / ".env")


@lru_cache(maxsize=1)
def _groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Copy .env.example to .env and add your Groq key.")
    # The free tier has per-minute token limits. The client waits as long as Groq asks before retrying a
    # rate-limited call; more retries than the default 2 let short bursts, such as explaining 20 spikes, finish.
    return Groq(api_key=api_key, max_retries=5)


def model_name(light=False):
    """The Groq model in use: GROQ_MODEL (or GROQ_LIGHT_MODEL for light tasks) from .env if set, else the default."""
    if light:
        return os.getenv("GROQ_LIGHT_MODEL") or DEFAULT_LIGHT_MODEL
    return os.getenv("GROQ_MODEL") or DEFAULT_MODEL


def complete(system_prompt, user_prompt, temperature=0.0, light=False):
    """Send a system and a user message to the Groq model and return the reply text."""
    response = _groq_client().chat.completions.create(
        model=model_name(light),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content
