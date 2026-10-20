import unicodedata
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from jobhunt.domain.normalize import (
    clean_line,
    clean_text,
    date_to_utc,
    html_to_text,
    normalize_url,
    to_utc,
)

ICT = timezone(timedelta(hours=7))  # Vietnam time, fixed offset so tests need no tz database


class TestCleanLine:
    def test_decomposed_vietnamese_equals_composed(self) -> None:
        composed = "Kỹ sư DevOps tại Đà Nẵng"
        decomposed = unicodedata.normalize("NFD", composed)
        assert decomposed != composed
        assert clean_line(decomposed) == composed

    def test_collapses_and_trims_whitespace(self) -> None:
        assert clean_line("  Senior\t Platform \n Engineer\u00a0 ") == "Senior Platform Engineer"

    def test_empty(self) -> None:
        assert clean_line(" \n\t ") == ""


class TestCleanText:
    def test_keeps_lines_trims_each(self) -> None:
        assert clean_text("  first   line  \nsecond\tline ") == "first line\nsecond line"

    def test_collapses_blank_lines_to_one(self) -> None:
        assert clean_text("a\n\n\n\n b \n\n\nc") == "a\n\nb\n\nc"

    def test_nfc(self) -> None:
        assert clean_text(unicodedata.normalize("NFD", "Lương")) == "Lương"


class TestNormalizeUrl:
    def test_spec_example(self) -> None:
        url = "HTTPS://Jobs.Example.COM/Careers/123?utm_source=x&b=2&a=1#apply"
        assert normalize_url(url) == "https://jobs.example.com/Careers/123?a=1&b=2"

    @pytest.mark.parametrize(
        "param", ["utm_medium=email", "UTM_Campaign=x", "gclid=1", "fbclid=2", "ref=3", "source=4"]
    )
    def test_drops_tracking_params(self, param: str) -> None:
        assert normalize_url(f"https://x.io/j?id=7&{param}") == "https://x.io/j?id=7"

    def test_drops_empty_query(self) -> None:
        assert normalize_url("https://x.io/j?utm_source=a&utm_medium=b") == "https://x.io/j"

    def test_keeps_blank_values_and_encoding(self) -> None:
        assert (
            normalize_url("https://x.io/s?q=dev%20ops&lang=") == "https://x.io/s?lang=&q=dev%20ops"
        )

    def test_keeps_port_drops_credentials(self) -> None:
        assert normalize_url("https://user:pw@X.io:8443/j") == "https://x.io:8443/j"

    def test_http_rejected_by_default(self) -> None:
        with pytest.raises(ValueError, match="https"):
            normalize_url("http://x.io/j")

    def test_http_allowed_when_source_allows(self) -> None:
        assert normalize_url("HTTP://X.io/j", allow_http=True) == "http://x.io/j"

    @pytest.mark.parametrize(
        "url",
        ["javascript:alert(1)", "ftp://x.io/f", "mailto:hr@x.io", "https:///no-host", "x.io/j"],
    )
    def test_rejects_invalid(self, url: str) -> None:
        with pytest.raises(ValueError, match="URL"):
            normalize_url(url)


class TestDatetimes:
    def test_converts_to_utc(self) -> None:
        local = datetime(2026, 10, 20, 9, 30, tzinfo=ICT)
        assert to_utc(local) == datetime(2026, 10, 20, 2, 30, tzinfo=UTC)
        assert to_utc(local).tzinfo is UTC

    def test_rejects_naive(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            to_utc(datetime(2026, 10, 20, 9, 30))  # noqa: DTZ001 - the case under test

    def test_date_becomes_midnight_utc(self) -> None:
        assert date_to_utc(date(2026, 10, 20)) == datetime(2026, 10, 20, tzinfo=UTC)


class TestHtmlToText:
    def test_paragraphs_and_inline(self) -> None:
        html = "<p>Hello&nbsp;<b>world</b></p><p>Second <a href='/x'>link</a></p>"
        assert html_to_text(html) == "Hello world\n\nSecond link"

    def test_lists_become_bullets(self) -> None:
        html = "<p>Must have:</p><ul><li>Python</li><li><p>Go</p></li></ul><ol><li>One</li></ol>"
        assert html_to_text(html) == "Must have:\n\n- Python\n\n- Go\n\n- One"

    def test_br_and_headings(self) -> None:
        html = "<h2>Role</h2>line1<br>line2<br/>line3"
        assert html_to_text(html) == "Role\n\nline1\nline2\nline3"

    def test_removes_script_style_and_hidden(self) -> None:
        html = "<head><title>T</title></head><style>p{}</style><p>a</p><script>alert(1)</script>"
        html += "<noscript>enable js</noscript><template><p>x</p></template>"
        assert html_to_text(html) == "a"

    def test_decodes_entities(self) -> None:
        assert html_to_text("<p>R&amp;D &lt;3 &#7899;</p>") == "R&D <3 ớ"

    def test_collapses_source_whitespace_and_empty_blocks(self) -> None:
        html = "<div>\n  <p>\n   Hello\n     world\n  </p>\n<p></p><p> </p><p>bye</p></div>"
        assert html_to_text(html) == "Hello world\n\nbye"

    def test_table_cells_separated(self) -> None:
        html = "<table><tr><td>Salary</td><td>2000 USD</td></tr><tr><td>Level</td></tr></table>"
        assert html_to_text(html) == "Salary 2000 USD\n\nLevel"

    def test_nfc_vietnamese(self) -> None:
        html = "<p>" + unicodedata.normalize("NFD", "Kỹ sư hạ tầng") + "</p>"
        assert html_to_text(html) == "Kỹ sư hạ tầng"

    def test_plain_text_passes_through(self) -> None:
        assert html_to_text("Salary < 2000 USD\nRemote") == "Salary < 2000 USD Remote"

    def test_empty(self) -> None:
        assert html_to_text("") == ""
