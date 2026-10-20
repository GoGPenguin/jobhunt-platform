# Spec 01: Canonical job schema

Status: approved 2026-10-20
Depends on: [constitution](constitution.md)
Used by: source-framework, collector-runtime, dedupe-store, notifications, matcher, job-summary, tailor-validator

## User story

As the job seeker, I want every job, from any source, converted into one consistent shape, so that deduplication, ranking, notifications and tailoring work the same way no matter where the job came from.

## Scope

In scope: the `Job` model (version 1), its field rules, text and URL normalization, how invalid records are reported, and how the schema changes over time.

Out of scope, covered by later specs:

- Source configuration format and parsers (source-framework).
- Database tables, raw payload store, dead-letter table, job open/closed lifecycle (dedupe-store).
- Anything inferred about a job, such as seniority from the title, skills from the description, fit scores (matcher).

## Design rules

1. **Parsers report, they don't guess.** A field is set only if the source states it. Anything not stated is `None` or `unknown`. Inference happens later in the matcher and is stored separately, so the canonical record always reflects the source. This is the anti-corruption layer between messy sources and the rest of the system.
2. **Identity is `(source, external_id)`.** It is unique and stable across runs. Duplicates *across* sources are the dedupe-store's job.
3. **Raw first.** Every `Job` points to the raw payload it was parsed from (`raw_ref`) and records the parser name and version, so any job can be re-parsed after a parser fix.
4. **Immutable.** A `Job` is frozen once built. Changes come from re-parsing, not editing.
5. **Source-specific data goes in `extra`.** Fields that only one source has go in a JSON bag instead of growing the schema.

## Fields (version 1)

| Field | Type | Required | Rules |
| ----- | ---- | -------- | ----- |
| `schema_version` | int | yes | Always `1` for this version. |
| `source` | str | yes | Source id from config, e.g. `remotive`, `greenhouse:gitlab`. Lowercase, `[a-z0-9:_-]`. |
| `external_id` | str | yes | The source's own job id. If the source has none, the SHA-256 of the normalized `url`; the source config must say which. |
| `url` | URL | yes | Public posting or apply page, normalized (see below). |
| `title` | str | yes | 1–300 characters after normalization. |
| `company` | str | yes | Display name as the source states it, 1–200 characters. |
| `description` | str | yes | Plain text converted from HTML, paragraphs and list items kept as line breaks. Maximum 50,000 characters. May be empty when the source gives none (e.g. job-alert emails); a later step fetches the public job page to fill it in before matching. |
| `description_truncated` | bool | yes | `true` if `description` was cut to the limit. |
| `language` | str | yes | ISO 639-1 language of the posting (`en`, `vi`, `ja`…), or `unknown`. Decides whether a Vietnamese CV is offered. |
| `locations` | list[Location] | yes | May be empty. See Location. |
| `location_raw` | str \| None | no | Location text exactly as the source gave it, kept when it can't be fully parsed (e.g. "Remote – APAC only"). |
| `workplace` | enum | yes | `onsite`, `hybrid`, `remote`, `unknown`. |
| `remote_regions` | list[str] \| None | no | Where remote candidates may live, as stated by the source. Each entry is an ISO 3166-1 alpha-2 country code or a region label (uppercase letters, digits and `_`, e.g. `WORLDWIDE`, `APAC`, `EU`, `LATAM`). The list of labels is open: the schema checks the format only, and what each region covers is configuration, not code. `None` means not stated. Used to drop jobs the candidate can't take from where they live (per the profile). |
| `employment_type` | enum | yes | `full_time`, `part_time`, `contract`, `internship`, `temporary`, `unknown`. |
| `seniority` | enum | yes | `intern`, `junior`, `mid`, `senior`, `lead`, `staff_plus`, `unknown`. Only when the source states it as structured data, not parsed from the title. |
| `years_experience_min` / `_max` | int \| None | no | Only when the posting states a number. 0–30, min ≤ max. |
| `salary` | Salary \| None | no | See Salary. |
| `visa_sponsorship` | bool \| None | no | Only when stated. |
| `relocation_support` | bool \| None | no | Only when stated. |
| `tags` | list[str] | yes | Tags the source provides (e.g. Remotive categories), lowercased, deduplicated. May be empty. |
| `posted_at` | datetime \| None | no | UTC. A date without a time becomes 00:00 UTC. |
| `expires_at` | datetime \| None | no | UTC, only when stated. |
| `collected_at` | datetime | yes | UTC time the collector fetched the raw payload. |
| `attribution` | Attribution \| None | no | Required when the source's terms require credit. |
| `raw_ref` | str | yes | Id of the raw payload record this job was parsed from. |
| `parser` | ParserInfo | yes | `name` and `version` of the parser that produced the record. |
| `extra` | dict[str, JSON] | yes | Source-specific data. May be empty. Never read by core logic without a spec change. |

**Location:** `city: str | None`, `region: str | None`, `country: str | None` (ISO 3166-1 alpha-2). At least one must be set.

