import json

import requests

from fpl_planner.config import LLM_MODEL, USER_AGENT, get_anthropic_api_key


class LLMUnavailable(Exception):
    """Raised when no ANTHROPIC_API_KEY is configured; callers should catch
    this and skip the LLM-dependent signal rather than fail the whole fetch."""


def fetch_page_text(url, max_chars=15000):
    """Plain GET, trimmed to keep LLM extraction calls cheap. Match reports
    and squad pages are prose/tables, not JSON, so there's no structured
    parse to do here - the trimmed HTML goes straight to the model."""
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    response.raise_for_status()
    return response.text[:max_chars]


def extract_json(prompt, page_text, schema_hint):
    """Ask the configured model to pull structured data out of prose/HTML
    that has no reliable regex/CSS-selector pattern (match reports, squad
    write-ups). Returns parsed JSON matching `schema_hint`'s shape, or raises
    LLMUnavailable if no API key is configured.
    """
    api_key = get_anthropic_api_key()
    if not api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set")

    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    full_prompt = (
        f"{prompt}\n\n"
        f"Respond with ONLY a JSON value matching this shape (no prose, no markdown fences): "
        f"{json.dumps(schema_hint)}\n\n"
        f"If nothing relevant is found, respond with an empty list/object matching that shape.\n\n"
        f"--- PAGE CONTENT ---\n{page_text}"
    )
    message = client.messages.create(
        model=LLM_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": full_prompt}],
    )
    text = "".join(block.text for block in message.content if block.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
