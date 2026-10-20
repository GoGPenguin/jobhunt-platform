import textwrap
from pathlib import Path

import pytest

from jobhunt.config_files import ConfigError
from jobhunt.preferences import load_accepted_languages
from jobhunt.sources.config import SourcesConfig, load_sources

REPO = Path(__file__).resolve().parents[4]
SAMPLE = REPO / "config" / "sources.sample.yaml"
KNOWN = {"linkedin-email", "itviec-email"}

VALID = """\
schema_version: 1
email:
  imap: { host: imap.gmail.com, label: jobhunt }
  schedule: "*/30 * * * *"
  sources:
    - id: linkedin-email
      parser: linkedin-email
      from: ["@linkedin.com"]
      page_fetch: forbidden
      reason: LinkedIn prohibits automated access
    - id: itviec-email
      parser: itviec-email
      from: ["@itviec.com"]
      page_fetch: allowed
"""


def write(tmp_path: Path, text: str, name: str = "sources.yaml") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def load(tmp_path: Path, text: str) -> SourcesConfig:
    return load_sources(write(tmp_path, text), known_parsers=KNOWN)


def test_sample_config_is_valid() -> None:
    config = load_sources(SAMPLE, known_parsers={"linkedin-email"})
    assert config.email is not None
    assert [s.id for s in config.email.sources] == ["linkedin-email"]


def test_valid_config(tmp_path: Path) -> None:
    config = load(tmp_path, VALID)
    assert config.email is not None
    assert config.email.imap.label == "jobhunt"
    assert config.email.imap.port == 993
    linkedin = config.email.sources[0]
    assert linkedin.senders == ("@linkedin.com",)
    assert linkedin.enabled


def test_unknown_parser_named_in_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"email\.sources\[1\] \(itviec-email\).*parser 'nope'"):
        load(tmp_path, VALID.replace("parser: itviec-email", "parser: nope"))


def test_duplicate_id(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate source id 'linkedin-email'"):
        load(tmp_path, VALID.replace("id: itviec-email", "id: linkedin-email"))


def test_same_sender_in_two_sources(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"'@itviec\.com' is routed to more than one source"):
        load(tmp_path, VALID.replace('from: ["@linkedin.com"]', 'from: ["@itviec.com"]'))


def test_invalid_slug(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"email\.sources\[0\].*id"):
        load(tmp_path, VALID.replace("id: linkedin-email", "id: LinkedIn Email"))


@pytest.mark.parametrize("sender", ["linkedin.com", "@LinkedIn.com", "@", "jobs@linkedin.com"])
def test_invalid_sender(tmp_path: Path, sender: str) -> None:
    with pytest.raises(ConfigError, match="from"):
        load(tmp_path, VALID.replace('"@itviec.com"', f'"{sender}"'))


def test_forbidden_needs_reason(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="reason"):
        load(tmp_path, VALID.replace("      reason: LinkedIn prohibits automated access\n", ""))


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("page_fetch: forbidden", "page_fetch: allowed"),  # LinkedIn by sender
        ('"@itviec.com"', '"@e.linkedin.com"'),  # a LinkedIn subdomain on another source
    ],
)
def test_linkedin_page_fetch_can_never_be_allowed(tmp_path: Path, old: str, new: str) -> None:
    with pytest.raises(ConfigError, match="LinkedIn"):
        load(tmp_path, VALID.replace(old, new))


def test_unknown_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="pagefetch"):
        load(tmp_path, VALID.replace("page_fetch: allowed", "pagefetch: allowed"))


def test_duplicate_yaml_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate key 'label'"):
        load(tmp_path, VALID.replace("label: jobhunt }", "label: jobhunt, label: other }"))


def test_not_yaml_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="mapping"):
        load(tmp_path, "- just\n- a list\n")


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_sources(tmp_path / "nope.yaml", known_parsers=KNOWN)


# Posting-language filter from preferences.yaml


def test_accepted_languages(tmp_path: Path) -> None:
    path = write(tmp_path, "languages:\n  postings: [vi, en]\n", "preferences.yaml")
    assert load_accepted_languages(path) == frozenset({"vi", "en"})


def test_no_preferences_file_means_no_filter(tmp_path: Path) -> None:
    assert load_accepted_languages(tmp_path / "preferences.yaml") is None


def test_preferences_without_postings_means_no_filter(tmp_path: Path) -> None:
    path = write(tmp_path, "languages:\n  outputs: [en]\n", "preferences.yaml")
    assert load_accepted_languages(path) is None


@pytest.mark.parametrize("postings", ["[vn]", "vi", "[]"])
def test_invalid_postings(tmp_path: Path, postings: str) -> None:
    path = write(tmp_path, f"languages:\n  postings: {postings}\n", "preferences.yaml")
    with pytest.raises(ConfigError, match="postings"):
        load_accepted_languages(path)
