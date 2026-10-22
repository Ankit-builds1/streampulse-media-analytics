import os
from functools import lru_cache

from dotenv import load_dotenv
from groq import Groq

from streampulse.load import PROJECT_ROOT

DEFAULT_MODEL = "openai/gpt-oss-120b"

load_dotenv(PROJECT_ROOT / ".env")


@lru_cache(maxsize=1)
def _groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Copy .env.example to .env and add your Groq key.")
    return Groq(api_key=api_key)


def model_name():
    """The Groq model in use: GROQ_MODEL from .env if set, otherwise the default."""
    return os.getenv("GROQ_MODEL") or DEFAULT_MODEL


def complete(system_prompt, user_prompt, temperature=0.0):
    """Send a system and a user message to the Groq model and return the reply text."""
    response = _groq_client().chat.completions.create(
        model=model_name(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content
