# 0005: Language detection

Date: 2026-10-20
Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md), `language` field; plan task 5

## Decisions asked and answered before coding

| Question | Answer |
| -------- | ------ |
| Languages to recognise | The plan list: vi, en, ja, zh, ko, de, nl, fr, es. Everything else is `unknown`. |
| Short text with no clear signal (e.g. a bare English title) | `unknown`, not a guess of `en`. |

## Implementation

- `jobhunt.domain.language.detect_language(text)` returns an ISO 639-1 code or `"unknown"`. No library.
- **Script first:** Korean (Hangul), Japanese (kana present), Chinese (Han without kana). A script must have at least 2 characters and 20% of the letters, because Asian postings mix in English terms.
- **Then common words** for Latin-script languages: the language with the most hits wins if it has at least 2 hits, 10% of the words, and 1.5× the runner-up.
- **Vietnamese is detected by common words, not by its special letters.** Detecting by letters would label "DevOps Engineer – Đà Nẵng" as Vietnamese because of the place name. This follows directly from the "short text → unknown" answer, so it was applied and noted here rather than asked separately.
- Word lists hold function words and general job-posting vocabulary only (experience, salary, team), never role or skill names, so they stay profile-neutral (constitution guardrail 5).
- Parsers set `language` from the source when it is stated, and call `detect_language(title + description)` otherwise.

## Verified

- Tests written first and failed before the module existed. 22 tests, 149 in total; `make check` passes.
- Covered: all nine languages; short Vietnamese and Japanese titles; English titles and text that name Vietnamese places stay English or `unknown`; decomposed Vietnamese; Thai, numbers and bare skill lists give `unknown`.
- Manual check on realistic inputs not in the tests: bilingual Vietnamese post → `vi`; English post with a Vietnamese address → `en`; Indonesian → `unknown`; ITviec and LinkedIn alert subjects → `vi` and `en`.
- No new dependencies, no secrets, cost $0.

## Limits

- Kanji-only Japanese text is reported as Chinese. Rare in postings, which almost always contain kana.
- Accuracy on unusual text is lower than a library such as `lingua`. If `unknown` turns out too common in practice, that library can be proposed as a dependency.
