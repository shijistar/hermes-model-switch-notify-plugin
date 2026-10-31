# hermes-model-switch-notify-plugin

A Hermes plugin that pushes a **real-time Feishu notice to the current chat**
whenever the model route changes during a task — a fallback switch, a failing
primary model, or a recovery back to the configured primary.

Hermes already knows when it falls back, but it buffers that notice and emits it
only at the end of the turn (`agent/turn_final_response.py`). A long task can
switch models several times before the user sees anything. This plugin watches
the per-call hooks and reports each event as it happens.

## Features

- **Switch notice** — old route, new route and the failure that caused it,
  merged into one message when an error is followed by a switch.
- **Failure notice** — the primary model errored but the turn kept going
  (retry succeeded or a switch is pending).
- **Recovery notice** — the route is back on `model.default` + `model.provider`.
- **Targets the current chat** — `session_id` is resolved through Hermes'
  `state.db`; CLI/one-shot sessions are skipped.
- **Bounded noise** — 60s de-duplication, a per-session rate window (10/min by
  default), and a suppressed-count footer instead of silently dropping.
- **Never blocks a turn** — hooks only touch memory and a queue (µs range);
  HTTP happens on one background worker.

## Requirements

- Hermes Agent with the Feishu platform configured for the target profile
  (`FEISHU_APP_ID`, `FEISHU_APP_SECRET`, optional `FEISHU_DOMAIN` in the
  profile `.env`).
- Python 3.10+ (stdlib only; PyYAML comes with Hermes and is used to read the
  profile config).

## Quick start

```bash
# From the repository root: symlink the plugin and its skill into a profile,
# then enable it (see PLUGIN.md for --install-plugin and --profile variants).
./post-install.sh

# Verify registration
hermes plugins info model-switch-notify

# Run the test suite
python3 -m pytest tests/ -q
```

The gateway hot-reloads plugin hooks, so a new install is usually active after
`hermes plugins enable model-switch-notify`. If hooks were already wired for an
older build, restart the gateway (`/restart` in chat).

## What the user sees

```
⚠️ 模型已切换
原因：HTTP 429 · rate_limit · 连续 2 次失败
原模型：deepseek-v4.1-flash（opencode-go）
现模型：stepfun/step-3.7-flash:free（nous）
时间：2026-10-31 19:20:03
```

```
🔴 主模型调用失败
模型：deepseek-v4.1-flash（opencode-go）
错误：HTTP 500 · server_error · 已自动重试成功
```

```
🟢 已切回主模型
模型：deepseek-v4.1-flash（opencode-go）
```

## Configuration

All settings are environment variables in the profile `.env` (see
`PLUGIN.md` for the full table):

| Variable | Default | Purpose |
| --- | --- | --- |
| `MODEL_WATCH_ENABLED` | `1` | Master switch |
| `MODEL_WATCH_DRY_RUN` | `0` | Log instead of sending |
| `MODEL_WATCH_RATE_PER_MIN` | `10` | Per-session send budget |
| `MODEL_WATCH_ERROR_HOLD_SECONDS` | `8` | Merge window for "error → switch" |
| `MODEL_WATCH_FORCE_CHAT` | empty | Override the target chat (testing) |

## Safety

- Credentials are read from the profile `.env` and never logged.
- Messages are sent to a chat id resolved from Hermes' own session store, and
  only when `source=feishu` with an `oc_`/`ou_`/`on_` prefix.
- Hook callbacks never raise into the turn: every network path is wrapped and a
  failed send is only logged.
- No writes outside the Hermes profile: no config files are modified at runtime.

## Development

```bash
python3 -m pytest tests/ -q     # 44 tests, no network
python3 -m pytest tests/ -v     # per-test detail
```

Layout and contribution rules live in `AGENTS.md`; runtime behaviour and
troubleshooting live in `PLUGIN.md`.

## Documentation map

| File | Contents |
| --- | --- |
| `README.md` | Overview, quick start, feature list |
| `PLUGIN.md` | Install, configuration, message contracts, troubleshooting |
| `AGENTS.md` | Repository layout, conventions, tests, versioning |
| `CHANGELOG.md` | Dated release notes |
| `skill/SKILL.md` | Agent-facing workflow for installing and operating the plugin |
