# Changelog

All notable changes to this project are documented here. Headings are dates
(`## YYYY-MM-DD`), not version numbers.

## 2026-11-09

### 0.2.1 — distinguish transport timeouts from watchdog kills

- Timeout notices no longer pair a short observed wait with the configured
  stale-stream budget. A transport failure arriving before that budget now
  reports the exception class (`timeout (waited 31.7s; transport: ReadTimeout)`)
  instead of implying the 180s watchdog fired; the watchdog copy is kept only
  when the observed wait reached the configured budget.
- The API error hook retains only the exception class, never the upstream error
  message, so provider payloads and credentials cannot reach a Feishu notice.
- Added `timeout_detail_transport` to all four locales; the existing i18n
  key-set test covers parity.
- The test suite no longer reads the developer's real Hermes profile or an
  exported `HERMES_STREAM_STALE_TIMEOUT`, so a machine-specific stale budget can
  no longer flip the timeout-copy assertions that assert the 180s default.

## 2026-11-06

### 0.2.0 — localization and config.toml

- Notice copy is localized into English, Simplified Chinese and Traditional
  Chinese in both Taiwan and Hong Kong variants (18 message keys in
  `locales/*.json`). English is the default; set `[notify] language` to
  `zh-CN`, `zh-TW`, `zh-HK` or `auto`. The Taiwan and Hong Kong files keep
  local vocabulary (呼叫/通話, 本輪/本次) rather than a mechanical script
  conversion, and `zh-HK` falls back through `zh-TW`.
- `auto` follows the profile `ui.language`, then `LC_ALL`/`LC_MESSAGES`/`LANG`,
  then English. Unknown languages and missing keys fall back through
  `zh-TW -> zh-CN -> en`.
- All runtime settings moved to `config.toml` (`enabled`, `dry_run`,
  `rate_per_min`, `error_hold_seconds`, `force_chat`, `language`). The
  `MODEL_WATCH_*` environment variables still override the file; an invalid
  override now falls through to the config value instead of reverting to the
  built-in default.
- The installer bootstraps `config.toml` from `config.example.toml` only when it
  is absent; the file is gitignored.
- Timeout notices now show the observed wait and the watchdog budget, e.g.
  `timeout (waited 180.4s; watchdog 180s)`.

### 1.1.0 — skill

- Documents the config file, language selection and the timeout detail.

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
  `-p <name>` so they operate on the profile that was installed, and the
  installer's printed check command carries the selected `HERMES_HOME`.
- Setup may run from an installed plugin directory as well as from the
  repository checkout.
- Replacing a real plugin directory now moves the old copy to
  `<profile>/plugin-backups/` instead of `plugins/*.bak.*`: Hermes scans every
  directory under `plugins/`, and a sibling backup with the same manifest name
  silently won discovery (the gateway kept loading the stale copy). Existing
  in-tree backups are reported, never deleted.
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
