# model-switch-notify plugin

Reference for installing, configuring and operating the plugin. For the short
version see `README.md`; for repository conventions see `AGENTS.md`.

## Requirements

- Hermes Agent with a Feishu bot configured for the target profile.
- Profile `.env` carrying `FEISHU_APP_ID`, `FEISHU_APP_SECRET` and, for Lark
  tenants, `FEISHU_DOMAIN=lark`.
- The bot must already be a member of the target chat (the DM chat with the
  bot, or a group it was added to).

## Install

Two supported layouts:

**Symlinked checkout (development, recommended for this repo)**

```bash
./post-install.sh --profile coder
```

The script:

1. links this repository to `<profile>/plugins/model-switch-notify`
   (an existing real directory is moved to `model-switch-notify.bak.<ts>`),
2. links `skill/` to `<profile>/skills/devops/model-switch-notify`,
3. enables the plugin in the profile config,
4. prints the verification commands.

**Hermes-managed install (release)**

```bash
hermes plugins install shijistar/hermes-model-switch-notify-plugin --enable
# or, from the installed plugin dir:
./post-install.sh --hermes-home "$HERMES_HOME"
```

Verify:

```bash
hermes plugins info model-switch-notify     # Status: enabled
hermes plugins list | grep model-switch
```

Runtime state is only registered on plugin load. A fresh enable hot-reloads the
hooks; after replacing code, reload with
`hermes plugins disable model-switch-notify && hermes plugins enable model-switch-notify`.
A full gateway restart (`/restart`) is the fallback when a reload reports that
previously wired hooks stay until restart.

## Configuration

Variables live in the profile `.env` (not `config.yaml`), so they are scoped to
the profile that runs the plugin.

| Variable | Default | Behaviour |
| --- | --- | --- |
| `MODEL_WATCH_ENABLED` | `1` | `0/false/no/off` disables both hooks |
| `MODEL_WATCH_DRY_RUN` | `0` | Log `would send` lines instead of calling Feishu |
| `MODEL_WATCH_RATE_PER_MIN` | `10` | Per-session sends per 60s; overflow is counted |
| `MODEL_WATCH_ERROR_HOLD_SECONDS` | `8` | How long an error waits for a switch before it is reported alone |
| `MODEL_WATCH_FORCE_CHAT` | empty | Force a chat id (`oc_…`) for testing; bypasses platform gating |

The primary route is read from the profile `config.yaml`:

```yaml
model:
  default: deepseek-v4.1-flash
  provider: opencode-go
```

A route counts as "primary" when the model matches after stripping any
`provider/` prefix and case, and the provider matches case-insensitively.

## Message contracts

| Event | Trigger | Message |
| --- | --- | --- |
| Switch | `post_api_request` reports a different route | `⚠️ 模型已切换` + cause + old/new route + time |
| Failure | `api_request_error` on the active route, no switch within the hold window | `🔴 主模型调用失败` (or `当前模型调用失败` when already on a fallback) |
| Retry recovered | same route succeeds after a held error | failure text + `已自动重试成功` |
| Recovery | route returns to the configured primary after an announced fallback | `🟢 已切回主模型` |

Merging: when a switch arrives inside the hold window, the failure text is not
sent separately; the switch message carries the cause and the failure count.

De-duplication: an identical `(from, to)` switch is sent at most once per 60s,
and the marker resets after a recovery so a new episode is always reported.
Identical failures are merged by the hold window instead of being de-duplicated.

Rate limiting: the 60s window is per session and shared by every message type.
Overflow increments a counter; the next delivered message ends with
`（期间另有 N 条通知被限流省略）`.

## How it works

```
post_api_request(model, provider, session_id, platform)
        │
        ├─ route unchanged ──► close a held error ("retry succeeded")
        └─ route changed ────► switch notice (merged with a held error)
                                   or recovery notice

api_request_error(status_code, reason, retryable, …)
        │
        └─ active route failed ──► hold the error, start a timer
```

- Chat resolution reads `sessions.chat_id` from the profile `state.db`; rows
  whose `source` is not `feishu` (CLI/one-shot runs) are rejected, as are ids
  without an `oc_`/`ou_`/`on_` prefix.
- The sender caches the tenant token until 60s before expiry and retries once
  with a fresh token when Feishu rejects it.
- All sends run on one daemon worker; the hook callbacks only enqueue.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| No messages at all | Plugin not loaded in the gateway | `hermes plugins info model-switch-notify`; reload or `/restart` |
| Code changes have no effect | A stale `__pycache__` next to the plugin | `rm -rf <plugin>/__pycache__`, then reload |
| `HTTP 400 … invalid receive_id` | Sending to a session id instead of a chat id | Check `sessions.source`; use a Feishu session or `MODEL_WATCH_FORCE_CHAT` |
| Nothing on CLI runs | By design: `platform=cli` has no Feishu target | Test from a Feishu chat |
| Duplicate notices at turn end | Hermes' built-in fallback notice still fires | Set `suppress_warning_notifications: true` for feishu in display config, or ignore |
| `FEISHU_APP_ID/SECRET missing` | Profile `.env` not found | Confirm `hermes -p <profile> config env-path` |

## Uninstall

```bash
hermes plugins disable model-switch-notify
rm -rf <profile>/plugins/model-switch-notify     # symlink only; the repo stays
```

Remove the skill symlink if it was installed:
`rm <profile>/skills/devops/model-switch-notify`.
