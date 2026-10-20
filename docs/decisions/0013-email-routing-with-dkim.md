# 0013: Email routing with DKIM check

Date: 2026-10-20
Spec: [02-source-framework](../spec/02-source-framework.md), F5; plan [02A](../plans/02a-email-sources.md) task 5

## Decision asked and answered before coding

| Question | Answer |
| -------- | ------ |
| The From header can be forged, so a phishing email posing as LinkedIn could inject fake jobs with phishing links into the digest. Require sender authentication? | Yes: route only if Gmail's verdict is `dkim=pass` for the sender's domain. |

## Implementation

- `route(payload, sources)` returns `routed`, `unknown_sender`, `unauthenticated` or `disabled`, plus the sender domain, so the CLI can count each.
- **Which verdict is trusted:** the topmost `Authentication-Results` header whose authserv-id is the receiving server (`mx.google.com` by default, configurable as `email.imap.trusted_authserv_id` for other mail providers). Headers further down were added before Gmail saw the mail and can be forged by the sender; only the first trusted header counts.
- **Alignment:** a `dkim=pass` counts only if its signing domain (`header.d`, or the domain in `header.i`) equals the From domain or is a subdomain of it, or the reverse. LinkedIn signs as both `linkedin.com` and `mailb.linkedin.com`. `notlinkedin.com` does not match `linkedin.com`.
- **Sender matching:** a configured `@linkedin.com` matches `linkedin.com` and its subdomains.
- `schemas/sources.v1.json` regenerated for the new setting.

## Verified

- Tests written first (13 new; 261 in total); `make check` passes.
- Rejected as `unauthenticated`: no header, `dkim=fail`, a pass for another domain, a suffix look-alike domain, a verdict from another server, and a forged `pass` below Gmail's real `fail`.
- The `header.d=` test caught a bug in the first signer pattern, which read `linkedin.com` as `m`; it was fixed with explicit `header.d` / `header.i` patterns.
- Both real LinkedIn sample emails route to `linkedin-email`.
- No new dependencies, no secrets, cost $0.
