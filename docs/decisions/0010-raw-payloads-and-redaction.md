# 0010: Raw payloads, link redaction and parser registry

Date: 2026-10-20
Spec: [02-source-framework](../spec/02-source-framework.md); plan [02A](../plans/02a-email-sources.md) task 2

## Decisions

- **Redact before anything else sees the email** (decided with plan 02A): `RawPayload.from_email` runs `redact_email` first, so no later step, log or store ever holds a sign-in token.
- **What is removed:** query parameters for sign-in and session tokens (`otpToken`, `midToken`, `midSig`, `token`, `auth`, `sig`, `session`, `apikey`, …), one-click unsubscribe ids (`loid`), and tracking ids (`trk*`, `utm_*`, `lipi`, `eid`, `refId`, `trackingId`, `gclid`, `fbclid`, …). Matching is case-insensitive. Everything else stays as written, including `&amp;` inside HTML.
- **Headers too:** links in headers are redacted, because `List-Unsubscribe` carries the same tokens as the body.
- **Kept on purpose:** `e`, `v`, `t` on `media.licdn.com` company-logo URLs. They are the image CDN's expiry and signature for public logos, not account tokens.
- **Identity:** `raw_ref = raw/email/<sha256(origin)[:32]>`, where origin is `email:<Message-ID>`, or `email:sha256:<content hash>` when there is no Message-ID. Re-fetching an email gives the same `raw_ref`.
- **Re-encoding:** text parts whose links change are written back as UTF-8 quoted-printable. The email's content is unchanged apart from the links; byte-level fidelity is traded for not storing tokens.
- **Registry:** `ParserRegistry.register(name, version)` validates the name (slug) and semver, rejects duplicates, and lists known names in the "unknown parser" error. One global `REGISTRY` that parser modules register into.

## Verified

- Tests written first (33 new; 224 in total); `make check` passes.
- **On the two real LinkedIn sample emails** (outside the test suite, files stay private): after redaction there are 0 occurrences of `otpToken`, `midToken`, `midSig`, `trkEmail`, `lipi=` and `loid=`, and all 17 job ids are still present (11 + 6).
- The first real-sample run found what the synthetic tests missed: tokens in the `List-Unsubscribe` header and the `loid` unsubscribe id. Both were added as tests, then fixed.
- No new dependencies, no secrets, cost $0.

## Follow-up: CI failure on Python 3.12.3

The first push failed in CI on one test (`test_redacts_links_in_headers`) while passing locally. Cause: CI uses the runner's Python 3.12.3, the dev machine uv's 3.12.14, and 3.12.3's `email` package keeps the folding space when reading a header folded right after the colon (`' <https://…>'`). Reproduced locally with `uv run --python 3.12.3`. The redaction output was correct; the test now strips the header value, as parsers must when reading headers. All 224 tests pass on both 3.12.3 and 3.12.14.
