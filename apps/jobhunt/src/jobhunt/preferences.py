"""The parts of preferences.yaml the collectors need. The profile spec formalizes the rest."""

import logging
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jobhunt.config_files import ConfigError, read_yaml_mapping
from jobhunt.domain.codes import LANGUAGE_CODES

log = logging.getLogger(__name__)


def load_accepted_languages(path: Path) -> frozenset[str] | None:
    """Posting languages to keep (`languages.postings`), or None for no language filter.

    A missing file or a missing key means no filter, with a warning, so a fresh copy of the
    project works before a profile exists.
    """
    if not path.exists():
        log.warning("%s not found: no posting-language filter", path)
        return None
    postings = (read_yaml_mapping(path).get("languages") or {}).get("postings")
    if postings is None:
        log.warning("%s has no languages.postings: no posting-language filter", path)
        return None
    if not isinstance(postings, list) or not postings:
        raise ConfigError(f"{path}: languages.postings must be a non-empty list, e.g. [vi, en]")
    unknown = [code for code in postings if code not in LANGUAGE_CODES]
    if unknown:
        raise ConfigError(f"{path}: languages.postings has invalid ISO 639-1 codes: {unknown}")
    return frozenset(postings)


def load_timezone(path: Path) -> ZoneInfo:
    """`candidate.timezone` (an IANA name such as Asia/Ho_Chi_Minh) for showing times; UTC if
    the file or the key is missing."""
    if not path.exists():
        return ZoneInfo("UTC")
    name = (read_yaml_mapping(path).get("candidate") or {}).get("timezone")
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError):
        message = f"{path}: candidate.timezone {name!r} is not a known IANA timezone"
        raise ConfigError(message) from None
