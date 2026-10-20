"""Normalizers applied to every canonical job, whatever source it came from.

See docs/spec/01-canonical-job-schema.md, section "Normalization".
"""

import re
import unicodedata
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib.parse import unquote_plus, urlsplit, urlunsplit

_TRACKING_PARAMS = frozenset({"gclid", "fbclid", "ref", "source"})
_BLANK_LINES = re.compile(r"\n{3,}")
_WHITESPACE = re.compile(r"\s+")


def clean_line(text: str) -> str:
    """NFC-normalize, collapse all whitespace to single spaces and trim. For titles and names."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def clean_text(text: str) -> str:
    """NFC-normalize multi-line text: trim each line, keep at most one blank line in a row."""
    lines = (" ".join(line.split()) for line in unicodedata.normalize("NFC", text).splitlines())
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def normalize_url(url: str, *, allow_http: bool = False) -> str:
    """Lowercase scheme and host, drop credentials, fragment and tracking parameters,
    and sort the remaining query parameters. Raises ValueError for anything but an
    absolute HTTPS URL (or HTTP when the source allows it)."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("https", "http") or not parts.hostname:
        raise ValueError(f"not an absolute web URL: {url!r}")
    if scheme == "http" and not allow_http:
        raise ValueError(f"URL must use https: {url!r}")

    host = parts.hostname  # already lowercased, without credentials
    if ":" in host:
        host = f"[{host}]"  # IPv6
    netloc = f"{host}:{parts.port}" if parts.port else host

    params = [p for p in parts.query.split("&") if p and not _is_tracking(p)]
    query = "&".join(sorted(params, key=lambda p: (p.split("=", 1)[0], p)))
    return urlunsplit((scheme, netloc, parts.path, query, ""))


def _is_tracking(param: str) -> bool:
    key = unquote_plus(param.split("=", 1)[0]).lower()
    return key.startswith("utm_") or key in _TRACKING_PARAMS


def to_utc(value: datetime) -> datetime:
    """Convert an aware datetime to UTC. Naive datetimes are rejected: guessing the
    timezone could shift a posting date by up to a day."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"datetime has no timezone: {value.isoformat()}")
    return value.astimezone(UTC)


def date_to_utc(value: date) -> datetime:
    """A date without a time becomes 00:00 UTC on that date."""
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def html_to_text(html: str) -> str:
    """Convert job-description HTML to plain text. Block elements become paragraphs,
    list items become "- " bullets, scripts and styles are dropped, entities decoded."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "head"})
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "header", "footer", "main", "aside",
        "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "dl", "dt", "dd",
        "table", "tr", "blockquote", "pre", "hr", "figure",
    }
)  # fmt: skip


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._bullet_pending = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "br":
            self._parts.append("\n")
        elif tag == "li":
            self._parts.append("\n\n")
            self._bullet_pending = True
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")
        elif tag in ("td", "th"):
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS or tag == "li":
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _WHITESPACE.sub(" ", data)
        if self._bullet_pending and text.strip():
            text = "- " + text.lstrip()
            self._bullet_pending = False
        self._parts.append(text)

    def text(self) -> str:
        return clean_text("".join(self._parts))
