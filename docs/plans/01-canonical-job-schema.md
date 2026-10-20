# Plan 01: Canonical job schema

Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md)
Status: approved 2026-10-20

## Layout

One Python project for all services, so every component shares the same domain models. Each service (collector, matcher…) will be a separate entrypoint of the same package and image.

```text
apps/jobhunt/
  pyproject.toml            uv project, Python 3.12
  src/jobhunt/
    domain/
      job.py                Job, Location, Salary, Attribution, ParserInfo, enums
      normalize.py          text, URL, datetime and HTML-to-text normalizers
      language.py           language detection helper
      dead_letter.py        DeadLetter result and batch builder
      codes/                bundled ISO 3166-1, ISO 4217, ISO 639-1 lists
    tools/
      export_schema.py      writes or checks schemas/job.v1.json
  tests/
    fixtures/jobs/          three hand-written job fixtures
schemas/job.v1.json         generated, committed
Makefile                    test, lint, typecheck, schema, check
.github/workflows/ci.yaml
```

`schemas/` sits at the repo root because it is a contract for everything, not only Python code.

## Dependencies

| Package | Kind | Status |
| ------- | ---- | ------ |
| pydantic (v2) | runtime | approved in constitution |
| pytest, mypy, ruff | dev | approved |
| uv | tool | approved |

**No new dependencies.** The two choices the spec left to this plan:

- **HTML to text:** a small converter on Python's built-in `html.parser`. Job descriptions are simple markup (paragraphs, lists, bold, links), so a full HTML library isn't needed. If real sources break it later, adding `selectolax` would be a separate approval.
- **Language detection:** a built-in heuristic, no library:
  - Vietnamese: letters only Vietnamese uses (ơ, ư, đ, ă and tone marks).
  - Japanese, Chinese, Korean: Unicode script ranges.
  - English, German, Dutch, French, Spanish: share of common words from small bundled stopword lists.
  - Anything below a confidence threshold: `unknown`.

  The schema allows `unknown`, so a wrong guess is never forced. A library such as `lingua` (accurate but large) can be proposed later if `unknown` turns out to be too common.

## Tasks

Each task is test-first, ends with `make check` passing, and adds a note to `docs/decisions/` saying what was verified.

1. **Scaffold.** uv project, `pyproject.toml` (ruff, mypy strict, pytest config), `.gitignore`, `Makefile` with `test`, `lint`, `typecheck`, `check`, one smoke test. Done when `make check` passes on an empty package.
2. **Code lists.** Bundled country, currency and language codes with their source and date in a header comment. Tests: known members (`VN`, `VND`, `vi`), known non-members (`Vietnam`, `XYZ`), list sizes.
3. **Normalizers.** Text (NFC, whitespace), URL (tracking parameters, fragment, sorted query, HTTPS rule), datetime (timezone required, UTC), HTML to text. Covers S3, including decomposed Vietnamese diacritics and a `utm_source` URL.
4. **Job model.** All fields and sub-models from the spec, frozen, with validators. Three fixtures. Covers S1, S2 (all four errors reported at once) and S4 (JSON round-trip, immutability).
5. **Language detection.** Heuristic plus tests on short and long English, Vietnamese, Japanese and German samples, and mixed text that should return `unknown`.
6. **Dead letters.** `DeadLetter` result and `build_jobs(records)` that returns valid jobs and dead letters without stopping on errors. Covers S6.
7. **Schema export.** `make schema` writes `schemas/job.v1.json`; `make check` fails if it is stale. Covers S5.
8. **CI.** GitHub Actions runs `make check` on every push and pull request, with uv caching and pinned action versions.

## Risks

- **Bundled code lists go stale.** ISO lists change rarely (a few codes per decade); the header comment records the date so it can be refreshed.
- **Heuristic language detection is weaker than a library.** Mitigated by allowing `unknown` and preferring the language the source states.
- **`make up` and `make down` in `CLAUDE.md` won't exist until Docker Compose arrives** in the collector-runtime work. Task 1 adds only the targets this spec needs.
