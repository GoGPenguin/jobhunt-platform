# Spec 07: Matcher (rule-based fit ranking)

Status: approved 2026-10-21
Depends on: [01-canonical-job-schema](01-canonical-job-schema.md), [04-dedupe-store](04-dedupe-store.md), [05-notifications](05-notifications.md), [06-profile](06-profile.md)
Used by: notifications (digest order and reasons), later the LLM re-ranking spec and job summaries

## User story

As the job seeker, I want the digest ordered by how well each job fits me, with a short reason for each, so the jobs worth my time are at the top and I can see why they're there.

## Scope

In scope:

- A rule-based fit score (0–100) per posting, computed at digest time from the stored job and the current profile. It is never stored.
- Inference the canonical schema leaves out on purpose (spec 01): a city's country, seniority from the title, years of experience from the description, and CV skills mentioned in the job.
- Filters from the profile: excluded companies and remote jobs outside your eligibility are dropped from the digest; excluded keywords and pay below the minimum rank last.
- Bundled reference data: GeoNames cities (city → country) and region definitions (APAC, EU, …), with overrides in `preferences.yaml`.
- The digest ordered by score, each posting with a reasons line; `digest list` shows score and reasons too.

Out of scope:

- Embeddings, LLM re-ranking of the top N, choosing their provider (a later spec).
- Learning from your feedback (buttons come with approval-tracker).
- Fuzzy company or title matching across sources (dedupe stays exact).

## Decisions (2026-10-20)

| Topic | Decision |
| ----- | -------- |
| Approach | Rules now: explainable, free and testable. LLM later, in its own spec. |
| City → country | Bundled GeoNames `cities15000` (CC BY 4.0), generated into a compact lookup with diacritics folded. |
| Low fit | Show everything, ranked; nothing hidden while the weights are being tuned. |
| Display | Score plus short reasons per posting. |
| Regions | Bundled defaults; `preferences.yaml` can add or redefine labels. |
| Weights | Documented defaults; `preferences.yaml` `matching.weights` can override any of them. |
| When | Computed at digest time, never stored; profile changes apply at once. |
| Dropped postings | Marked as sent (no backlog). Removing a company from `excluded_companies` later doesn't bring back postings already dropped; they stay visible in `digest list`. |

## Score

`score = Σ weight × component`. Each component is between 0 and 1, and the default weights add up to 100.

| Component | Default weight | How it is scored |
| --------- | -------------- | ---------------- |
| title | 30 | A target role phrase appears in the title: 1.0. Otherwise a role keyword as a whole word: 0.6. Otherwise 0. Folded text, as in spec 04. |
| market | 25 | The first market (in priority order) the job fits: 1.0 for the first market, decreasing evenly to 1/n for the last; 0 for none. Fitting a market means its countries/regions cover the job's country (or, for remote jobs, its stated eligibility), and its workplace list allows the job's workplace when that's known. A job with no location information at all: 0.5. |
| skills | 20 | CV skills (by name or alias) found as whole words in the title, description and tags, weighted by your level (core 1.0, working 0.7, familiar 0.4). The component is that sum divided by 4, capped at 1. A job with an empty description and no skill in the title: 0.5 (unknown, not bad). |
| seniority | 15 | Structured seniority, else inferred from title words (intern, junior, mid/middle, senior, lead, staff, principal). Any inferred level in your targets: 1.0; an adjacent level only: 0.5; otherwise 0; unknown: 0.6. |
| experience | 10 | Minimum years (structured, else "N+ years" in the description) ≤ your `years_experience_max`: 1.0; one more year: 0.5; more: 0; unknown: 0.6. |

The posting's score is its representative job's score (spec 04), which is the one with a description when there is one.

## Filters

| Filter | Effect |
| ------ | ------ |
| `excluded_companies` | Postings whose company matches after `normalize_company` are left out of the digest. They stay stored and appear in `digest list`, marked. |
| `drop_remote_outside_eligibility` | A remote job whose stated `remote_regions` don't cover your country is left out of the digest, as above. Not stated means kept. |
| `excluded_keywords` | Whole word, case-insensitive, in the title or description: the posting ranks after every unflagged one, with "(excluded: sales)". |
| `minimum_salary` | A stated salary in the same currency whose upper end (or only end) is below the floor, compared after converting the period (1 year = 12 months = 52 weeks = 260 days = 2,080 hours): ranks last, "(below minimum salary)". Other currencies aren't compared (no exchange rates). |

