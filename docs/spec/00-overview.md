# JobHunt Platform — Overview (spec seed)

## 1. Purpose

A personal, Kubernetes-based job-hunt system that collects jobs from many platforms, scores and summarizes them against my profile, tailors a truthful CV and cover letter, and helps me apply with a human approval step. It works for any field: target roles, levels, markets and skills come from the profile (master CV plus preferences), never from code. It is also my portfolio project for Kubernetes, GitOps, observability and SRE practice (CKA path).

## 2. Goals

- **G1:** Collect new jobs from many sources, with new sources added by config or a small plugin.
- **G2:** Rank jobs by fit, using cheap filters first and an LLM only for the top 10-20 a day.
- **G3:** Generate tailored CVs and cover letters using only verified facts.
- **G4:** Track applications and notify me (Telegram) for approval and status.
- **G5:** Run with enterprise-style practices: Terraform, GitOps, security policies, observability, SLOs.
- **G6:** Stay under a fixed monthly cost cap.
- **G7:** Summarize top-ranked jobs, and any job on request: a short TL;DR, must-have versus nice-to-have requirements, fit and gaps against the master CV, and red flags.
- **G8:** Profile-driven: anyone can run their own copy by supplying their own master CV and preferences, without code changes.

## 3. Non-goals

- No scraping of LinkedIn, no bypassing logins or captchas, and no mass auto-apply.
- No fabricated skills, titles or numbers in any generated document.
- No multi-user or SaaS features: one person per deployment. Others self-host their own copy.

## 4. Guardrails (hard rules)

- **Human in the loop:** the system finds, scores, tailors and sends me an application package; I apply and click submit myself.
- **No fabrication:** the LLM may only select, reorder and rephrase facts from `master_cv.yaml`. A validator rejects any skill or number not in that file.
- **Respect source terms:** check robots.txt and terms per source, poll slowly, cache, identify the User-Agent, keep required attribution.
- **LinkedIn:** job-alert emails, manual "save URL" and pasted descriptions only; details otherwise come from the company's own posting. No LinkedIn host is ever requested automatically.
- **Cost:** AWS Budgets alert at $15, a hard daily LLM token cap, and EKS only for demos with a one-command teardown.

## 5. Architecture

```text
Sources → Collectors (CronJobs) → raw store → Parser/Normalizer → Dedupe → Postgres+pgvector
  → Matcher (rules + embeddings → LLM on top N) → Summarizer (top N + on request) → Tailor (+ validator) → Approval (Telegram/UI) → Apply-assist + Tracker
```

- **Profile:** `master_cv.yaml` (facts) and `preferences.yaml` (target roles, levels, markets, languages, exclusions) drive filtering, matching, summaries and tailoring. Both live outside the repo; the repo ships fictional samples.

- **Platform-agnostic collection:** a source is Transport (`http_json`, `rss`, `imap_email`, `search_api`, `html_page`) + Parser (`jsonpath`, `rss`, `selector`, `LLM`, `plugin`) + Policy + Schedule.
- **Three ways to add a source:** YAML only, a plugin file, or LLM extraction as a fallback.
- **Canonical Job schema** (versioned, with an `extra` bag), raw payload stored first so parsers can be re-run, idempotent upserts on `(source, external_id)`, a dead-letter table for invalid records.
- **Patterns:** ports and adapters, plugin registry, anti-corruption layer, declarative config.
- **Source families** (e.g. Greenhouse) list company boards, so adding a company is one line.

## 6. Source strategy

| Tier | Sources | Method |
| ---- | ------- | ------ |
| 1 | Company boards on Greenhouse, Lever, Ashby (and SmartRecruiters, Recruitee, Workable, Personio) | Public job-board endpoints |
| 2 | Himalayas, Remotive, RemoteOK, Jobicy, Arbeitnow, Working Nomads | Official APIs or feeds, with attribution and slow polling |
| 3 | ITviec, TopDev, TopCV, VietnamWorks, JobStreet, Glints, LinkedIn, Japan Dev, Relocate.me | Saved-search email alerts |
| 4 | Anything else | Search API restricted to a domain, then polite fetch of single public pages |

I verified that these sources exist and what they publish, but not every site's terms. We Work Remotely's API terms reportedly restrict building job-search services, so check them before use.

## 7. Infrastructure and cost

- **Dev:** laptop with kind or k3d ($0).
- **Daily "prod":** a 16 GB mini PC (about $300 one-time) running k3s, or a small VPS. Oracle's free tier is an optional secondary node.
- **Showcase:** EKS via Terraform for demos only, on a current Kubernetes version (control plane about $0.10/hour, plus nodes), destroyed after each demo.
- **Estimated monthly cash:** about $15-22 with the mini PC (EKS demos $10-15, LLM $3-5).

Prices change, so confirm before buying.

## 8. Platform requirements (what interviewers should see)

- Terraform for VPC, EKS and the k3s bootstrap, with remote state and locking.
- GitOps with ArgoCD (dev and prod overlays), Helm charts that generate one CronJob per source.
- **Security:** Trivy in CI, cosign signing, Kyverno policies, default-deny NetworkPolicies, External Secrets or SOPS.
- **Scaling and delivery:** KEDA for workers, Argo Rollouts canary on the UI.
- **Observability:** Prometheus, Grafana, Loki, OpenTelemetry.
- Postgres via CloudNativePG with S3 backups and one tested restore.

## 9. Draft SLOs

