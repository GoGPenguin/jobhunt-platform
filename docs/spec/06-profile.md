# Spec 06: Profile (master CV and preferences)

Status: approved 2026-10-20
Depends on: [constitution](constitution.md), [01-canonical-job-schema](01-canonical-job-schema.md)
Used by: matcher (spec 07), job-summary, tailor-validator, notifications (timezone)

## User story

As the job seeker, I want my facts (master CV) and what I'm looking for (preferences) in two validated files, so that matching, summaries and tailored CVs all work from the same truthful source, and anyone can run their own copy by writing their own two files.

## Scope

In scope:

- The formats (version 1) of `master_cv.yaml` and `preferences.yaml`: Pydantic models, committed JSON Schemas, strict validation with errors naming the entry.
- `jobhunt/profile/skill_aliases.yaml` (in the package, so installed copies and images have it; not personal): alternative names for the same skill (constitution guardrail 3).
- `jobhunt profile check`: validates both files and reports warnings.
- Fictional sample profiles in the repo, used by tests and CI and covered by the fixture privacy scan.
- Converting the user's existing private files (drafted on 2026-10-20) to version 1, keeping all content.
- One `load_profile()` that the rest of the code uses. The current `load_accepted_languages` / `load_timezone` become accessors on it.

Out of scope: matching and ranking (spec 07), CV and cover letter generation and the fabrication validator (tailor-validator), and any LLM use.

## Decisions (2026-10-20)

| Topic | Decision |
| ----- | -------- |
| Skill strength | Optional `level` per skill: `core`, `working` or `familiar`, the user's own rating. Used only for ranking, never printed on a CV. Missing means `working`. |
| Filters | Excluded companies, excluded keywords, minimum salary. |
| Excluded keywords | Whole-word, case-insensitive. A matching job ranks last with "(excluded: …)", and is never dropped, because keywords misfire ("Sales" in "Salesforce Platform Engineer"). |
| Excluded companies | The job never reaches the digest. |
| Minimum salary | Jobs whose stated salary is below it rank last; jobs without a salary are kept. |
| Where filters apply | In the matcher, before the digest. Every job stays stored, and a changed filter applies at once to jobs already collected. |
| Free text | An optional `looking_for` paragraph (at most 1,000 characters) for the matcher's LLM step and job summaries. Never shown on a CV. |

## `master_cv.yaml` (version 1)

Facts about the candidate; the only source for generated CVs (constitution guardrail 2).

```yaml
schema_version: 1
profile:   { name, location, email, phone, linkedin, languages: [{ name, level, vi }] }
summary:   [ fact ]
skills:    [ { name, category, level: core|working|familiar } ]   # level optional
experience:
  - { id, company, title, title_vi, location, start: 2024-08, end: null,
      projects: [ { name, description, description_vi, facts: [ fact ] } ] }
certifications: [ { name, code, date: 2026-05 } ]
education: [ { institution, institution_vi, degree, degree_vi, location, start, end, gpa } ]

# fact = { id, en, vi, vi_reviewed, skills: [skill names], numbers: ["30–80%"] }
```

Validation rules:

- Fact ids are unique slugs across the file.
- Every skill a fact lists exists in `skills`, by name or by an alias from `skill_aliases.yaml` (case-insensitive).
- Every number a fact lists appears literally in its `en` text (and its `vi` text, when present). This is the base the fabrication validator relies on.
- Dates are `YYYY-MM`, and an end is not before its start.
- Unknown keys are rejected (typos surface).
- Warnings, not errors: facts with `vi_reviewed: false`, and an empty `linkedin`.

## `preferences.yaml` (version 1)

What the candidate is looking for. Nothing about a profession is hardcoded; everything comes from here (constitution guardrail 5).

```yaml
schema_version: 1
candidate: { location: { city, country }, timezone: Asia/Ho_Chi_Minh }
looking_for: >-               # optional, at most 1,000 characters
  ...
targets:
  roles: [ ... ]              # titles to match
  role_keywords: [ ... ]      # wider net for new titles in the same space
  seniority: [ junior, mid ]  # values from the job schema's Seniority enum
  years_experience_max: 4
markets:                      # in priority order: first = most preferred
  - { name, countries: [VN], regions: [], workplace: [onsite, hybrid, remote], prefer: "..." }
filters:
  drop_remote_outside_eligibility: true
  excluded_companies: [ ... ] # compared after normalize_company (spec 04)
  excluded_keywords: [ ... ]
  minimum_salary: [ { amount: 20000000, currency: VND, period: month } ]
languages: { postings: [vi, en], outputs: [en, vi] }
```

Validation rules:

- Country, currency and language codes from the bundled ISO lists.
- Region labels in the job schema's format.
- `seniority` and `workplace` values from the job schema's enums.
- An IANA timezone.
- Unique market names.
- Unknown keys are rejected.

## `skill_aliases.yaml` (inside the package)

```yaml
Kubernetes: [K8s]          # matching is case-insensitive
AWS EKS: [EKS, Amazon EKS]
GitLab CI/CD: [GitLab CI]
```

- An alias names **the same skill only**, never a broader or related one (constitution guardrail 3).
- An alias belongs to exactly one skill.
- The file is in the public repo and reviewed like code.

## `jobhunt profile check`

- Validates `master_cv.yaml`, `preferences.yaml` and the aliases from `--config-dir` (default `~/.config/jobhunt`).
- Prints errors and warnings that name the entry (`experience[0].projects[1].facts[2] (vizerp-ci-optimization).numbers: "30-80%" not found in en text`), never the personal values themselves. The CV is private, and the output may be pasted somewhere.
- Exits 0 when valid (warnings allowed) and 2 on any error.

## Acceptance criteria

- **P1:** the fictional sample profile validates in CI; the JSON Schemas `master_cv.v1.json`, `preferences.v1.json` and `skill_aliases.v1.json` are committed with the same drift check as the other schemas.
- **P2:** a fact listing a skill that isn't in `skills` (and isn't an alias of one) is rejected, naming the fact.
- **P3:** a fact listing a number that isn't in its text is rejected, naming the fact and the number.
- **P4:** duplicate fact ids, bad dates, unknown keys, invalid codes and invalid enum values are rejected with the entry named.
- **P5:** an alias claimed by two skills, or used as a skill name and as an alias, is rejected.
- **P6:** `profile check` on the user's converted real files exits 0, and lists the `vi_reviewed` warnings and the missing LinkedIn URL without printing personal values.
- **P7:** the rest of the code (collection's language filter, digest timezone) reads through `load_profile()`; the behaviour stays as before.
- **P8:** the samples pass the fixture privacy scan, which now also covers `config/`.

## Edge cases

| Case | Expected handling |
| ---- | ----------------- |
| No `preferences.yaml` | Defaults: no language filter, UTC, no filters, no targets; the matcher ranks by recency only. |
| No `master_cv.yaml` | `profile check` reports it missing; the matcher runs without skill matching. |
| A skill written as an alias in a fact ("K8s") | Accepted when the alias belongs to a listed skill; stored canonically by the matcher. |
| A number written differently ("30-80%" vs "30–80%") | Rejected: numbers must match literally, so the fact text and the number list stay in sync. |
| A Vietnamese text not reviewed yet | A warning, not an error; the tailor spec decides whether unreviewed texts may be used. |

## Dependencies

None new.

## Test plan

- Model tests for each rule above, using the fictional sample with one change per test.
- Schema drift tests for the three new schemas.
- `profile check` CLI tests: valid, warnings only, errors, and no personal values in the output.
- Converting the user's real files is a manual step, checked with `profile check` (P6).