**Order:** postings not flagged, by score, then flagged ones, by score; ties go to the newest first-seen.

## Reference data

- **Cities:** generated from GeoNames `cities15000` by a committed script, like the ISO lists.
  - Each entry is a folded name or ASCII name → country, keeping the most populous on a clash (Hanoi → VN).
  - LinkedIn suffixes such as "Capital Region", "Metropolitan Area", "Area" or "Region" are stripped before lookup.
  - The download date and attribution ("GeoNames, CC BY 4.0") are recorded in the data file header and `docs/`.
- **Regions:** a reviewed `regions.yaml` in the package. Labels: `WORLDWIDE`, `APAC` (East, South-East and South Asia plus Oceania), `ASEAN` (its 11 members, with Timor-Leste since October 2025), `EU` (the 27 members), `EMEA`, `AMERICAS`, `LATAM`.
  - `preferences.yaml` can add labels or redefine them under `regions:`.
  - Unknown labels in a job count as "not stated".
- **Preferences additions** (a spec 06 schema change, version 1 stays because both keys are optional):
  - `regions: {LABEL: [country codes]}`;
  - `matching: {weights: {title, market, skills, seniority, experience}}`. Weights are non-negative numbers; the total doesn't need to be 100, because the score is normalized to 0–100.

## Digest and list changes

- Each posting gets a reasons line after its title line, for example `82 · title ✓ · vietnam (1st) · AWS, Terraform`, plus `(excluded: sales)` or `(below minimum salary)` when flagged.
- **Order:** the digest uses the matcher's order. The cap (30 + "and N more") applies after ordering, so the best 30 are shown.
- **Marking:** dropped postings (excluded company, ineligible remote) are not shown, and **are marked as sent**, so they don't wait in the backlog. They are counted on the header line ("… · 2 filtered out").
- `jobhunt digest list` adds `score`, `reasons` and `filtered` to each line.

## Acceptance criteria

- **M1:** for the fictional profile, a posting titled "Senior Platform Engineer" in Da Nang (city only) with Terraform and AWS in its description outscores "Sales Engineer" in Berlin; the reasons name the title match, "vietnam (1st)" and the skills.
- **M2:** "Đà Nang", "Ha Noi" and "Ho Chi Minh City" resolve to VN; "Singapore" to SG; "Hanoi Capital Region" to VN after stripping the suffix.
- **M3:** an excluded company is left out of the digest, marked as sent, and counted as filtered out.
- **M4:** a remote job open only to `US` residents is left out when `drop_remote_outside_eligibility` is on; one open to `APAC` is kept for a candidate in VN.
- **M5:** an excluded keyword ranks the posting after all unflagged ones, with its reason; "Salesforce" doesn't match "sales".
- **M6:** a salary of 15–18M VND/month ranks last under a 20M VND/month floor; 300M VND/year (25M/month) doesn't; a USD salary isn't compared with a VND floor.
- **M7:** weights from `preferences.yaml` change the order as expected; invalid weights (negative, unknown names) are rejected by `profile check`.
- **M8:** a job with no description isn't scored lower on skills than one whose description lists none of your skills.
- **M9:** the digest shows the reasons line, is ordered by score, and its cap keeps the 30 best.
- **M10:** the cities data is generated by a committed script and carries GeoNames attribution; regions and city data pass `profile check`'s validation (unknown country codes rejected).

## Edge cases

| Case | Expected handling |
| ---- | ----------------- |
| City name in two countries | The most populous wins; a country stated in the job always wins over the lookup. |
| "Remote" job with no regions | Market fit uses the workplace only (a remote-friendly market fits); eligibility not stated means it is kept. |
| Title with two levels ("Middle - Senior") | The best level in your targets counts. |
| No `preferences.yaml` | Every posting scores on recency order only; no filters, no reasons beyond "no profile". |
| No `master_cv.yaml` | The skills component is 0.5 for all (unknown), so the rest still ranks. |

## Dependencies

None new. GeoNames data is downloaded once by the generator script and committed (CC BY 4.0, with attribution).

## Test plan

- Unit tests per component with fictional jobs and the sample profile, plus filter and order tests (M1, M3–M8).
- City and region lookup tests (M2, M10).
- Digest golden tests updated for the reasons line and score order (M9).
- Manual check: today's real digest postings ranked and listed with reasons, to tune the default weights with you.
