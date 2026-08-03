import json
import re
import time

import requests

from fpl_planner.config import LLM_MODEL, LLM_PROVIDER, USER_AGENT, get_llm_api_key


class LLMUnavailable(Exception):
    """Raised when no API key is configured for the selected provider;
    callers should catch this and skip the LLM-dependent signal rather than
    fail the whole fetch."""


_NOISE_TAGS = re.compile(r"<(script|style|svg|noscript)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_RUN_OF_SPACES = re.compile(r"[ \t]{2,}")
_RUN_OF_BLANK_LINES = re.compile(r"\n{3,}")


def _clean_html(html):
    """Strip script/style/svg blocks and remaining tags so a page's fixed
    character budget goes to actual visible text - raw HTML was leaving
    nothing but markup/icon-sprite noise within max_chars for content-heavy
    pages (large inline SVGs, long inline JSON blobs)."""
    text = _NOISE_TAGS.sub(" ", html)
    text = _TAG.sub("\n", text)
    text = _RUN_OF_SPACES.sub(" ", text)
    text = _RUN_OF_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _with_retries(fn, attempts=3, base_delay=2):
    """A handful of the sites/APIs this hits (club/news sites, the LLM
    provider itself) return transient 429/5xx under load - worth a couple of
    retries before giving up on what's otherwise a working source."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            transient = status in (429, 500, 502, 503, 504) or "UNAVAILABLE" in str(exc) or " 503" in str(exc)
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(base_delay * (attempt + 1))
    raise last_exc


def fetch_page_text(url, max_chars=20000):
    """Cleaned visible text, trimmed to keep LLM extraction calls cheap."""

    def attempt():
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        response.raise_for_status()
        return response.text

    html = _with_retries(attempt)
    return _clean_html(html)[:max_chars]


def _call_gemini(api_key, full_prompt):
    from google import genai

    client = genai.Client(api_key=api_key)

    def attempt():
        response = client.models.generate_content(model=LLM_MODEL, contents=full_prompt)
        return (response.text or "").strip()

    return _with_retries(attempt)


def _call_anthropic(api_key, full_prompt):
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    def attempt():
        message = client.messages.create(
            model=LLM_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": full_prompt}],
        )
        return "".join(block.text for block in message.content if block.type == "text").strip()

    return _with_retries(attempt)


_PROVIDER_CALLERS = {
    "gemini": _call_gemini,
    "anthropic": _call_anthropic,
}


def extract_json(prompt, page_text, schema_hint):
    """Ask the configured model (FPL_PLANNER_LLM_PROVIDER, default "gemini")
    to pull structured data out of prose/HTML that has no reliable
    regex/CSS-selector pattern (match reports, squad write-ups). Returns
    parsed JSON matching `schema_hint`'s shape, or raises LLMUnavailable if
    no API key is configured for that provider.
    """
    api_key = get_llm_api_key()
    if not api_key:
        raise LLMUnavailable(f"No API key set for LLM provider '{LLM_PROVIDER}'")

    caller = _PROVIDER_CALLERS.get(LLM_PROVIDER)
    if caller is None:
        raise LLMUnavailable(f"Unknown LLM provider '{LLM_PROVIDER}'")

    full_prompt = (
        f"{prompt}\n\n"
        f"Respond with ONLY a JSON value matching this shape (no prose, no markdown fences): "
        f"{json.dumps(schema_hint)}\n\n"
        f"If nothing relevant is found, respond with an empty list/object matching that shape.\n\n"
        f"--- PAGE CONTENT ---\n{page_text}"
    )
    text = caller(api_key, full_prompt)
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
