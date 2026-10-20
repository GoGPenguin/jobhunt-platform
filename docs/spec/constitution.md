# Constitution

Rules every spec, plan and change must follow. Changing this file is itself a spec change. Background and goals are in [00-overview.md](00-overview.md).

## 1. Guardrails

1. **Human in the loop.** The system finds, scores, tailors and sends an application package. A human applies and submits. Nothing submits an application automatically.
2. **No fabrication.** Generated CVs and cover letters may only select, reorder and rephrase facts from `master_cv.yaml`. Vietnamese output uses the Vietnamese texts stored in `master_cv.yaml`; the LLM never translates facts.
3. **Validator.** Every generated document passes the validator before it reaches the user:
   - Every skill mentioned must exist in `master_cv.yaml`, either by its canonical name or by an alias listed in `config/skill_aliases.yaml`.
   - An alias maps an alternative name to the same skill only (K8s → Kubernetes, EKS → AWS EKS). It never maps to a broader, narrower or related skill (AWS ≠ EKS, Docker ≠ Kubernetes).
   - Every number (percentages, years, counts, scores) must match a number in `master_cv.yaml` exactly.
   - Any failure rejects the whole document.
4. **Summaries are faithful.** A job summary only states what the posting says. Its fit section may claim coverage only by citing master CV fact ids, and anything not covered is listed as a gap. The same validator checks it.
5. **Profile-driven.** No role, skill, level, market or keyword list is hardcoded. They come from `master_cv.yaml` and `preferences.yaml`, so the system works for any field.
6. **Real facts only.** Work on this project enters `master_cv.yaml` only after it is implemented and verified, with a link to the decision record in `docs/decisions/` that shows it.
7. **Respect sources.** Check robots.txt and terms before adding a source. Poll slowly, cache, send an identifying User-Agent, keep required attribution. No scraping LinkedIn, no bypassing logins or captchas. LinkedIn is used only through alert emails, manually saved URLs and descriptions the user pastes; no LinkedIn host is ever requested automatically, enforced in code.
8. **Personal data stays out of Git.** `master_cv.yaml` and `preferences.yaml` live in `~/.config/jobhunt/`. Job data, credentials and secrets are never committed. The repo is public and ships only a fictional sample profile for tests and demos.
9. **Cost caps.** AWS Budgets alert at $15 for AWS (EKS demos only, torn down with one command). Hard LLM cap of $0.20/day, enforced in code, not only alerted.

## 2. Change control

- No new dependency, source, service or infrastructure resource without a spec change that names it and says why.
- One spec per feature: user story, acceptance criteria, edge cases, test plan. Then a plan, then a task list, then one task at a time.
- After each task, record what was verified (security, IAM scope, secrets, cost, tests) in `docs/decisions/`.
- Claude never runs `terraform apply`/`destroy`, pushes, or changes a live cluster without asking first.

## 3. Tech choices

| Area | Choice |
| ---- | ------ |
| Language | Python 3.12 |
| Data models | Pydantic |
| Database | Postgres + pgvector, run by CloudNativePG in Kubernetes |
| Local / MVP runtime | Docker Compose |
| Kubernetes | kind (dev), k3s (daily "prod"), EKS (demos only) |
| Packaging and delivery | Helm, ArgoCD (dev and prod overlays), Argo Rollouts |
| Infrastructure | Terraform with remote state and locking |
| CI | GitHub Actions |
| Supply chain | Trivy, cosign |
| Policy and secrets | Kyverno, External Secrets or SOPS |
| Scaling | KEDA |
| Observability | Prometheus, Grafana, Loki, OpenTelemetry |
| Notifications and approval | Telegram |

Still open: queue (NATS or Redis), embedding model, LLM provider, web UI. Each is decided in the spec that first needs it.

## 4. Code standards

- Type hints everywhere; type checking passes in CI.
- Tests are written before or with the code they cover. Each source has a recorded fixture and a golden-file test.
- External systems sit behind ports (interfaces) with adapters, so core logic is tested without network or database.
- Configuration is declarative and validated against a schema in CI.
- Writes are idempotent: re-running a collector or parser never creates duplicates.

Tooling: `uv` (packaging), `ruff` (lint and format), `mypy --strict` (types), `pytest` (tests).

## 5. Kubernetes standards

The goal is a production-grade baseline, the kind an enterprise platform team would accept. Kyverno enforces these rules once it is installed (weeks 7-8). Until then, CI checks them on rendered Helm output.

**Workloads**

- Every container sets CPU and memory requests and limits.
- Long-running workloads have readiness and liveness probes. Multi-replica Deployments have a PodDisruptionBudget.
- CronJobs set `concurrencyPolicy: Forbid`, `backoffLimit`, `activeDeadlineSeconds` and history limits.
- Every resource carries the standard `app.kubernetes.io/*` labels.

**Security**

- Pods run as non-root, with a read-only root filesystem, no privilege escalation, all capabilities dropped and the `RuntimeDefault` seccomp profile.
- Each workload has its own ServiceAccount with least-privilege RBAC. `automountServiceAccountToken` is false unless the workload calls the Kubernetes API.
- Every namespace has a default-deny NetworkPolicy; traffic is allowed explicitly.
- Secrets are never stored in plain text in Git (External Secrets or SOPS).

**Images**

- Images are referenced by digest, never by a `latest` tag.
- CI scans with Trivy and fails on HIGH or CRITICAL vulnerabilities that have a fix. Images are signed with cosign, and the cluster only admits signed images.

**Delivery**

- All cluster changes go through Git and ArgoCD. A manual `kubectl apply` is a break-glass action and gets a decision record.
- Every component exposes metrics and has at least one alert tied to an SLO in [00-overview.md](00-overview.md).
- Postgres has scheduled S3 backups and a restore that has actually been tested and recorded.
