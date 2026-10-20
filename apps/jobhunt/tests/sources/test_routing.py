from datetime import UTC, datetime
from email.message import EmailMessage

import pytest

from jobhunt.sources.config import EmailSource
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.routing import route

LINKEDIN = EmailSource.model_validate(
    {"id": "linkedin-email", "parser": "linkedin-email", "from": ["@linkedin.com"],
     "page_fetch": "forbidden", "reason": "LinkedIn prohibits automated access"}
)  # fmt: skip
ITVIEC = EmailSource.model_validate(
    {"id": "itviec-email", "parser": "itviec-email", "from": ["@itviec.com"],
     "page_fetch": "allowed", "enabled": False}
)  # fmt: skip
SOURCES = (LINKEDIN, ITVIEC)
GMAIL_DKIM_OK = (
    "mx.google.com; dkim=pass header.i=@mailb.linkedin.com header.s=d2048 header.b=t8QiuF9n;"
    " dkim=pass header.i=@linkedin.com header.s=d2048-00 header.b=dKR7AFDL;"
    " spf=pass (google.com: domain of m-1@bounce.linkedin.com designates 108.174.0.155 as"
    " permitted sender) smtp.mailfrom=m-1@bounce.linkedin.com"
)


def payload(sender: str, *auth_results: str) -> RawPayload:
    msg = EmailMessage()
    for value in auth_results:  # first = topmost = added last, by the receiving server
        msg["Authentication-Results"] = value
    msg["From"] = sender
    msg["Message-ID"] = "<1@x>"
    msg.set_content("hello\n")
    return RawPayload.from_email(msg.as_bytes(), fetched_at=datetime.now(UTC))


def test_routes_authenticated_linkedin_email() -> None:
    result = route(payload("LinkedIn <jobs-noreply@linkedin.com>", GMAIL_DKIM_OK), SOURCES)
    assert result.outcome == "routed"
    assert result.source == LINKEDIN


def test_subdomain_signature_is_aligned() -> None:
    only_sub = "mx.google.com; dkim=pass header.i=@mailb.linkedin.com header.s=x header.b=y"
    assert route(payload("jobs-noreply@linkedin.com", only_sub), SOURCES).outcome == "routed"


def test_header_d_tag_is_read() -> None:
    with_d = "mx.google.com; dkim=pass header.d=linkedin.com header.s=x"
    assert route(payload("jobs-noreply@linkedin.com", with_d), SOURCES).outcome == "routed"


@pytest.mark.parametrize(
    "auth_results",
    [
        (),  # no header at all
        ("mx.google.com; dkim=fail header.i=@linkedin.com",),
        ("mx.google.com; dkim=pass header.i=@attacker.example",),  # signed, wrong domain
        ("mx.google.com; dkim=pass header.i=@notlinkedin.com",),  # suffix but not subdomain
        ("evil.example; dkim=pass header.i=@linkedin.com",),  # someone else's verdict
        # forged "pass" placed below the receiving server's real "fail"
        ("mx.google.com; dkim=fail header.i=@linkedin.com",
         "mx.google.com; dkim=pass header.i=@linkedin.com"),
    ],
)  # fmt: skip
def test_forged_or_unsigned_linkedin_email_is_rejected(auth_results: tuple[str, ...]) -> None:
    result = route(payload("LinkedIn <jobs-noreply@linkedin.com>", *auth_results), SOURCES)
    assert result.outcome == "unauthenticated"
    assert result.source is None


def test_unknown_sender() -> None:
    signed = "mx.google.com; dkim=pass header.i=@shop.example"
    result = route(payload("deals@shop.example", signed), SOURCES)
    assert result.outcome == "unknown_sender"
    assert result.sender_domain == "shop.example"


def test_disabled_source() -> None:
    signed = "mx.google.com; dkim=pass header.i=@itviec.com"
    result = route(payload("ITviec <love@itviec.com>", signed), SOURCES)
    assert result.outcome == "disabled"
    assert result.source == ITVIEC


def test_trusted_server_is_configurable() -> None:
    other = "mail.example.org; dkim=pass header.i=@linkedin.com"
    msg = payload("jobs-noreply@linkedin.com", other)
    assert route(msg, SOURCES).outcome == "unauthenticated"
    assert route(msg, SOURCES, trusted_authserv_id="mail.example.org").outcome == "routed"


def test_missing_from_header() -> None:
    msg = EmailMessage()
    msg["Message-ID"] = "<2@x>"
    msg.set_content("x\n")
    raw = RawPayload.from_email(msg.as_bytes(), fetched_at=datetime.now(UTC))
    assert route(raw, SOURCES).outcome == "unknown_sender"
