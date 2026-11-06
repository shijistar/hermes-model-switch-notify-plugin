---
name: model-switch-notify
description: Install and operate Feishu model-switch alerts.
version: 1.1.0
author: Hermes Agent / Fengbao Li
metadata:
  hermes:
    tags: [feishu, model-routing, fallback, notifications, hermes-plugin]
---

# Model Switch Notify

Install and operate the `model-switch-notify` Hermes plugin (source repo:
`hermes-model-switch-notify-plugin`). The plugin pushes a Feishu message to the
active chat whenever Hermes switches model routes mid-task, the primary model
fails, or the route recovers.

## When to Use

- The user asks to be told when Hermes falls back to another model.
- Installing, upgrading, or removing the plugin on a profile.
- Debugging "I never got a notification" reports.

## Install

```bash
cd <path-to-checkout>                  # wherever this repository was cloned
./post-install.sh --profile <name>     # default profile when --profile is omitted
hermes -p <name> plugins info model-switch-notify    # Status: enabled
```

`--hermes-home DIR` and an exported `HERMES_HOME` are honored, either as the
Hermes root or as a profile-scoped home (`<root>/profiles/<name>`), so the
install lands in the same home the plugin reads at runtime. A running gateway
keeps the home it was started with: restart it with the same `HERMES_HOME`
(custom root) and `-p <name>` (named profile) after installing elsewhere. Use
`-p default` for the default profile, and prefix
`HERMES_HOME=<hermes-home>` when the install used a custom root.

The profile `.env` must carry `FEISHU_APP_ID` and `FEISHU_APP_SECRET`
(`FEISHU_DOMAIN=lark` for Lark tenants). The bot must already be in the target
chat.

A new enable hot-reloads plugin hooks. When replacing code, delete
`__pycache__/` first and reload, or restart the gateway with `/restart`.

## Behaviour

Copy is localized (`en` by default, plus `zh-CN`, `zh-TW` and `zh-HK`); the table
shows the English text.

| Event                          | Message                                                    |
| ------------------------------ | ---------------------------------------------------------- |
| Route changed                  | `⚠️ Model switched` — cause, old route, new route, time    |
| Primary failed, retried OK     | `🔴 Primary model call failed` + `✅ Retried successfully` |
| Primary failed, no switch      | `🔴 Primary model call failed` after the hold window       |
| Back on the configured primary | `🟢 Switched back to the primary model`                    |

A timeout carries the observed wait and the watchdog budget, e.g.
`timeout (waited 180.4s; watchdog 180s)`; the budget comes from
`providers.<id>.stale_timeout_seconds`, else `HERMES_STREAM_STALE_TIMEOUT`,
else 180s.

An error arriving before a switch is merged into the switch message. Identical
switches are de-duplicated for 60s; the marker resets after a recovery.

## Configure

Settings live in `config.toml` next to the plugin. The installer creates it
from `config.example.toml` only when absent; it is not tracked by Git.

```toml
[notify]
enabled = true
dry_run = false
rate_per_min = 10
error_hold_seconds = 8.0
force_chat = ""
language = "en"      # en | zh-CN | zh-TW | zh-HK | auto
```

Environment variables override the file (useful for one-off debugging):

| Setting              | Env override                     | Default | Purpose                                                           |
| -------------------- | -------------------------------- | ------- | ----------------------------------------------------------------- |
| `enabled`            | `MODEL_WATCH_ENABLED`            | `true`  | Master switch                                                     |
| `dry_run`            | `MODEL_WATCH_DRY_RUN`            | `false` | Log instead of sending                                            |
| `rate_per_min`       | `MODEL_WATCH_RATE_PER_MIN`       | `10`    | Per-session per-minute budget                                     |
| `error_hold_seconds` | `MODEL_WATCH_ERROR_HOLD_SECONDS` | `8.0`   | Merge window before a lone error is sent                          |
| `force_chat`         | `MODEL_WATCH_FORCE_CHAT`         | empty   | Force a chat id (`oc_…`); bypasses platform gating — testing only |
| `language`           | `MODEL_WATCH_LANGUAGE`           | `en`    | Notice copy: `en`, `zh-CN`, `zh-TW`, `zh-HK` or `auto`            |

`auto` follows the profile `ui.language`, then `LC_ALL`/`LC_MESSAGES`/`LANG`,
then English. An unknown language falls back to `en`; a missing, unreadable or
malformed `config.toml` falls back to the defaults with a warning and never
raises inside a hook.

"Primary" is `model.default` + `model.provider` from the profile
`config.yaml`; the model comparison ignores a `provider/` prefix and case.

## Verify

```bash
python3 -m pytest tests/ -q          # offline, no network
hermes -p <name> plugins info model-switch-notify
```

End-to-end check without sending anything. A normal turn only produces a
notice when the route actually changes or a call fails, so force one switch
with a model that cannot exist (dry-run still resolves the target chat):

```bash
MODEL_WATCH_DRY_RUN=1 MODEL_WATCH_FORCE_CHAT=<oc_chat_id> \
  hermes -p <profile> -z "reply with exactly: ok" -m nonexistent-model-xyz
```

Then look for `model-switch-notify[dry-run]` lines in the agent log. To
confirm real delivery, run the same command without `MODEL_WATCH_DRY_RUN` and
check that the chat receives the notice.

## Troubleshooting

| Symptom                       | Action                                                                                                           |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| No notification               | `hermes -p <name> plugins info`; reload with disable/enable or `/restart`                                        |
| Edits ignored                 | `rm -rf <plugin>/__pycache__` — a stale `.pyc` shadows the source                                                |
| Old version reported          | A `plugins/*.bak.*` copy shadows the symlink; move it to `<profile>/plugin-backups/` and reload                  |
| `HTTP 400 invalid receive_id` | The target was a session id, not a chat id; only `source=feishu` rows with an `oc_`/`ou_`/`on_` prefix are valid |
| CLI runs silent               | Expected: one-shot sessions have `platform=cli` and no Feishu target                                             |
| Duplicate end-of-turn notice  | Hermes' built-in fallback notice still fires; optionally set `suppress_warning_notifications: true` for feishu   |

## Uninstall

```bash
hermes -p <name> plugins disable model-switch-notify
rm <profile>/plugins/model-switch-notify      # symlink only
rm <profile>/skills/devops/model-switch-notify
```
