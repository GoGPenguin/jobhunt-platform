# 0033: The user's profile converted to version 1

Date: 2026-10-20
Spec: [06-profile](../spec/06-profile.md), P6; plan [06](../plans/06-profile.md) task 5

## What changed in the private files

- `~/.config/jobhunt/master_cv.yaml`:
  - backup saved as `master_cv.pre-v1.yaml` (mode 600);
  - one change: `summary-main`'s `numbers: ["2 years"]` → `["2"]` (figures only, decision 0030);
  - header comments added: the format and the optional skill `level`.

  Skill levels were left unset (count as `working`): only the user can rate them honestly.
- `~/.config/jobhunt/preferences.yaml` was converted in task 3 (decision 0031).

## Verified

- `jobhunt profile check` on the real files: exit 0, **0 errors, 8 warnings**:
  - 7 Vietnamese texts not reviewed (`vi_reviewed: false`), the translations drafted from the English CV on 2026-10-20;
  - an empty `profile.linkedin`.

  Each warning names only its location and fact id, no CV text (P6).
- All other content is unchanged.

## For the user, when convenient

- Rate skills (`level: core | working | familiar`) and fill in the filters (`excluded_companies`, `excluded_keywords`, `minimum_salary`) and `looking_for`. The matcher (spec 07) uses all of them.
- Review the 7 Vietnamese texts and set `vi_reviewed: true`, and add the LinkedIn URL.
