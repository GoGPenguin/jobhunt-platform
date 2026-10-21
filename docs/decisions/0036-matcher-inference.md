# 0036: Matcher inference: seniority, years, skills

Date: 2026-10-21
Spec: [07-matcher](../spec/07-matcher.md); plan [07](../plans/07-matcher.md) task 3

## Implementation (pure functions in `jobhunt.matching.infer`)

- `seniority_levels(title)`: job-schema seniority values named by whole folded words or phrases:
  - English: intern, junior/jr/fresher/"entry level", mid/middle/intermediate, senior/sr, lead, staff/principal;
  - Vietnamese: "cao cấp" → senior, "trưởng nhóm" → lead.

  This is generic title vocabulary, not profession keywords (constitution guardrail 5). "Seniority" doesn't match "senior".
- `years_required(text)`: the smallest plausible (≤ 30) figure in "3+ years", "2-4 years", "2–4 years", "2 năm" style phrases. The smallest, so a job is never penalized by its most demanding line; crude by design ("Founded 15 years ago" counts), and the experience weight is the lowest (10).
- `skills_found(text, skills, aliases)`: CV skills found by name or any alias as whole words in folded text ("CI/CD" matches "CI/CD pipelines"; "Go" doesn't match "Going" or "Golang"). Names that fold to a single character ("C", "C++") are skipped to avoid false matches. Returns skill → level.
- `SkillAliases.names_of(skill)` lists a skill's name and its aliases for searching.

These choices are within the spec's description of the components (inference belongs to the matcher, unknown is neutral); they were stated in chat before implementing.

## Verified

- Tests written first (25 new; 558 in total); `make check` passes.
- An en dash typed into a regex and a test was stored as the literal character, which ruff flags as ambiguous. Both are now written as `–` escapes.
- No new dependencies, cost $0.
