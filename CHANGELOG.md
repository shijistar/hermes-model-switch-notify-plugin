# Changelog

All notable changes to this project are documented here. Headings are dates
(`## YYYY-MM-DD`), not version numbers.

## 2026-11-01

### 0.1.1 — review follow-ups

- A 2xx response with an unparsable body is no longer retried: the server has
  already answered, so a resend could duplicate a notice Feishu accepted.
- The installer accepts a profile-scoped `HERMES_HOME`
  (`<root>/profiles/<name>`): it resolves the Hermes root instead of appending
  a second `profiles/<name>`, and the profile the home names is the one that
  gets enabled (previously it fell back to `-p default`).
- Docs state that installing into a non-default home does not move a running
  gateway: it keeps the home it was started with and must be restarted with the
  selected home to load the plugin.
- Verification, reload, troubleshooting and uninstall commands carry
  `-p <name>` so they operate on the profile that was installed.
- Setup may run from an installed plugin directory as well as from the
  repository checkout.
- New `tests/test_installer.py` covers root vs profile-scoped homes, explicit
  `--profile` precedence and the installed-directory layout.

### 1.0.1 — skill

- The skill's commands carry `-p <name>` and document profile-scoped
  `HERMES_HOME` plus the gateway-home requirement.

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
- Delivery retry policy: server errors and connection failures retry once;
  4xx rejections and timeouts are final (a resend could duplicate an accepted
  message — Lark has no idempotency key for sends).
- Concurrency and lifecycle hardening: the rate window mutates under the
  session lock, flush timers are cancelled when an error is consumed,
  per-session bookkeeping is capped (256, LRU), and a session that starts on a
  fallback route reports its return to the primary as a recovery.
- Failed lookups are never cached: a transient DB miss or an unreadable
  `config.yaml` is retried instead of pinning a wrong chat or primary route,
  and a session whose baseline came from the first observed route re-pins to
  the configured primary once the config reads.
- PyYAML is a declared runtime dependency (`requirements.txt`).
- The installer honors an exported `HERMES_HOME`, passes the selected profile
  to every Hermes command it runs, and never links a plugin directory onto
  itself.