**Salary:** `min: Decimal | None`, `max: Decimal | None` (at least one set, min ≤ max, both ≥ 0), `currency` (ISO 4217, e.g. `USD`, `VND`, `JPY`), `period` (`year`, `month`, `week`, `day`, `hour`, `unknown`), `basis` (`gross`, `net`, `unknown`). `basis` matters because Vietnamese postings often state net monthly salary.

**Attribution:** `text: str`, `url: URL`. Shown wherever the job is shown, including the Telegram digest.

**ParserInfo:** `name: str`, `version: str` (semver).

## Normalization

Applied by the model, so every parser gets it for free:

- **Text:** Unicode NFC, so Vietnamese diacritics compare equal however they were encoded. Title and company have whitespace collapsed and trimmed.
- **URL:** scheme and host lowercased, fragment removed, tracking parameters removed (`utm_*`, `gclid`, `fbclid`, `ref`, `source`), remaining query parameters sorted. HTTPS only, except where a source's config explicitly allows HTTP.
- **HTML to text:** scripts and styles removed, block elements and list items become line breaks, entities decoded, more than two blank lines collapsed.
- **Datetimes:** must carry a timezone and are converted to UTC. A naive datetime is rejected, because guessing the timezone could shift posting dates by up to a day.

## Validation and invalid records

- Building a `Job` from invalid data raises a validation error listing every failing field, not just the first.
- `posted_at` later than `collected_at` + 1 day is invalid (a sign of a parsing bug).
- The parser layer turns a validation error into a dead-letter result containing `source`, `raw_ref`, `parser`, the field errors and the time. The result format is defined here; where it is stored is the dedupe-store's job. One bad record never stops the rest of a batch.

## Versioning

- Adding an optional field, or a new enum value, keeps `schema_version` at 1.
- **Strict on parse, lenient on read.** Building a job from parser output rejects unknown fields and unknown enum values, so parser bugs become dead letters. Loading a stored job ignores unknown fields and maps unknown enum values to `unknown`, so older code keeps working on data written by newer code (e.g. during a canary rollout).
- Removing or renaming a field, or changing a field's meaning, means version 2: a spec change, a database migration and a re-parse from the raw store.
- The JSON Schema is exported from the model and committed as `schemas/job.v1.json`. CI fails if the committed file differs from the model, so every schema change shows up in review.

## Acceptance criteria

- **S1:** A valid record for each of the three fixture jobs builds a `Job`, and `mypy --strict` passes on the model and tests.
- **S2:** A record with several invalid fields (missing title, currency `XYZ`, country `Vietnam` instead of `VN`, naive `posted_at`) fails with an error that names all four fields.
- **S3:** The normalization rules above each have a test with input and expected output, including a Vietnamese title with decomposed diacritics and a URL carrying `utm_source` and a fragment.
- **S4:** A `Job` round-trips through JSON (serialize, then parse) to an equal object, and attempting to change a field after building fails.
- **S5:** `schemas/job.v1.json` is generated from the model, committed, and a CI check fails when it is stale.
- **S6:** An invalid record in a batch of three produces one dead-letter result and two valid jobs.

## Edge cases

| Case | Expected handling |
| ---- | ----------------- |
| Source has no job id | `external_id` = SHA-256 of normalized URL, declared in source config. |
| Same job reposted with a new id | Two records here; merged by dedupe-store. |
| Several locations (e.g. "Singapore or Tokyo") | Multiple `Location` entries. |
| "Remote, APAC only" | `workplace: remote`, `remote_regions: ["APAC"]`, `location_raw` kept. |
| Region label not seen before (e.g. "Remote – LATAM") | `remote_regions: ["LATAM"]`; accepted as long as the format is valid. |
| Job-alert email with no description | `description: ""`; the job is stored and its public page is fetched later. |
| "Remote" with no region stated | `remote_regions: None` (unknown), not `WORLDWIDE`. |
| Salary "15–25 triệu net/month" | Parser converts to `min: 15000000, max: 25000000, currency: VND, period: month, basis: net`. |
| Salary "Competitive" or "Negotiable" | `salary: None`. |
| Only a date, no time | 00:00 UTC on that date. |
| Description longer than 50,000 characters | Cut at the limit, `description_truncated: true`. |
| Japanese or Vietnamese posting | `language` set from the source if stated, otherwise detected; detection is the only inference allowed here, because it describes the text itself, not the job. |

## Test plan

- **Unit tests** for each field rule, each normalization rule and each error case above.
- **Fixtures:** three hand-written jobs in `tests/fixtures/jobs/`: an English Greenhouse-style posting, a remote-board posting with attribution and `remote_regions`, and a Vietnamese posting with a net monthly VND salary. Hand-written so no real postings or personal data enter the repo.
- **Schema drift check** in CI (S5).
- **Type check:** `mypy --strict` over the model package.

## Decisions

Added during task 4 (2026-10-20): empty descriptions allowed, strict-on-parse / lenient-on-read, salary periods `week`, `day`, `unknown`.

1. **Regions are open.** Any well-formed region label is accepted; region definitions live in configuration.
2. **Code lists are bundled.** Country, currency and language codes ship as small lists in the repo. No new dependency.
3. **HTML-to-text and language detection** are decided in the implementation plan, which names any new dependency for approval.
