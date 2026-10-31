---
name: model-switch-notify
description: Install and operate Feishu model-switch alerts.
version: 1.0.0
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
cd ~/.hermes/workspace/repository/hermes-model-switch-notify-plugin
./post-install.sh --profile coder          # symlink + skill link + enable
hermes plugins info model-switch-notify    # Status: enabled
```

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
| `MODEL_WATCH_FORCE_CHAT` | empty | Force a target chat (testing) |

"Primary" is `model.default` + `model.provider` from the profile
`config.yaml`; the model comparison ignores a `provider/` prefix and case.

## Verify

```bash
python3 -m pytest tests/ -q          # 44 tests, no network
hermes plugins info model-switch-notify
```

End-to-end check without disturbing a live session: set
`MODEL_WATCH_DRY_RUN=1`, run one turn, and look for
`model-switch-notify[dry-run]` lines in the agent log. To confirm delivery,
send a test text through the profile bot to the chat id and check the returned
`message_id`.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| No notification | `hermes plugins info`; reload with disable/enable or `/restart` |
| Edits ignored | `rm -rf <plugin>/__pycache__` — a stale `.pyc` shadows the source |
| `HTTP 400 invalid receive_id` | The target was a session id, not a chat id; only `source=feishu` rows with an `oc_`/`ou_`/`on_` prefix are valid |
| CLI runs silent | Expected: one-shot sessions have `platform=cli` and no Feishu target |
| Duplicate end-of-turn notice | Hermes' built-in fallback notice still fires; optionally set `suppress_warning_notifications: true` for feishu |

## Uninstall

```bash
hermes plugins disable model-switch-notify
rm <profile>/plugins/model-switch-notify      # symlink only
rm <profile>/skills/devops/model-switch-notify
```
