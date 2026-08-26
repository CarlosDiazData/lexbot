"""Citation link resolution tests (presentation layer).

LexBot answers cite knowledge with [slug] tags (e.g. [01-firm-policies.md]).
sources.py turns those tags into real GitHub links at the presentation layer:
escape_html guards against HTML injection, source_url resolves a filename to
its raw-file URL, format_answer_html linkifies ONLY slugs the agent actually
cited (unknown tags stay literal — LLM hallucination guard).
"""

from lexbot_api.sources import SOURCE_URL_BASE, escape_html, format_answer_html, source_url

EXPECTED_URL = (
    "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge/01-firm-policies.md"
)


def test_source_url_default_base():
    assert SOURCE_URL_BASE == "https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge"
    assert source_url("01-firm-policies.md") == EXPECTED_URL


def test_source_url_appends_filename_unchanged():
    assert source_url("02-faq-clients.md").endswith("/02-faq-clients.md")


def test_escape_html_escapes_ampersand_first():
    assert escape_html("a & b") == "a &amp; b"


def test_escape_html_does_not_double_escape_ampersand():
    assert escape_html("&") == "&amp;"
    assert "&amp;amp;" not in escape_html("<&>")


def test_escape_html_escapes_angle_brackets():
    assert escape_html("<script>") == "&lt;script&gt;"
    assert escape_html("<a href='x'>") == "&lt;a href='x'&gt;"


def test_format_answer_html_links_known_slugs():
    answer = "See [01-firm-policies.md] for details."
    expected = (
        f'See <a href="{EXPECTED_URL}">[01-firm-policies.md]</a> for details.'
    )
    assert format_answer_html(answer, {"01-firm-policies.md"}) == expected


def test_format_answer_html_leaves_unknown_slugs_literal():
    answer = "See [bogus.md] for details."
    assert format_answer_html(answer, {"01-firm-policies.md"}) == answer


def test_format_answer_html_escapes_html_in_text():
    answer = "Results <script>alert(1)</script> [01-firm-policies.md]"
    result = format_answer_html(answer, {"01-firm-policies.md"})
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert EXPECTED_URL in result


def test_format_answer_html_does_not_double_escape_link_text():
    answer = "[01-firm-policies.md]"
    assert format_answer_html(answer, {"01-firm-policies.md"}) == (
        f'<a href="{EXPECTED_URL}">[01-firm-policies.md]</a>'
    )