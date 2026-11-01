---
name: model-switch-notify
description: Install and operate Feishu model-switch alerts.
version: 1.0.1
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
keeps the home it was started with — restart it with the same home (or
`--profile <name>`) after installing elsewhere. Drop `-p <name>` for the
default profile.

The profile `.env` must carry `FEISHU_APP_ID` and `FEISHU_APP_SECRET`
(`FEISHU_DOMAIN=lark` for Lark tenants). The bot must already be in the target
chat.

A new enable hot-reloads plugin hooks. When replacing code, delete
`__pycache__/` first and reload, or restart the gateway with `/restart`.

## Behaviour

| Event | Message |
| --- | --- |
| Route changed | `⚠️ 模型已切换` — cause, old route, new route, time |
| Primary failed, retried OK | `🔴 主模型调用失败` + `已自动重试成功` |
| Primary failed, no switch | `🔴 主模型调用失败` after the hold window |
| Back on the configured primary | `🟢 已切回主模型` |

An error arriving before a switch is merged into the switch message. Identical
switches are de-duplicated for 60s; the marker resets after a recovery.

## Configure

Profile `.env` variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MODEL_WATCH_ENABLED` | `1` | Master switch |
| `MODEL_WATCH_DRY_RUN` | `0` | Log instead of sending |
| `MODEL_WATCH_RATE_PER_MIN` | `10` | Per-session per-minute budget |
| `MODEL_WATCH_ERROR_HOLD_SECONDS` | `8` | Merge window before a lone error is sent |
| `MODEL_WATCH_FORCE_CHAT` | empty | Force a chat id (`oc_…`); bypasses platform gating — testing only |

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

| Symptom | Action |
| --- | --- |
| No notification | `hermes -p <name> plugins info`; reload with disable/enable or `/restart` |
| Edits ignored | `rm -rf <plugin>/__pycache__` — a stale `.pyc` shadows the source |
| Old version reported | A `plugins/*.bak.*` copy shadows the symlink; move it to `<profile>/plugin-backups/` and reload |
| `HTTP 400 invalid receive_id` | The target was a session id, not a chat id; only `source=feishu` rows with an `oc_`/`ou_`/`on_` prefix are valid |
| CLI runs silent | Expected: one-shot sessions have `platform=cli` and no Feishu target |
| Duplicate end-of-turn notice | Hermes' built-in fallback notice still fires; optionally set `suppress_warning_notifications: true` for feishu |

## Uninstall

```bash
hermes -p <name> plugins disable model-switch-notify
rm <profile>/plugins/model-switch-notify      # symlink only
rm <profile>/skills/devops/model-switch-notify
```
