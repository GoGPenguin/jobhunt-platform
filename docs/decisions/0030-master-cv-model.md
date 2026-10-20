# 0030: master_cv.yaml version 1

Date: 2026-10-20
Spec: [06-profile](../spec/06-profile.md), P2, P3, P4; plan [06](../plans/06-profile.md) task 2

## Decision asked during the task

| Question | Answer |
| -------- | ------ |
| `numbers` like "2 years" can't appear literally in the Vietnamese text ("2 năm") | **Figures only, whole match:** `numbers` holds the figure without units or words ("2", "40%", "30–80%", "15M", "3.82/4.0"), and it must appear in both texts as a whole figure. "2" doesn't match inside "12", "2024", "3.2" or "v2". Spec 06 updated. |

The sample's own summary ("3 years" / "3 năm") failed the first draft of the rule, which is how this was found. The user's real CV has the same case (`summary-main`: "2 years"), to be converted to "2" in task 5.

## Implementation

- `jobhunt.profile.master_cv`: frozen Pydantic models (`MasterCV`, `Fact`, `Skill`, `Experience`, `Project`, `Education`, …), unknown keys rejected everywhere.
- **Rules:**
  - fact ids are unique slugs (also experience ids);
  - a figure pattern applies to `numbers`, plus the whole-figure match in `en` and `vi` (`contains_figure`);
  - dates are `YYYY-MM` with end ≥ start;
  - skill names are unique, ignoring case;
  - `level` is `core`/`working`/`familiar`, defaulting to `working`.
- `fact_skill_issues(cv, aliases)` checks fact skills against `skills` by name or alias (the sample's "EKS" resolves to "AWS EKS"). It is separate because it needs the alias table.
- `warnings()`: unreviewed Vietnamese texts and an empty LinkedIn, by location only.
- **No CV text in errors:** `load_master_cv` builds each message from the error location (`describe_location`, now shared in `config_files`) and our own message, never Pydantic's default text, which can include the input. A test plants a sentence and checks it is absent from the error.
- `config/master_cv.sample.yaml` (fictional "Alex Example"); `schemas/master_cv.v1.json` committed with the drift check.
- Test speed: the fake Telegram server's poll interval went from 0.5 s to 10 ms, removing a 0.5 s wait from each of 12 teardowns (suite back to about 6 s).

## Verified

- Tests written first (28 new; 481 in total); `make check` passes.
- The real master CV, validated read-only with location-only output: one error, `summary[0] (summary-main).numbers[0]: '2 years' is not a figure`, as expected.
- No new dependencies, cost $0.
