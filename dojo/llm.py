"""Azure AI Foundry chat client + JSONL call logging.

Auth: Azure CLI login (`az login`). No API keys in code or env.
"""
import json
import os
import time
import threading

from azure.identity import AzureCliCredential, get_bearer_token_provider
from openai import AzureOpenAI

ENDPOINT = os.environ.get(
    "AZURE_FOUNDRY_ENDPOINT",
    "https://nodestra-final-resource.cognitiveservices.azure.com/",
)
API_VERSION = "2024-10-21"

# Student is deliberately the weaker model; teacher the stronger one.
STUDENT_MODEL = os.environ.get("DOJO_STUDENT_MODEL", "gpt-4o-mini")
TEACHER_MODEL = os.environ.get("DOJO_TEACHER_MODEL", "gpt-4o")

LOG_DIR = "/Users/hanavmodasiya/trainme/logs"
_log_lock = threading.Lock()
_client = None


def client():
    global _client
    if _client is None:
        tp = get_bearer_token_provider(
            AzureCliCredential(), "https://cognitiveservices.azure.com/.default"
        )
        _client = AzureOpenAI(
            azure_endpoint=ENDPOINT,
            azure_ad_token_provider=tp,
            api_version=API_VERSION,
        )
    return _client


def _log(record):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, "calls.jsonl")
    with _log_lock:
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")


def chat(model, system, user, max_tokens=600, temperature=0.0, tag=""):
    """One chat turn. Returns text. Logs every call to logs/calls.jsonl."""
    t0 = time.time()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    err = None
    text = ""
    usage = {}
    try:
        r = client().chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = r.choices[0].message.content or ""
        if r.usage:
            usage = {"in": r.usage.prompt_tokens, "out": r.usage.completion_tokens}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        raise
    finally:
        _log({
            "ts": time.time(),
            "tag": tag,
            "model": model,
            "latency_s": round(time.time() - t0, 2),
            "usage": usage,
            "error": err,
            "system": system,
            "user": user,
            "response": text,
        })
    return text


def selftest():
    for m in (STUDENT_MODEL, TEACHER_MODEL):
        try:
            out = chat(m, "You are terse.", "Reply with the single word: ok",
                       max_tokens=5, tag="selftest")
            print(f"{m}: OK -> {out.strip()!r}")
        except Exception as e:
            print(f"{m}: FAIL {type(e).__name__}: {str(e)[:300]}")


if __name__ == "__main__":
    selftest()
