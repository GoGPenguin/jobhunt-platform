import email
from datetime import UTC, datetime, timedelta, timezone
from email import policy
from email.message import EmailMessage

import pytest

from jobhunt.sources.raw import RawPayload, redact_email, redact_url

JOB = "https://www.linkedin.com/comm/jobs/view/4428452156/"
TOKENS = (
    "trackingId=5o03pdx4QOKK%2B2MjFQAvvQ%3D%3D&refId=xxwD7ZeDTjyJVC3Wi8vjLw%3D%3D"
    "&lipi=urn%3Ali%3Apage%3Aemail&midToken=AQHFnfSMCP9Atg&midSig=3_syqoQkowNcs1"
    "&trk=eml-view_job&trkEmail=eml-view_job-null&eid=bjyi3z-mvat13hu-fh&otpToken=MDVjZmZh"
)
SECRET_MARKERS = ("otpToken", "midToken", "midSig", "MDVjZmZh", "AQHFnfSMCP9Atg")


class TestRedactUrl:
    def test_strips_linkedin_tokens(self) -> None:
        assert redact_url(f"{JOB}?{TOKENS}") == JOB

    def test_keeps_other_params_in_order(self) -> None:
        url = (
            "https://www.linkedin.com/comm/jobs/search-results/?keywords=devops&otpToken=x&geoId=1"
        )
        assert redact_url(url) == (
            "https://www.linkedin.com/comm/jobs/search-results/?keywords=devops&geoId=1"
        )

    @pytest.mark.parametrize(
        "param",
        ["utm_source=a", "UTM_Medium=b", "token=c", "access_token=d", "sig=e", "signature=f",
         "session=g", "sessionid=h", "auth=i", "apikey=j", "gclid=k", "fbclid=l", "mc_eid=m"],
    )  # fmt: skip
    def test_strips_generic_tokens_and_tracking(self, param: str) -> None:
        assert redact_url(f"https://x.io/j/7?id=7&{param}") == "https://x.io/j/7?id=7"

    def test_html_escaped_ampersands(self) -> None:
        url = f"{JOB}?keywords=devops&amp;otpToken=abc&amp;geoId=1"
        assert redact_url(url) == f"{JOB}?keywords=devops&amp;geoId=1"

    def test_strips_one_click_unsubscribe_id(self) -> None:
        url = "https://www.linkedin.com/comm/mypreferences/u/emailunsub?action=unsub&loid=AQE123"
        assert redact_url(url) == (
            "https://www.linkedin.com/comm/mypreferences/u/emailunsub?action=unsub"
        )

    def test_keeps_public_image_signature(self) -> None:
        url = (
            "https://media.licdn.com/dms/image/v2/x/company-logo_100_100/0/1/logo?e=1&v=beta&t=abc"
        )
        assert redact_url(url) == url

    def test_unchanged_without_query(self) -> None:
        assert redact_url(JOB) == JOB


UNSUBSCRIBE = (
    "<https://www.linkedin.com/mysettings-api/settingsApiEmailSubscriptionPost"
    "?lipi=urn&midToken=AQHFnfSMCP9Atg&midSig=3_sy&trk=x&trkEmail=y&eid=z&loid=AQE123>"
)


def make_email(
    text: str, html: str, message_id: str | None = "<abc@linkedin.com>", unsubscribe: bool = True
) -> bytes:
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = "LinkedIn <jobs-noreply@linkedin.com>"
    msg["Subject"] = "Spartan is hiring for a Remote role"
    if unsubscribe:
        msg["List-Unsubscribe"] = UNSUBSCRIBE
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content(text, cte="quoted-printable")
    msg.add_alternative(html, subtype="html", cte="quoted-printable")
    return msg.as_bytes()


def parts(raw: bytes) -> dict[str, str]:
    msg = email.message_from_bytes(raw, policy=policy.default)
    return {p.get_content_type(): p.get_content() for p in msg.walk() if not p.is_multipart()}


class TestRedactEmail:
    TEXT = f"DevOps Engineer\nSpartan\nHo Chi Minh City\nView job: {JOB}?{TOKENS}\n"
    HTML = f'<a href="{JOB}?{TOKENS.replace("&", "&amp;")}">DevOps Engineer</a>'

    def test_removes_tokens_from_text_and_html(self) -> None:
        redacted = redact_email(make_email(self.TEXT, self.HTML))
        for marker in SECRET_MARKERS:
            assert marker.encode() not in redacted
        content = parts(redacted)
        assert f"View job: {JOB}\n" in content["text/plain"]
        assert f'href="{JOB}"' in content["text/html"]

    def test_redacts_links_in_headers(self) -> None:
        msg = email.message_from_bytes(
            redact_email(make_email(self.TEXT, self.HTML)), policy=policy.default
        )
        assert msg["List-Unsubscribe"] == (
            "<https://www.linkedin.com/mysettings-api/settingsApiEmailSubscriptionPost>"
        )

    def test_keeps_headers_and_content(self) -> None:
        msg = email.message_from_bytes(
            redact_email(make_email(self.TEXT, self.HTML)), policy=policy.default
        )
        assert msg["Message-ID"] == "<abc@linkedin.com>"
        assert msg["Subject"] == "Spartan is hiring for a Remote role"
        assert "Ho Chi Minh City" in parts(msg.as_bytes())["text/plain"]

    def test_idempotent(self) -> None:
        once = redact_email(make_email(self.TEXT, self.HTML))
        assert redact_email(once) == once

    def test_no_urls_unchanged(self) -> None:
        raw = make_email("no links here\n", "<p>none</p>", unsubscribe=False)
        assert redact_email(raw) == raw


class TestRawPayload:
    def test_from_email_keys_by_message_id(self) -> None:
        fetched = datetime(2026, 10, 20, 9, 0, tzinfo=timezone(timedelta(hours=7)))
        raw = make_email("a\n", "<p>a</p>")
        payload = RawPayload.from_email(raw, fetched_at=fetched)
        assert payload.origin == "email:<abc@linkedin.com>"
        assert payload.content_type == "message/rfc822"
        assert payload.fetched_at == datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
        assert payload.raw_ref.startswith("raw/email/")
        # Same Message-ID, same raw_ref: re-fetching the same email is idempotent.
        again = RawPayload.from_email(make_email("b\n", "<p>b</p>"), fetched_at=fetched)
        assert again.raw_ref == payload.raw_ref

    def test_from_email_redacts(self) -> None:
        raw = make_email(TestRedactEmail.TEXT, TestRedactEmail.HTML)
        payload = RawPayload.from_email(raw, fetched_at=datetime.now(UTC))
        assert b"otpToken" not in payload.content

    def test_without_message_id_uses_content_hash(self) -> None:
        now = datetime.now(UTC)
        first = RawPayload.from_email(make_email("a\n", "<p>a</p>", None), fetched_at=now)
        second = RawPayload.from_email(make_email("b\n", "<p>b</p>", None), fetched_at=now)
        assert first.origin.startswith("email:sha256:")
        assert first.raw_ref != second.raw_ref

    def test_naive_fetched_at_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone"):
            RawPayload.from_email(make_email("a\n", "<p>a</p>"), fetched_at=datetime(2026, 1, 1))  # noqa: DTZ001
