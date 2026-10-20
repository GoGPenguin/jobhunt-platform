# Plan 02A: Email sources (Gmail, LinkedIn)

Spec: [02-source-framework](../spec/02-source-framework.md), phase A
Status: done 2026-10-20 (tasks 1–7 and the manual IMAP check; decision records 0009–0015)

## Goal

`jobhunt collect email --since 3d` reads the Gmail alert label read-only, parses LinkedIn alert emails into canonical jobs, and prints jobs, dead letters and counts as JSON lines. No storage yet (dedupe-store), no HTTP requests at all.

## Decisions for this phase (asked 2026-10-20)

| Question | Answer |
| -------- | ------ |
| Raw emails contain sign-in-capable LinkedIn tokens and the user's name | Strip token and tracking query parameters from every link before a raw payload leaves the transport; keep everything else, so parsers can be re-run. |
| Config format | YAML with PyYAML (also needed for the profile files). |
| What Phase A produces | A CLI dry run printing JSON lines. "Only new mail" and storage come with dedupe-store. |
| ITviec | Not followed for now; its parser moves to phase C with the other platforms, once samples exist. |

## What the samples showed

Two LinkedIn emails ("New jobs similar to …", "… is hiring for a Remote role"):

- The `text/plain` part has a stable block layout: title, company, location, optional badge lines ("Apply with resume & profile"), `View job: <link>`, separator. The parser reads the plain-text part, so **no HTML library is needed for LinkedIn**.
- Job links look like `https://www.linkedin.com/comm/jobs/view/<id>/?…otpToken=…`. The job id becomes `external_id`; the URL is rebuilt as `https://www.linkedin.com/jobs/view/<id>/`, so no token or tracking parameter reaches a job.
- The same job can appear in two sections of one email; the parser keeps it once.
- The first line of a "similar jobs" email names the job *viewed*, not a new one; it is skipped.
- The footer names the recipient; it is removed from fixtures.

## Dependencies (for approval)

| Package | Kind | Why |
| ------- | ---- | --- |
| `pyyaml` | runtime | read `sources.yaml` and `preferences.yaml` (`safe_load` only) |
| `types-pyyaml` | dev | type stubs so `mypy --strict` checks YAML-reading code |

Standard library for everything else: `imaplib`, `email`, `argparse`, `logging`. No HTML library: that choice moves to phase C, once an email that needs it exists.

## Tasks

Each task is test-first, ends with `make check` passing, and adds a decision note.

1. **Config.** PyYAML; `SourcesConfig` model for the `email` section (IMAP host and label, email sources with `id`, `parser`, `from` sender domains, `page_fetch` and `reason`); clear errors naming the bad entry; rejects unknown parser, duplicate id, invalid slug, `page_fetch: allowed` for a LinkedIn sender. `config/sources.sample.yaml` (fictional); `schemas/sources.v1.json` with drift check. Reads `languages.postings` from `preferences.yaml` for the language filter. Covers F1 (email part).
2. **Raw payloads and redaction.** `RawPayload` (bytes, content type, origin such as Message-ID, fetched-at, `raw_ref`); `redact_links()` removes token and tracking parameters (`otpToken`, `midToken`, `midSig`, `eid`, `trk*`, `lipi`, `refId`, `trackingId`, `utm_*`, …) from every URL in an email's text and HTML parts. Parser registry: parsers registered by name and semver version.
3. **Secrets.** Read `JOBHUNT_IMAP_USER` and `JOBHUNT_IMAP_APP_PASSWORD` from the environment, or from `~/.config/jobhunt/secrets.env` (refuses to read it if group/other can read it). A logging filter masks secret values. Covers F11.
4. **IMAP transport.** A small port (interface) with an `imaplib` adapter: TLS login, `EXAMINE` the label (read-only), `UID SEARCH SINCE`, `UID FETCH BODY.PEEK[]`, redact, return raw payloads keyed by Message-ID. Tested against a fake that records commands and fails on anything that writes (`SELECT`, `STORE`, `COPY`, `MOVE`, `EXPUNGE`). Covers F4.
5. **Routing.** Sender domain → email source; unknown senders counted and skipped. Covers F5.
6. **LinkedIn parser + golden tests.** Plain-text block parser: title, company, location (`location_raw` kept; a country name such as "Vietnam" becomes `country: VN`, otherwise `city`), workplace from a "(Remote)"/"(Hybrid)"/"(On-site)" suffix if present, badges and email kind into `extra`, language detected from the title (mostly `unknown`, as decided). Golden-test harness auto-discovering `tests/fixtures/sources/<parser>/<case>/`. Two sanitized fixtures from the samples. **Fixture privacy scan:** fails on any token parameter, any email address outside an allow-list, and any string listed in a private `~/.config/jobhunt/privacy-scan.txt` (your name, address; skipped in CI where that file doesn't exist). Covers F6 for LinkedIn.
7. **CLI.** `jobhunt collect email --since 3d` (entry point in `pyproject.toml`) and `make collect-email`; JSON lines for jobs and dead letters, a summary line (emails read, jobs, dead letters, dropped languages, unrouted senders). Unit-tested with the fake IMAP client. **Manual check:** you run it once against your real Gmail label and we compare the output with the emails.

## Setup you'll need for task 7

1. In Gmail settings, enable IMAP.
2. Create a filter that applies label `jobhunt` to mail from `jobs-noreply@linkedin.com`.
3. Create an app password (Google Account → Security → 2-Step Verification → App passwords).
4. Put both in `~/.config/jobhunt/secrets.env` with `chmod 600`.

## Risks

- **LinkedIn changes its email layout.** The golden tests pin today's layout; a change shows up as zero jobs or dead letters, which the later drift alert catches.
- **The app password can read the whole mailbox.** Mitigated by read-only commands enforced in the adapter and tested, label-only access, and the file-permission check. Revocable at any time.
- **Other LinkedIn email kinds** (saved-search "job alert" emails) may use a different layout. A sample of one is needed before relying on them.
