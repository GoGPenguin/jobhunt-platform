"""Raw payloads: what a transport fetched, stored before parsing so parsers can be re-run.

Emails are redacted before they become a payload: sign-in and tracking parameters are removed
from every link (LinkedIn alert links carry one-time sign-in tokens). Everything else is kept.
See plan 02A, task 2.
"""

import email
import hashlib
import re
from datetime import datetime
from email import policy
from email.parser import BytesHeaderParser
from typing import Self
from urllib.parse import unquote_plus

from pydantic import BaseModel, ConfigDict

from jobhunt.domain.job import UtcDatetime
from jobhunt.domain.normalize import to_utc

_SENSITIVE_PARAMS = frozenset(
    {
        # sign-in and session tokens
        "otptoken", "midtoken", "midsig", "token", "access_token", "auth", "authtoken",
        "sig", "signature", "session", "sessionid", "apikey", "api_key",
        # one-click unsubscribe ids, which act on the account without signing in
        "loid",
        # tracking ids
        "eid", "lipi", "refid", "trackingid", "gclid", "fbclid", "mc_eid", "mc_cid",
    }
)  # fmt: skip
_SENSITIVE_PREFIXES = ("utm_", "trk")
_URL = re.compile(r"https?://[^\s\"'<>]+")


def redact_url(url: str) -> str:
    """Remove token and tracking query parameters; keep everything else as written."""
    base, has_query, rest = url.partition("?")
    if not has_query:
        return url
    query, has_fragment, fragment = rest.partition("#")
    separator = "&amp;" if "&amp;" in query else "&"  # links inside HTML
    kept = [p for p in query.split(separator) if p and not _is_sensitive(p)]
    redacted = base + ("?" + separator.join(kept) if kept else "")
    return redacted + has_fragment + fragment


def _is_sensitive(param: str) -> bool:
    key = unquote_plus(param.split("=", 1)[0]).lower()
    return key in _SENSITIVE_PARAMS or key.startswith(_SENSITIVE_PREFIXES)


def _redact_links(text: str) -> str:
    return _URL.sub(lambda m: redact_url(m.group()), text)


def redact_email(raw: bytes) -> bytes:
    """Redact links in the headers (e.g. List-Unsubscribe) and every text part of an email.
    Returns the input unchanged if no link needed redacting, so redaction is idempotent."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    changed = False
    for name, value in list(msg.items()):
        redacted_value = _redact_links(str(value))
        if redacted_value != str(value):
            msg.replace_header(name, redacted_value)
            changed = True
    for part in msg.walk():
        if part.is_multipart() or part.get_content_maintype() != "text":
            continue
        content = part.get_content()
        redacted = _redact_links(content)
        if redacted != content:
            part.set_content(redacted, subtype=part.get_content_subtype(), cte="quoted-printable")
            changed = True
    return msg.as_bytes() if changed else raw


class RawPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_ref: str
    origin: str  # where it came from, e.g. "email:<message-id>"
    content_type: str
    content: bytes
    fetched_at: UtcDatetime

    @classmethod
    def from_email(cls, raw: bytes, *, fetched_at: datetime) -> Self:
        """Redact an email and key it by Message-ID (content hash if it has none), so fetching
        the same email again gives the same raw_ref."""
        content = redact_email(raw)
        origin = email_origin(message_id(content), content)
        return cls(
            raw_ref=raw_ref_for(origin),
            origin=origin,
            content_type="message/rfc822",
            content=content,
            fetched_at=to_utc(fetched_at),
        )


def message_id(raw: bytes) -> str:
    """The Message-ID header of an email (or of its headers alone), "" if it has none."""
    headers = BytesHeaderParser(policy=policy.default).parsebytes(raw)
    return str(headers["Message-ID"] or "").strip()  # strip: 3.12.3 keeps folding whitespace


def email_origin(message_id: str, content: bytes) -> str:
    """`email:<Message-ID>`, or a content hash for email without one."""
    return f"email:{message_id}" if message_id else f"email:sha256:{_sha256(content)}"


def raw_ref_for(origin: str) -> str:
    return f"raw/email/{_sha256(origin.encode())[:32]}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
