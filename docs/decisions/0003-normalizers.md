# 0003: Text, URL, datetime and HTML normalizers

Date: 2026-10-20
Spec: [01-canonical-job-schema](../spec/01-canonical-job-schema.md), section "Normalization"; plan task 3

## Decision

- `jobhunt.domain.normalize` holds pure functions: `clean_line` (titles, names), `clean_text` (multi-line text), `normalize_url`, `to_utc`, `date_to_utc`, `html_to_text`. The Job model (task 4) will apply them, so parsers get them for free.
- **HTML to text** is a small converter on the standard library's `html.parser`, as the plan proposed. No new dependency.
- Choices made where the spec was silent:
  - List items are prefixed with `- `, so requirement lists stay readable for the matcher and summaries.
  - Blank-line runs collapse to a single blank line.
  - URL query parameters are filtered and sorted *as written*, without decoding and re-encoding, so `%20` stays `%20` and the URL still points at the same page.
  - Credentials in a URL (`user:pw@host`) are dropped, so they can never be stored or shown.
  - Plain-text descriptions (e.g. from emails) should use `clean_text`, not `html_to_text`: HTML rules treat a newline as a space.

## Verified

- Tests written first and failed before the module existed. 36 normalizer tests, 79 in total; `make check` passes.
- Spec S3 cases covered: decomposed Vietnamese diacritics equal their composed form; a URL with `utm_source` and a fragment is cleaned.
- Naive datetimes are rejected; aware ones are converted to UTC (tested with a fixed +07:00 offset, so no timezone database is needed).
- Manual check on messy HTML: unclosed tags, nested lists, `<script>` containing tag-like strings, Vietnamese salary text. All produced clean output.
- No new dependencies, no secrets, cost $0.

## For later specs

- **source-framework:** Greenhouse's job-board API returns `content` HTML-escaped a second time (`&lt;p&gt;`). Its parser must `html.unescape` before `html_to_text`, otherwise tags appear as literal text. Covered by that parser's golden test.
