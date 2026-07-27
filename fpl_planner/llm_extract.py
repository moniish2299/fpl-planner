import json

import requests

from fpl_planner.config import LLM_MODEL, LLM_PROVIDER, USER_AGENT, get_llm_api_key


class LLMUnavailable(Exception):
    """Raised when no API key is configured for the selected provider;
    callers should catch this and skip the LLM-dependent signal rather than
    fail the whole fetch."""


def fetch_page_text(url, max_chars=15000):
    """Plain GET, trimmed to keep LLM extraction calls cheap. Match reports
    and squad pages are prose/tables, not JSON, so there's no structured
    parse to do here - the trimmed HTML goes straight to the model."""
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    response.raise_for_status()
    return response.text[:max_chars]


def _call_gemini(api_key, full_prompt):
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=LLM_MODEL, contents=full_prompt)
    return (response.text or "").strip()


def _call_anthropic(api_key, full_prompt):
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=LLM_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": full_prompt}],
    )
    return "".join(block.text for block in message.content if block.type == "text").strip()


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
