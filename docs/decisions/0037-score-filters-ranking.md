# 0037: Fit score, filters and ranking

Date: 2026-10-21
Spec: [07-matcher](../spec/07-matcher.md), M1, M3–M8; plan [07](../plans/07-matcher.md) task 4

## Implementation (`jobhunt.matching.score`)

- `Matcher(profile).score(posting) -> Ranked(score 0–100, reasons, flags, filtered)`; `rank(postings, profile)` sorts by:
  1. unflagged first;
  2. score;
  3. newest first-seen.

  Filtered-out postings stay in the result for callers to mark as sent.
- **Score:** `100 × Σ(weight × component) / Σ weights`, using the profile's weights (defaults 30/25/20/15/10).
- **Components:**
  - **title:** role phrase 1.0 "title ✓"; role keyword 0.6 "title ~kw"; else 0. No targets: 0.5.
  - **market:** first fitting market in priority order, `1 − index/n`, "vietnam (1st)". A market fits when its countries and regions (bundled plus profile overrides) cover the posting's countries, or, for a remote job, when it allows remote and the job's stated eligibility overlaps it (or isn't stated). No location at all: 0.5. No markets: 0.5.
  - **seniority:** structured, else from title words. In your targets: 1.0 "mid ✓"; adjacent: 0.5 "senior ~"; else 0 "staff_plus ✗"; unknown: 0.6.
  - **experience:** structured minimum, else "N years" from the description, against `years_experience_max`. Within: 1.0 "2y ✓"; one more: 0.5; more: 0; unknown: 0.6.
  - **skills:** CV skills found (level weights 1.0/0.7/0.4) / 4, capped at 1; reason lists the best three. No CV: 0.5. **No description and nothing found: 0.5** (unknown, M8); a description without your skills: 0.
- **Locations** of a posting are the union over all its sources (a company board may name the country a LinkedIn alert leaves out); text comes from the representative job.
- **Filters:**
  - excluded company (after `normalize_company`) → filtered;
  - remote job whose *known* eligibility regions don't cover your country → filtered (unknown labels count as not stated);
  - excluded keyword as a whole folded word in title or description → flag;
  - stated salary in a currency that has a floor, upper end converted per year (12 months, 52 weeks, 260 days, 2,080 hours), below the floor → flag. An unknown period isn't compared.
- **Remote fitting the first market:** a remote job open to APAC fits "vietnam (1st)", since that market allows remote work and VN is in APAC (spec 07: market fit uses a remote job's stated eligibility). The first draft of the test was loose about this; it now asserts it.

## Verified

- Tests written first, on the fictional sample profile (17 new; 575 in total); `make check` passes:
  - M1: "Senior Platform Engineer" in Da Nang beats "Sales Engineer" in Berlin, reasons "title ✓", "vietnam (1st)", skills.
  - Market order: Hanoi > Tokyo > Berlin; unknown location beats a wrong market.
  - M3: excluded company; M4: US-only remote filtered, APAC and unknown labels kept.
  - M5: "Sales" flags, "Salesforce" doesn't.
  - M6: five salary cases, including period conversion and other currencies.
  - M7: weights change the order.
  - M8: no description beats an unrelated one.
  - Seniority and experience preferences; the full ordering rule; neutral scoring with no profile files.
- No new dependencies, cost $0.
