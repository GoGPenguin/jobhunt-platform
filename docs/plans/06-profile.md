# Plan 06: Profile

Spec: [06-profile](../spec/06-profile.md)
Status: done 2026-10-20 (tasks 1–5; decision records 0029–0033)

## Design

**Code layout:** `jobhunt.profile` package:
- `aliases.py` (`SkillAliases`: canonical name ↔ aliases, `canonical(name)`);
- `master_cv.py` and `preferences.py` (Pydantic models with the spec's validation rules);
- `load.py` (`Profile`, `load_profile(config_dir)`).

The existing `jobhunt/preferences.py` functions delegate to it until callers move over (task 3).

**Validation that needs both files and the aliases** (fact skills must exist by name or alias) runs in `load_profile`, after each file validates on its own, so errors can still name the entry.

**Errors without personal values:** Pydantic errors include the input value, which here would be a CV sentence. `profile check` prints only the location (`experience[0].projects[1].facts[2] (vizerp-ci-optimization).numbers`) and a message written by us, never `input_value`.

**Initial `config/skill_aliases.yaml`** (only true synonyms; reviewed with this plan):

| Skill | Aliases |
| ----- | ------- |
| Kubernetes | K8s |
| AWS EKS | EKS, Amazon EKS |
| AWS | Amazon Web Services |
| AWS CDK | CDK |
| AWS CodePipeline | CodePipeline |
| AWS CodeBuild | CodeBuild |
| ECS Fargate | Amazon ECS on Fargate |
| ALB | Application Load Balancer |
| CloudFront | Amazon CloudFront |
| RDS | Amazon RDS |
| S3 | Amazon S3 |
| IAM | AWS IAM |
| WAF | AWS WAF |
| VPC | Amazon VPC |
| GitLab CI/CD | GitLab CI |
| Infrastructure as Code | IaC |
| CI/CD | CICD |
| TypeScript | TS |

Not aliases, because they name something broader or different: "Fargate" (also used by EKS) is not "ECS Fargate", "Docker" is not "Kubernetes", "AWS" is not "EKS".

**Converting your real files:**
- `master_cv.yaml` already matches version 1 except for `level`, which stays empty. Only you can rate your skills honestly: core, working or familiar.
- `preferences.yaml` gets the new keys (`looking_for`, `excluded_companies`, `excluded_keywords`, `minimum_salary`) as empty or commented placeholders for you to fill in. All existing values are kept.

## Dependencies

None new.

## Tasks

Each task is test-first, ends with `make check` passing, a decision note, a commit and a push.

1. **Skill aliases.** Model (an alias belongs to one skill, no alias equals a skill name, case-insensitive), `jobhunt/profile/skill_aliases.yaml` as above (inside the package), schema `skill_aliases.v1.json` (P5).
2. **Master CV.** Model and rules: unique fact ids, numbers literally in `en`/`vi`, dates, unknown keys, skills by name or alias, warnings for unreviewed Vietnamese and an empty LinkedIn; `config/master_cv.sample.yaml` (fictional); schema (P2, P3, P4).
3. **Preferences and `load_profile`.** Model with codes, enums, timezone, unique markets, filters, `looking_for`; `config/preferences.sample.yaml`; schema. Collection and the digest read through `load_profile()` with unchanged behaviour (P7).
4. **`jobhunt profile check`** with location-only messages; the privacy scan extended to `config/` (P1, P6 for samples, P8).
5. **Convert your real files** and run `profile check` on them (P6). You then rate your skill levels and fill in the new filters when convenient.

## Risks

- **The literal number rule may reject a real fact** whose text and number list drifted. `profile check` names the fact; fix the text or the list.
- **Pydantic error messages leaking CV text** is prevented by printing our own messages only, and a test checks the output contains no fact text.
