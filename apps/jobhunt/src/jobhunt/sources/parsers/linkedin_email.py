"""LinkedIn job-alert emails -> job records. See plan 02A task 6, decision 0014.

Reads the text/plain part, where each job is a paragraph:

    Title
    Company
    Location [(Remote|Hybrid|On-site)]
    [badge lines, e.g. "Apply with resume & profile"]
    View job: https://www.linkedin.com/comm/jobs/view/<id>/?...

Links are parsed, never followed (LinkedIn hard deny). The job URL is rebuilt from the id, so no
query parameter from the email reaches the job. LinkedIn emails have no description; enrichment
comes later (spec 02, phase D).
"""

import email
import re
from email import policy
from typing import Any

from jobhunt.domain.codes import COUNTRY_NAMES
from jobhunt.domain.language import detect_language
from jobhunt.sources.raw import RawPayload
from jobhunt.sources.registry import REGISTRY

NAME = "linkedin-email"
VERSION = "1.0.0"

KNOWN_BADGES = frozenset(
    {
        "Apply with resume & profile",
        "Actively recruiting",
        "Be an early applicant",
        "Easy Apply",
        "Promoted",
        "Your profile matches this job",
    }
)
_VIEW_JOB = re.compile(r"^View job:\s*(\S+)$")
_JOB_ID = re.compile(r"/jobs/view/(\d+)")
_SEPARATOR = re.compile(r"^-{10,}$")
_WORKPLACE = re.compile(r"\s*\((Remote|Hybrid|On-site)\)$", re.IGNORECASE)
_WORKPLACES = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}
_EMAIL_KIND = re.compile(r"^\s*You are receiving (.+?) emails\.?\s*$", re.MULTILINE)


@REGISTRY.register(NAME, VERSION)
def parse(payload: RawPayload) -> list[dict[str, Any]]:
    msg = email.message_from_bytes(payload.content, policy=policy.default)
    body = msg.get_body(("plain",))
    if body is None:
        return []
    text = body.get_content()
    kind_match = _EMAIL_KIND.search(text)
    kind = kind_match.group(1).strip() if kind_match else None

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paragraph in _paragraphs(text):
        view = _VIEW_JOB.match(paragraph[-1])
        job_id = _JOB_ID.search(view.group(1)) if view else None
        if job_id is None or job_id.group(1) in seen:
            continue  # not a job block (header, section links, footer), or a repeat
        seen.add(job_id.group(1))
        records.append(_record(job_id.group(1), paragraph[:-1], kind, payload))
    return records


def _paragraphs(text: str) -> list[list[str]]:
    """Runs of non-blank lines; separator lines also end a run."""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and not _SEPARATOR.match(line):
            current.append(line)
        elif current:
            paragraphs.append(current)
            current = []
    if current:
        paragraphs.append(current)
    return paragraphs


def _record(job_id: str, lines: list[str], kind: str | None, payload: RawPayload) -> dict[str, Any]:
    urls = [i for i, line in enumerate(lines) if line.startswith(("http://", "https://"))]
    if urls:  # a section heading and its link ran into the job block: keep what follows
        lines = lines[urls[-1] + 1 :]
    fields = [line for line in lines if line not in KNOWN_BADGES]
    badges = [line for line in lines if line in KNOWN_BADGES] + fields[3:]

    record: dict[str, Any] = {
        "external_id": job_id,
        "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
        "description": "",
        "locations": [],
        "location_raw": None,
        "workplace": "unknown",
        "employment_type": "unknown",
        "seniority": "unknown",
        "tags": [],
        "collected_at": payload.fetched_at.isoformat(),
        "extra": {"email_kind": kind, "badges": badges},
    }
    if fields:
        record["title"] = fields[0]
    if len(fields) > 1:
        record["company"] = fields[1]
    if len(fields) > 2:
        locations, workplace = parse_location(fields[2])
        record.update(locations=locations, location_raw=fields[2], workplace=workplace)
    record["language"] = detect_language(record.get("title", ""))
    return record


def parse_location(text: str) -> tuple[list[dict[str, str]], str]:
    """LinkedIn location text -> (locations, workplace). Reports only what the text states:
    a trailing country name becomes its code; nothing is inferred from city names."""
    workplace = "unknown"
    suffix = _WORKPLACE.search(text)
    if suffix:
        workplace = _WORKPLACES[suffix.group(1).lower()]
        text = text[: suffix.start()].strip()
    if text.lower() == "remote":
        return [], "remote"
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return [], workplace
    location: dict[str, str] = {}
    if parts[-1].lower() in COUNTRY_NAMES:
        location["country"] = COUNTRY_NAMES[parts.pop().lower()]
    if len(parts) == 1 and parts[0].endswith((" Region", " Area")):
        location["region"] = parts[0]
    elif parts:
        location["city"] = parts[0]
        if len(parts) > 1:
            location["region"] = parts[1]
    return [location], workplace
