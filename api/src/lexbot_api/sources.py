"""Citation [slug] -> URL resolution for the presentation layer.

The agent cites knowledge with [slug] tags in answer text (the [slug]
contract — agent code never changes). This module turns those tags into real
links at presentation time: source_url resolves a filename to its raw-file
URL, escape_html guards against HTML injection, format_answer_html linkifies
only slugs the agent actually cited (unknown tags stay literal — LLM
hallucination guard) and escapes everything else.
"""

import os
import re

SOURCE_URL_BASE = os.getenv(
    "SOURCE_URL_BASE",
    "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge",
)


def source_url(source: str) -> str:
    """Resolve a knowledge filename to its GitHub blob URL."""
    return f"{SOURCE_URL_BASE}/{source}"


def escape_html(text: str) -> str:
    """Escape &, < and > for safe embedding in HTML (ampersand first, so a
    previously escaped &amp; is never re-escaped into &amp;amp;)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_answer_html(answer: str, known_slugs: set[str]) -> str:
    """Escape the answer and linkify every [slug] tag whose slug was cited.

    Replacement happens after escaping, so the link text is already safe
    (a slug with no HTML-special characters appears unchanged). Unknown slugs
    keep their literal bracket form — never linkified.
    """
    escaped = escape_html(answer)
    for slug in known_slugs:
        tag = f"[{slug}]"
        url = source_url(slug).replace("&", "&amp;")
        link = f'<a href="{url}">{tag}</a>'
        escaped = re.sub(re.escape(tag), lambda _: link, escaped)
    return escaped