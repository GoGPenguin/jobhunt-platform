# 0038: Digest ranked by fit

Date: 2026-10-21
Spec: [07-matcher](../spec/07-matcher.md), M9; plan [07](../plans/07-matcher.md) task 5

## Decision asked

- **A broken profile file in the daily run:** you chose "send anyway, with a warning". A missing digest is worse than an unranked one, and the warning says what to fix.

## Implementation

- `profile.load.load_profile_lenient(config_dir) -> (Profile, problems)`, used only by the digest:
  - a file that fails to load is left out (no CV; default preferences) and named in `problems`;
  - CV fact skills that aren't known skills also put `master_cv.yaml` in `problems`;
  - logs give file locations only, never values.
  - `jobhunt profile check` stays strict.
- `digest send`: `rank(unsent, profile)`, then `compose(ranked, …, warnings=problems)`.
- **`compose`:**
  - takes the matcher's order and doesn't re-sort;
  - the cap of 30 applies after ranking, so it keeps the 30 best;
  - filtered-out postings aren't shown, are counted in the header ("· 2 filtered out") and are returned for marking as sent, so they don't come back the next day;
  - each block has a reasons line: `   86 · title ✓ · vietnam (1st) · junior ✓ · (excluded: sales)`;
  - a header line "⚠ Profile invalid (master_cv.yaml): ranked without it; run jobhunt profile check" when the profile couldn't be loaded.
- `digest list` prints the postings in ranked order with `score`, `reasons`, `flags` and `filtered`, and the existing fields.

## Verified

- Tests: the reasons line, flags shown on it, order kept as ranked, filtered postings counted but marked, a digest with only filtered postings, the warning line; CLI: `digest list` fields, a broken `master_cv.yaml` still sends with the warning; lenient loader with and without problems. `make check` passes (584 passed, 26 skipped without a test database).
- **Real data, no send:** `jobhunt digest list --since 30d` ranked the 19 stored postings with the real profile.
  - Junior and mid DevOps roles in Vietnam are first (86), then plain "DevOps Engineer" (80), then senior roles (78) and keyword-only titles (56–68).
  - Most LinkedIn alerts have no description, so the skills part is mostly neutral; that's expected (M8).
  - Nothing was filtered or flagged, since the profile has no filters yet.
- No new dependencies or services, cost $0. No secrets or CV text in the output.
