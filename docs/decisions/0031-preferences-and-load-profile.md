# 0031: preferences.yaml version 1 and load_profile

Date: 2026-10-20
Spec: [06-profile](../spec/06-profile.md), P4, P7; plan [06](../plans/06-profile.md) task 3

## Implementation

- `jobhunt.profile.preferences.Preferences` (frozen, unknown keys rejected):
  - `candidate` (location, IANA timezone);
  - `looking_for` (at most 1,000 characters);
  - `targets` (roles, role keywords, seniority from the job schema's enum, years);
  - `markets` in priority order (country, region and workplace values validated with the job schema's types; unique names);
  - `filters` (remote eligibility, excluded companies and keywords, `minimum_salary` per currency and period, unique per pair, amount > 0);
  - `languages` (postings: non-empty if present; outputs).
- Missing file or sections mean defaults: no language filter, UTC, no markets or filters, matching the old behaviour.
- `accepted_languages` and `timezone` properties replace the old `jobhunt.preferences` module, which was removed. Collection and the digest now read through `load_preferences` (P7); their tests moved to `tests/profile/test_preferences.py`.
- `jobhunt.profile.load.load_profile(config_dir)` returns `Profile(master_cv | None, preferences, aliases)` with `issues()` (fact skills by name or alias) and `warnings()`.
- `config/preferences.sample.yaml` (fictional) and `schemas/preferences.v1.json` committed with the drift check.

## Order change: the user's preferences converted in this task

Plan 06 put converting the real files in task 5. The real `preferences.yaml` used a draft key (`remote_regions_ok`) that the strict model rejects, so switching collection and the digest to it first would have broken the next scheduled run (12:00). The preferences file was therefore converted here:
- a backup was saved as `~/.config/jobhunt/preferences.pre-v1.yaml` (mode 600);
- `remote_regions_ok` → `regions`, the header comment updated;
- empty `excluded_companies`, `excluded_keywords`, `minimum_salary` and a commented `looking_for` were added for the user to fill in.

All existing values are unchanged. The master CV is only read by later specs, so it stays in task 5.

## Verified

- Tests written first (18 new; 490 in total); `make check` passes.
- The converted real file validates (4 markets, languages vi/en, Asia/Ho_Chi_Minh). With the real config, `jobhunt collect email --dry-run --since 1d` and `jobhunt digest list --since 30d` both exit 0 (19 postings listed), so the timer's next run is unaffected.
- No new dependencies, cost $0.