- 95% of new jobs from polled sources are collected within 2 hours.
- Tailored CV generated within 5 minutes of my approval.
- Per-source health: parse-success rate above a threshold, with a drift alert when a source suddenly returns zero or malformed records.
- Cost: LLM spend below the daily cap, shown on a Grafana panel.

## 10. Acceptance criteria for the first milestone (MVP)

- **AC1:** `docker compose up` collects jobs covering Vietnam and Asia from two sources into Postgres: one job-alert email source (a Vietnamese platform or LinkedIn alerts), and one company-board family (Greenhouse, Lever or Ashby) configured by YAML only.
- **AC2:** Duplicates across runs and sources are not stored twice.
- **AC3:** A new YAML source plus fixture passes CI schema validation and golden-file tests without code changes.
- **AC4:** A daily Telegram digest lists new jobs with scores.
- **AC5:** Tailored output containing a skill not in `master_cv.yaml` is rejected by the validator.

## 11. Phases

Ordered job-hunt first (see section 12): the tool is useful daily in Docker Compose before the Kubernetes move.

- **Weeks 1-2:** canonical schema, interfaces, two sources, Postgres, Telegram digest, in Docker Compose.
- **Weeks 3-4:** matcher, tailor with validator, approval flow (Telegram package), tracker — still in Docker Compose.
- **Weeks 5-6:** move to kind, Helm, ArgoCD, CloudNativePG.
- **Weeks 7-8:** security and delivery layer (Trivy, cosign, Kyverno, KEDA, Argo Rollouts).
- **Weeks 9-12:** Terraform and EKS demo, CKA preparation.
- **Phase 2 (Feb-Apr 2027):** observability, SLOs, chaos drills, blameless postmortems.

## 12. Decisions

### Decided (2026-10-20)

- **Priority:** job hunt first. When usefulness and platform polish conflict, the tool must be usable daily as early as possible; platform layers come after.
- **Generality:** works for any field. Nothing about a profession is hardcoded; it all comes from the profile. One person per deployment.
- **My profile:** my own target roles, levels, markets and relocation destinations live in my private `preferences.yaml`, not in this repo.
- **Summaries:** generated for the top 10-20 jobs a day (the ones already going to the LLM) and for any job requested from Telegram. Content: TL;DR, must-have versus nice-to-have requirements, fit and gaps against the master CV, red flags. Fit claims follow the no-fabrication rule.
- **Build order after spec 02 phase A (2026-10-20):** storage (dedupe-store) and the Telegram digest (notifications) come before collector-runtime and spec 02 phases B–D, so the tool is useful every day as early as possible; then profile and matcher (ranking the digest by fit). Spec numbers keep the original order: 03 collector-runtime, 06 profile, 07 matcher.
- **Default sources and markets:** Vietnamese job platforms and the Vietnam market are enabled by default; LinkedIn (job-alert emails and saved URLs only) is enabled for every market. Every other source, market and region is optional and chosen by the user in config. Nothing is fixed in code.
- **Apply-assist:** after approval, send a package via Telegram (tailored CV PDF, cover letter, apply link). I apply manually and confirm; the tracker is updated on confirmation. No browser form-filling.
- **Phase order:** matcher, tailor and tracker (weeks 3-4) come before the Kubernetes move (weeks 5-6).
- **Output languages:** English, plus Vietnamese for Vietnamese-language postings.
- **Posting languages:** the profile lists the posting languages to keep; others are dropped at collection. Jobs whose language is still unknown are kept until their description is fetched.
- **Repo visibility:** public on GitHub. `master_cv.yaml`, personal data, job data and secrets stay out of the repo; the repo ships a sample CV for tests and demos.
- **Profile location:** `~/.config/jobhunt/master_cv.yaml` and `~/.config/jobhunt/preferences.yaml`, outside the repo. Each fact has an id, English and Vietnamese text, and the skills and numbers it supports.
- **Vietnamese output:** Vietnamese texts live in `master_cv.yaml` next to the English ones (drafted from English, marked `vi_reviewed` until checked). The LLM selects and orders facts for Vietnamese CVs but never translates, so the validator still applies.
- **Validator strictness:** skills match by canonical name or by an alias in `config/skill_aliases.yaml` (e.g. K8s → Kubernetes). Aliases never stretch to a broader or related skill. Numbers must match exactly.
- **Kubernetes depth:** the platform phases aim for enterprise-grade Kubernetes practice (see `constitution.md`, section 5). The goal is real, verified Kubernetes experience that can honestly go on the CV.
- **Cost caps:** an AWS Budgets alert at $15 covering AWS only (EKS demos), and a separate hard LLM cap of $0.20/day (about $6/month), shown on a Grafana panel.

### Open

- k3s on a mini PC versus a VPS for daily "prod".
- Queue choice (NATS or Redis), embedding model and LLM provider (decide when the matcher is specced).
- Telegram-only approval, or also a small web UI.
- Whether Source becomes a Kubernetes CRD later.

## 13. Spec-driven workflow

- **Constitution** (`docs/spec/constitution.md`): the guardrails in section 4, the tech choices, and coding standards (Python 3.12, typing, tests first).
- **One spec per feature**, in this order: canonical-job-schema, source-framework, dedupe-store, notifications, collector-runtime, profile, matcher, job-summary, tailor-validator, approval-tracker, deploy-gitops, platform-security, scaling-delivery, infra-terraform, observability-slo.
- **For each spec:** user story, acceptance criteria, edge cases, test plan. Then a plan, then a task list, then implement task by task.
- **Review gate:** after each task, record what was verified (security groups, IAM scope, secrets, cost) in `docs/decisions/`.
- **Rule for Claude:** it may not add a dependency or source without a spec change.
