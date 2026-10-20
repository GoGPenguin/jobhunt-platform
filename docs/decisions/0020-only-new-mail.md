# 0020: Only-new mail (Message-ID pre-check)

Date: 2026-10-20
Spec: [04-dedupe-store](../spec/04-dedupe-store.md), D7, "Only-new mail"; plan [04](../plans/04-dedupe-store.md) task 5

## Implementation

- `fetch_emails(..., known=store.known_raw_refs)` first fetches `BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]` for the UIDs in the window (batched, read-only like every other fetch), computes each `raw_ref`, asks `known` which are stored, and fetches full bodies only for the rest.
- **One identity rule:** `message_id()`, `email_origin()` and `raw_ref_for()` were factored out of `RawPayload.from_email` and are used by both the pre-check and the full parse, so they can't compute different `raw_ref`s for the same email. A test checks the pre-check's `raw_ref` equals the full email's.
- Emails without a Message-ID are always fetched; their identity is a content hash, unknown until the body is read.
- UIDs are matched to header responses by the `UID n` in each response, not by position.
- Without `known` (dry runs, `.eml` input) behaviour is unchanged, so the phase A command sequence still holds.

## Verified

- Tests written first (4 new; 374 in total, 19 skipped without a database); `make check` passes.
- D7: a second run over the same mailbox issues only the header fetch and no `BODY.PEEK[]` fetch; with 1 of 3 emails stored, bodies are fetched for exactly the other 2; an email without a Message-ID is always fetched.
- The fake IMAP server still fails on any non-PEEK fetch or write command.
- No new dependencies, no secrets, cost $0.
