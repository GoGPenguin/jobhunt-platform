# Spec 02: Source framework

Status: approved 2026-10-20, delivered in phases (below)
Depends on: [constitution](constitution.md), [01-canonical-job-schema](01-canonical-job-schema.md)
Used by: collector-runtime, dedupe-store, notifications

## User story

As the job seeker, I want jobs from my alert emails and from the career pages of companies I follow turned into canonical jobs automatically, with as much detail as each source legitimately allows, so that I see every relevant Vietnam/Asia job in one place without checking each site.

## Scope

In scope:

- The source model (transport + parser + policy + schedule) and the `sources.yaml` format, validated in CI.
- A parser plugin registry.
- Transports: `imap_email` (read-only, one Gmail label), `http_json` (ATS job-board APIs), `html_page` (one public job page, to fill in descriptions).
- Company-board parsers: Greenhouse, Lever, Ashby. Adding a company is one line of YAML.
- Alert-email parsers for ITviec, LinkedIn, TopCV, VietnamWorks, TopDev, Glints, JobStreet, one plugin each.
- Description enrichment for jobs that arrive without a description: page fetch where allowed, company-posting lookup where not, manual paste as the last resort.
- Politeness: User-Agent, per-host rate limit, robots.txt, HTTP caching, a hard LinkedIn deny rule.

Out of scope, covered by later specs:

- Scheduling and running sources as jobs (collector-runtime). This spec defines `schedule` but does not run it.
- Raw payload storage, dead-letter storage, cross-source matching (dedupe-store). This spec produces raw payloads and `build_jobs` results; the "known boards" step of the company-posting lookup is a dedupe-store query.
- The Telegram side of manual paste and "add this board?" prompts (notifications).
- LLM extraction for unknown email formats, search APIs (tier 4), and remote-job boards (tier 2): later specs.

## Delivery phases

The spec is delivered in four phases, each with its own plan. Phase A comes first by the user's choice: alert emails are the main source.

| Phase | Delivers | Acceptance criteria |
| ----- | -------- | ------------------- |
| A | Framework core (source model, `sources.yaml` + schema, parser registry, secrets loading), `imap_email` transport for the Gmail label, LinkedIn and ITviec email parsers | F1, F4, F5, F6 (LinkedIn, ITviec), F11 |
| B | `http_json` transport, politeness layer with the LinkedIn hard deny, Greenhouse, Lever and Ashby families | F2, F3, F7, F8 |
| C | TopCV, VietnamWorks, TopDev, Glints, JobStreet email parsers | F6 (rest) |
| D | Description enrichment: `html_page`, page parsers, ATS probe, manual paste | F9, F10 |

Phase A makes no HTTP requests at all: links in alert emails are parsed, never followed. The overview's MVP criteria AC1 and AC3 also need a company-board family, so the MVP is complete after phase B.

## Decisions (2026-10-20)

| Topic | Decision |
| ----- | -------- |
| Mailbox | The main Gmail account; a Gmail filter puts alert emails under one label, and only that label is read over IMAP with an app password. The password can technically read the whole mailbox, so the transport only issues read-only commands, only opens the configured label, and the password lives in `~/.config/jobhunt/secrets.env` (chmod 600), revocable from the Google account at any time. |
| Alert platforms | ITviec, LinkedIn, TopCV, VietnamWorks, TopDev, Glints, JobStreet. |
| Email parsing | One plugin per platform, each with a golden test on a sanitized sample email. No LLM. |
| `sources.yaml` | Private at `~/.config/jobhunt/sources.yaml` (it reveals target companies). The repo ships `config/sources.sample.yaml` with fictional companies, used by tests and CI. |
| Company boards | Greenhouse, Lever, Ashby. |
| LinkedIn detail | (1) everything in the alert email; (2) the company's own posting (known boards, then an ATS probe); (3) the user opens the LinkedIn link and pastes the description. No automated LinkedIn access: LinkedIn's robots.txt disallows all automated clients (checked 2026-10-20). |
| Page fetch per platform | robots.txt checked 2026-10-20. Allowed for job pages: ITviec, TopCV, VietnamWorks, TopDev, Glints. Not allowed: LinkedIn (all automated access prohibited), JobStreet (regional sites disagree; my.jobstreet.com disallows `/job/`, jobstreet.vn blocks the crawler). JobStreet follows the LinkedIn path. Terms of service are reviewed per platform before its page parser is enabled, and recorded in `docs/decisions/`. |
| Secrets (Compose phase) | `~/.config/jobhunt/secrets.env`, loaded as environment variables; moved to SOPS / External Secrets in the Kubernetes phase. |

