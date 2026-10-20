# 0014: LinkedIn alert-email parser, golden tests and fixture privacy scan

Date: 2026-10-20
Spec: [02-source-framework](../spec/02-source-framework.md), F6 (LinkedIn); plan [02A](../plans/02a-email-sources.md) task 6

## Decision asked and answered before coding

| Question | Answer |
| -------- | ------ |
| Public fixtures from real emails would show which job the user viewed and which companies LinkedIn recommends | Replace all job content with fictional values; keep LinkedIn's exact layout. |

The fixtures were written from scratch by a one-off script copying the layout seen in the two real samples (paragraph blocks, separators, section headings with search links, badges, a repeated job, the viewed-job header line, footer). No real email was edited into a fixture, so no real content can leak through a missed replacement.

## Parser (`linkedin-email` 1.0.0)

- Reads the `text/plain` part. A job is a paragraph whose last line is `View job: <link>`. Other paragraphs (viewed-job header, section links, footer) are ignored. A job id seen earlier in the same email is skipped: the first occurrence wins, including its badges.
- `external_id` is the numeric id; `url` is rebuilt as `https://www.linkedin.com/jobs/view/<id>/`.
- Lines are title, company, location, then badges. Known badges ("Apply with resume & profile", "Actively recruiting", …) are recognised anywhere, so a badge is never read as a location.
- **Location reports what the text states:**
  - a trailing country name becomes its ISO code ("Vietnam" → `VN`, "Singapore, Singapore" → city + `SG`);
  - "… Region" / "… Area" become a region;
  - a "(Remote)" / "(Hybrid)" / "(On-site)" suffix sets `workplace`;
  - nothing is inferred from a city name. "Đà Nang" stays a city without a country; the matcher decides markets later.
- Country names come from a new generated `COUNTRY_NAMES` map (ISO name, common and official names; 425 entries) in the bundled code lists.
- Language is detected from the title; short English titles are `unknown`, as decided for task 5 of plan 01.
- `extra`: `email_kind` (from the footer, e.g. "Viewed Jobs") and `badges`.

## Golden tests and privacy scan

- `tests/sources/test_golden.py` auto-discovers `tests/fixtures/sources/<parser>/<case>/input.*` and compares the full `build_jobs` result with `expected.json`; `make golden` rewrites them for review. A test fails if a registered parser has no golden case.
- `tests/test_fixture_privacy.py` scans every fixture (decoded email parts and headers included) for token parameters, email addresses outside example domains and `linkedin.com`, and the personal strings in the private `~/.config/jobhunt/privacy-scan.txt` (skipped where that file is absent, as in CI).

## Verified

- Unit tests written first (16); 309 tests in total; `make check` passes.
- Golden files reviewed by hand: 6 + 5 jobs, header line skipped, duplicate kept once, badge-only block has no location, hybrid/remote/on-site suffixes, `VN`/`SG`/`JP`, Vietnamese title → `vi`, clean URLs, `raw_ref` and `collected_at` set.
- **On the two real LinkedIn emails** (local only, not committed): 10 and 6 jobs, 0 dead letters, matching the emails exactly (the viewed job skipped, the two repeated jobs kept once).
- The privacy scan was checked to fail: a planted file with the user's address, a fake `otpToken` and a personal string failed all three checks, then was removed.
- No new dependencies, no secrets, cost $0.
