# 0029: Skill aliases

Date: 2026-10-20
Spec: [06-profile](../spec/06-profile.md), P5; plan [06](../plans/06-profile.md) task 1

## Implementation

- `jobhunt.profile.aliases.SkillAliases`: `canonical(name)` returns the skill a name or alias refers to (or `None`); `same_skill(a, b)` compares two names through the table. Matching is case-insensitive, so the table lists "K8s" once and "k8s" matches too.
- **Rules,** checked on load with errors naming the entry. An alias:
  - belongs to exactly one skill (reported when the second skill claims it);
  - is never also a skill name, and never its own skill's name;
  - is not listed twice for the same skill;
  - is not empty, and no skill name is empty.
- **The bundled table** is `jobhunt/profile/skill_aliases.yaml`, inside the package rather than `config/` as the spec first said, so installed copies and container images have it (the same reason as the SQL migrations; spec and plan updated). Its contents are the 18 entries reviewed with plan 06, true synonyms only. A test pins that "Fargate", "Docker" and "AWS" are *not* aliases of "ECS Fargate", "Kubernetes" and "AWS EKS".
- `schemas/skill_aliases.v1.json` is committed with the drift check (input shape).

## Verified

- Tests written first (9 new; 453 in total); `make check` passes; the built wheel contains `skill_aliases.yaml`.
- No new dependencies, no personal data (the table is generic), cost $0.