## Concepts

**Source:** one place jobs come from. It has:

- `id`: slug, unique (e.g. `itviec-email`, `greenhouse:lumen-robotics`).
- `transport`: how raw payloads are fetched, with its settings.
- `parser`: name of a registered parser plugin.
- `policy`: politeness and permissions (below).
- `schedule`: a cron expression, used by collector-runtime.
- `enabled`: on or off without deleting the entry.

**Family:** a template that expands to many sources. `greenhouse`, `lever` and `ashby` list board names; each name becomes a source `<family>:<board>` with the family's transport, parser and policy.

**Policy:** `user_agent` (default `jobhunt-platform/<version> (+https://github.com/GoGPenguin/jobhunt-platform)`), `min_interval_seconds` per host (default 5), `max_requests_per_run`, `respect_robots` (always true; not configurable off), `page_fetch: allowed | forbidden` with a `reason`, `allow_http` (default false), `attribution` (text and URL when the terms require it).

**Raw payload:** what a transport returns before parsing: bytes, content type, the URL or Message-ID it came from, and fetch time. It gets a `raw_ref` and is stored before parsing (dedupe-store), so parsers can be re-run.

**Parser plugin:** a function from one raw payload to a list of records (dicts in the canonical job shape, without `source`, `parser`, `raw_ref`, which `build_jobs` adds). Registered by name with a version (semver). Bumping a parser's version is required whenever its output changes.

## `sources.yaml` (sample shape)

```yaml
schema_version: 1
defaults:
  policy: { min_interval_seconds: 5, max_requests_per_run: 200 }
  accepted_languages_from: preferences   # posting-language filter from preferences.yaml

email:
  imap: { host: imap.gmail.com, label: jobhunt }  # credentials come from secrets.env
  sources:
    - { id: itviec-email,   parser: itviec-email,   from: ["@itviec.com"],   page_fetch: allowed }
    - { id: linkedin-email, parser: linkedin-email, from: ["@linkedin.com"], page_fetch: forbidden,
        reason: "LinkedIn prohibits automated access" }

families:
  greenhouse: { schedule: "0 */6 * * *", boards: [lumen-robotics, northwind-cloud] }
  lever:      { schedule: "0 */6 * * *", boards: [] }
  ashby:      { schedule: "0 */6 * * *", boards: [] }
```

The exact format is finalized in the plan. It is validated by a Pydantic model whose JSON Schema is committed as `schemas/sources.v1.json`, with the same drift check as the job schemas.

## Flows

**Company board:** `http_json` fetches the board's public API → raw payload → family parser → `build_jobs` (language filter from preferences) → jobs + dead letters.

**Alert email:** `imap_email` lists messages under the label since the last run (read-only) → one raw payload per message, keyed by Message-ID so re-runs are idempotent → routed to a parser by sender domain → `build_jobs`. Mail from an unrouted sender is counted and skipped, never parsed by a guess.

**Description enrichment** (jobs with an empty description):

1. Page fetch allowed: `html_page` fetches the job URL (policy and robots.txt applied) → platform page parser → re-parsed job, language filter applied again.
2. Page fetch forbidden (LinkedIn, JobStreet):
   1. Known boards: ask dedupe-store whether a job from an already-collected board matches (same company, similar title).
   2. ATS probe: derive board-name candidates from the company name (e.g. "Lumen Robotics Pte. Ltd." → `lumenrobotics`, `lumen-robotics`), query each of Greenhouse, Lever, Ashby (at most 6 requests per company, results cached for 30 days), and look for a matching title. If found, use its description and suggest adding that board to `sources.yaml`.
   3. Otherwise mark the job as "description needed" for the notifications spec, which sends the link and accepts a pasted description. A pasted description becomes a raw payload with source `manual` and is re-parsed.

## Rules

