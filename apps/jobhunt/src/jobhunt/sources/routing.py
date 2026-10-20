"""Route an alert email to its source, only if the sender is authenticated. See spec 02 F5,
plan 02A task 5, decision 0013.

The From header can be forged, so an email is routed only when the receiving server's
Authentication-Results header (the topmost one with the trusted authserv-id; lower copies may
be forged by the sender) reports dkim=pass for the sender's domain or a subdomain of it.
"""

import email
import re
from collections.abc import Sequence
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Literal

from jobhunt.sources.config import EmailSource
from jobhunt.sources.raw import RawPayload

GMAIL_AUTHSERV_ID = "mx.google.com"
Outcome = Literal["routed", "unknown_sender", "unauthenticated", "disabled"]

_DKIM_PASS = re.compile(r"^\s*dkim=pass\b", re.IGNORECASE)
# The signing domain: header.d=example.com, or header.i=[local]@example.com.
_SIGNER = re.compile(
    r"\bheader\.d=\"?([A-Za-z0-9.-]+)|\bheader\.i=\"?[^@\s;\"]*@([A-Za-z0-9.-]+)", re.IGNORECASE
)


@dataclass(frozen=True)
class RouteResult:
    outcome: Outcome
    sender_domain: str | None
    source: EmailSource | None = None


def route(
    payload: RawPayload,
    sources: Sequence[EmailSource],
    *,
    trusted_authserv_id: str = GMAIL_AUTHSERV_ID,
) -> RouteResult:
    msg = email.message_from_bytes(payload.content, policy=policy.default)
    domain = _sender_domain(msg)
    source = next((s for s in sources if domain and _matches(domain, s.senders)), None)
    if domain is None or source is None:
        return RouteResult("unknown_sender", domain)
    if not _dkim_aligned(msg, domain, trusted_authserv_id):
        return RouteResult("unauthenticated", domain)
    if not source.enabled:
        return RouteResult("disabled", domain, source)
    return RouteResult("routed", domain, source)


def _sender_domain(msg: EmailMessage) -> str | None:
    _, address = parseaddr(str(msg["From"] or "").strip())
    _, at, domain = address.rpartition("@")
    return domain.lower() if at and domain else None


def _matches(domain: str, senders: Sequence[str]) -> bool:
    return any(_within(domain, sender.removeprefix("@")) for sender in senders)


def _within(domain: str, parent: str) -> bool:
    return domain == parent or domain.endswith("." + parent)


def _dkim_aligned(msg: EmailMessage, domain: str, authserv_id: str) -> bool:
    """dkim=pass, in the receiving server's own verdict, for a signer aligned with `domain`."""
    for header in msg.get_all("Authentication-Results") or []:
        server, *results = " ".join(str(header).split()).split(";")
        if server.strip().split()[0:1] != [authserv_id]:
            continue
        for result in results:
            signer = _SIGNER.search(result)
            if _DKIM_PASS.match(result) and signer:
                signed = (signer.group(1) or signer.group(2)).lower()
                if _within(signed, domain) or _within(domain, signed):
                    return True
        return False  # only the topmost trusted header counts
    return False
