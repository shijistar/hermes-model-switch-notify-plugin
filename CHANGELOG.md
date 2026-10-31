# Changelog

All notable changes to this project are documented here. Headings are dates
(`## YYYY-MM-DD`), not version numbers.

## 2026-10-31

### 0.1.0 — initial release

- Feishu notices for model-route changes, driven by the `post_api_request` and
  `api_request_error` hooks.
- Switch messages merge a preceding failure into one notice, carrying the HTTP
  status, failover reason and failure count.
- Failure notices report retries that recovered on the same route, and separate
  "current model" failures from primary-model failures.
- Recovery notices fire when the route returns to `model.default` +
  `model.provider`.
- Chat targeting resolves `session_id` through Hermes' `state.db` and rejects
  non-Feishu sources and ids without an `oc_`/`ou_`/`on_` prefix.
- Per-session rate window (10/min default) with a suppressed-count footer, plus
  60s switch de-duplication that resets after a recovery.
- Background delivery worker: hook callbacks never perform network I/O.
- Tenant-token caching, one retry on a rejected token, and truncated error
  bodies in logs.
