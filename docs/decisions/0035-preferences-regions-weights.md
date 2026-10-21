# 0035: Preferences: region overrides and scoring weights

Date: 2026-10-21
Spec: [07-matcher](../spec/07-matcher.md) (amends spec 06's preferences, still version 1), M7 validation part; plan [07](../plans/07-matcher.md) task 2

## Implementation

- `regions: {LABEL: [country codes]}`: labels in the job schema's region format (uppercase), at least one ISO country code each. They add to or redefine the bundled regions (`Regions.with_overrides`).
- `matching.weights`: `title`, `market`, `skills`, `seniority`, `experience`, each ≥ 0, defaults 30/25/20/15/10. Unlisted weights keep their default; unknown names are rejected; all-zero is rejected (the score is normalized by the total).
- The sample profile shows both: `SEA_HUBS: [SG, VN, TH]`, and `title: 35`. `schemas/preferences.v1.json` is regenerated.

## Verified

- Tests written first (8 new; 533 in total); `make check` passes.
- The user's real profile still validates (no `regions` or `matching` section means the defaults).
- No new dependencies, cost $0.
