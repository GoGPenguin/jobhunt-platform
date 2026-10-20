"""Fixtures and sample config are committed to a public repo: they must not contain tokens, real
email addresses or personal details (spec 02 F6, spec 06 P8).

Personal strings to look for are kept outside the repo, one per line, in
~/.config/jobhunt/privacy-scan.txt (name, addresses, phone, employer...). Where that file doesn't
exist, e.g. in CI, only the token and address checks run.
"""

import email
import re
from email import policy
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[3]
PRIVATE_STRINGS = Path.home() / ".config" / "jobhunt" / "privacy-scan.txt"
TOKEN_PARAMS = ("otptoken=", "midtoken=", "midsig=", "loid=", "sessionid=", "access_token=")
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "linkedin.com")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
FILES = sorted(p for p in FIXTURES.rglob("*") if p.is_file()) + sorted((REPO / "config").glob("*"))


def readable_text(path: Path) -> str:
    """File content as a person would read it: decoded parts and headers for emails."""
    if path.suffix != ".eml":
        return path.read_text(encoding="utf-8")
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    headers = "\n".join(f"{k}: {v}" for k, v in msg.items())
    parts = [p.get_content() for p in msg.walk() if p.get_content_maintype() == "text"]
    return "\n".join([headers, *parts])


def private_strings() -> list[str]:
    if not PRIVATE_STRINGS.exists():
        return []
    lines = PRIVATE_STRINGS.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_tokens(path: Path) -> None:
    text = readable_text(path).lower()
    assert not [t for t in TOKEN_PARAMS if t in text]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_only_example_email_addresses(path: Path) -> None:
    domains = {d.lower() for d in _EMAIL.findall(readable_text(path))}
    allowed = ALLOWED_EMAIL_DOMAINS
    assert not [d for d in domains if not any(d == a or d.endswith("." + a) for a in allowed)]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_no_personal_strings(path: Path) -> None:
    strings = private_strings()
    if not strings:
        pytest.skip(f"{PRIVATE_STRINGS} not present")
    text = readable_text(path).lower()
    found = [s for s in strings if s.lower() in text]
    assert not found, f"{len(found)} personal string(s) found; see {PRIVATE_STRINGS}"