- **LinkedIn hard deny.** No transport ever requests a `linkedin.com` host (or `lnkd.in`), whatever the config says. Links in LinkedIn emails are parsed, never followed. This is a code-level guard, because a config mistake must not be able to break the rule.
- **Tracking links in emails** are resolved without a request when the target is encoded in the link. Otherwise they are followed with a single `HEAD` request, only for platforms whose page fetch is allowed.
- **Read-only mail.** The IMAP transport opens the label with `EXAMINE` and fetches with `BODY.PEEK[]`, so messages are never marked read, moved or deleted.
- **Secrets** are read from the environment (`JOBHUNT_IMAP_USER`, `JOBHUNT_IMAP_APP_PASSWORD`), never logged, and never included in raw payloads, errors or dead letters.
- **Fixtures are sanitized.** Sample emails committed as test fixtures have the recipient's name, address, unsubscribe and tracking tokens replaced. A test scans all fixtures for the real email address and name and fails if found.

## Acceptance criteria

- **F1:** `config/sources.sample.yaml` validates; configs with an unknown parser, a duplicate id, an invalid slug, or `page_fetch: allowed` on a LinkedIn source are rejected with an error naming the entry. CI validates the sample and checks `schemas/sources.v1.json` for drift.
- **F2 (MVP AC3):** adding one Greenhouse board line plus a recorded API response fixture passes CI schema validation and its golden test without any code change.
- **F3:** Greenhouse, Lever and Ashby parsers turn recorded API responses into jobs (golden tests). Greenhouse's double-escaped HTML is unescaped before `html_to_text`.
- **F4:** the IMAP transport, run against a fake server, issues only read-only commands, opens only the configured label, and returns each message once across repeated runs.
- **F5:** emails are routed by sender; an unknown sender is counted and skipped without error.
- **F6:** each alert-email parser has a golden test from a sanitized sample email; the fixture scan finds no personal data.
- **F7:** politeness: the configured User-Agent is sent, requests to one host are spaced by `min_interval_seconds`, a URL disallowed by robots.txt is never fetched, and conditional requests (`ETag` / `If-Modified-Since`) are used where the server supports them.
- **F8:** no request to `linkedin.com` or `lnkd.in` is possible, even with a config that asks for one.
- **F9:** the ATS probe finds a fictional company's job on a fake Greenhouse board, stays within 6 requests, and returns "not found" cleanly otherwise.
- **F10:** a job without a description from an allowed platform is enriched via its page and re-checked by the language filter; a pasted description re-processes a LinkedIn job.
- **F11:** the IMAP password never appears in logs, errors or dead letters (tested by injecting a known fake password).

## Edge cases

| Case | Expected handling |
| ---- | ----------------- |
| One alert email lists 10 jobs | One raw payload, 10 records, one `raw_ref`. |
| The same job arrives by email from two platforms | Two records here; merged by dedupe-store. |
| Platform changes its email layout | Parser yields dead letters or zero jobs; the drift alert (observability spec) fires; fix the parser and bump its version. |
| Board name no longer exists (404) | Source reports "board gone"; no jobs, no crash; flagged in the run summary. |
| robots.txt unreachable | Treat as disallowed for that run (fail closed). |
| HTTP 429 or 5xx | Back off exponentially, respect `Retry-After`, give up for this run after 3 tries. |
| Company name with Vietnamese diacritics ("Công ty TNHH Phần mềm Sông Hàn") | Probe candidates are built from an ASCII-folded name, with legal suffixes (TNHH, JSC, Pte. Ltd., Inc.) removed. |
| Email is a digest with no job links (newsletter, promo) | Parser returns no records; counted as "no jobs", not an error. |

## Dependencies

These need approval and are chosen in the plan:

- **PyYAML**, to read `sources.yaml` and the profile files. Required; there is no YAML parser in the standard library.
- **An HTML parsing library** for alert emails and job pages (e.g. `selectolax` or `beautifulsoup4`). Email HTML is table-heavy, and selector-based extraction is much more robust than the built-in parser.
- **HTTP client:** standard-library `urllib` or `httpx`.

Standard library, no approval needed: `imaplib`, `email`, `urllib.robotparser`.

## Test plan

- Golden tests per parser, auto-discovered from `tests/fixtures/sources/<parser>/<case>/` (`input.*` plus `expected.json`), regenerated with a make target and reviewed as a diff.
- Transports tested against fakes (fake IMAP server, fake HTTP server); no test touches the network.
- Config validation tests (F1), politeness tests (F7, F8), and the secret-redaction test (F11).
- Fixture privacy scan (F6).

## Inputs needed

Real alert emails, 1–2 per platform, as raw `.eml` files (Gmail: open the email → ⋮ → "Download message"), kept in `~/.config/jobhunt/samples/` (private). Sanitized copies become fixtures; the originals never enter the repo. Each email parser is blocked until its platform's samples exist.
