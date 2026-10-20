# 0009: sources.yaml config (email section)

Date: 2026-10-20
Spec: [02-source-framework](../spec/02-source-framework.md), F1 (email part); plan [02A](../plans/02a-email-sources.md) task 1

## Decisions

- **Dependencies:** `pyyaml` (runtime, locked 6.0.3) and `types-pyyaml` (dev), approved with plan 02A.
- **Layout:** general-purpose pieces sit outside `sources`. `jobhunt.config_files` has `ConfigError` and a strict YAML reader; `jobhunt.preferences` has `load_accepted_languages`, which the profile spec will extend; `jobhunt.sources.config` has the `sources.yaml` models.
- **Strict YAML:** a `SafeLoader` subclass rejects duplicate keys. Plain PyYAML silently keeps the last value, so a repeated `label:` would go unnoticed.
- **LinkedIn rule in config:** any source whose parser name starts with `linkedin` or whose sender is `linkedin.com` or a subdomain must have `page_fetch: forbidden`. Also enforced in code for HTTP in phase B (F8).
- **One sender, one source:** a sender domain routed to two sources is a config error, so routing is never ambiguous.
- **No preferences file means no language filter**, with a warning. Not asked: it only affects copies without a profile, and the user's own `preferences.yaml` sets `[vi, en]`.
- **Schema modes:** `sources.v1.json` is exported in *validation* (input) mode, with the YAML key `from` and optional defaults, because people write it. Job and dead-letter schemas stay in serialization (stored) mode.

## Verified

- Tests written first (24 new; 191 in total); `make check` passes, including the drift check for the new `schemas/sources.v1.json`.
- The fictional `config/sources.sample.yaml` validates in CI.
- Rejected with an error naming the entry: unknown parser, duplicate id, sender shared by two sources, invalid slug or sender, `forbidden` without a reason, LinkedIn with `page_fetch: allowed` (by sender or subdomain), unknown keys, duplicate YAML keys, non-mapping files, missing files, invalid `languages.postings`.
- Error output checked by hand: `email.sources[0] (LinkedIn Alerts).id: String should match pattern …`.
- No secrets, cost $0.
