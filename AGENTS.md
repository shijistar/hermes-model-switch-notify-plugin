# AGENTS.md

Working guide for humans and AI agents contributing to
**hermes-model-switch-notify-plugin** — a Hermes plugin that reports model-route
changes (fallback switches, primary failures, recoveries) to the active Feishu
chat in real time.

## Modules

| Path        | What it is                                                    | Key files                                |
| ----------- | ------------------------------------------------------------- | ---------------------------------------- |
| repo root   | Hermes plugin package: hook handlers, state machine, Feishu client | `__init__.py`, `model_switch_notify.py`, `plugin.yaml` |
| `tests/`    | Pytest suites (state machine, delivery, registration, profile detection) | `conftest.py`, `test_state_machine.py`, `test_delivery.py`, `test_plugin.py` |
| `skill/`    | Hermes agent skill for installing and operating the plugin    | `SKILL.md`, `README.md`                  |

The repository root **is** the plugin package: `plugin.yaml` and `__init__.py`
live at the top level, and `hermes plugins install` clones the whole repository.

## Directory layout

```
hermes-model-switch-notify-plugin/
├── AGENTS.md
├── CHANGELOG.md              # Version history (date headings)
├── README.md                 # Project overview and quick start
├── PLUGIN.md                 # Install / configuration / message contracts / troubleshooting
├── __init__.py               # Hermes entry point: register(ctx)
├── model_switch_notify.py    # Implementation
├── plugin.yaml               # Plugin metadata + version
├── post-install.sh           # Symlink installer (plugin + skill)
├── after-install.md          # Follow-up steps shown by `hermes plugins install`
├── requirements.txt          # Runtime dependencies (stdlib only)
├── requirements-dev.txt      # Test dependencies
├── tests/                    # pytest suites
└── skill/                    # Hermes agent skill
    ├── SKILL.md
    └── README.md
```

## Build & test

```bash
python3 -m pytest tests/ -q     # 44 tests, no network access
python3 -m pytest tests/ -v     # per-test detail
```

- `tests/conftest.py` injects the repository root into `sys.path`, so
  `import model_switch_notify` resolves to the module at the root.
- Every test starts from empty caches: `reset_state`, `reset_chat_cache`,
  `reset_env_cache`, `reset_primary_cache`, `reset_profile_home_cache`.
- Network is never exercised: tests monkeypatch `urllib.request.urlopen` or
  replace `_dispatch` with a recorder.

## Versioning rules

The project tracks module versions in **two** places. The CHANGELOG uses
**date headings** (`## YYYY-MM-DD`), not version numbers:

| Place           | Field                    | Current   |
| --------------- | ------------------------ | --------- |
| `plugin.yaml`   | `version`                | 0.1.0     |
| `skill/SKILL.md`| frontmatter `version`    | 1.0.0     |
| `CHANGELOG.md`  | `## YYYY-MM-DD` headings | 2026-10-31 |

Module versions are independent of each other and of the CHANGELOG.

### Git tags

Every module version bump MUST also create a tag of the form
`<type>@<version>` on the merge commit in `master`:

| Module | Tag prefix | Example         |
| ------ | ---------- | --------------- |
| plugin | `plugin@`  | `plugin@0.1.0`  |
| skill  | `skill@`   | `skill@1.0.0`   |

- Tag only the modules whose version actually changed.
- Tags are created on `master` **after** the PR is merged, never on the feature
  branch.
- A date tag `vYYYY-MM-DD` accompanies each new CHANGELOG heading; replace an
  existing tag for the same date by deleting and re-creating it on the newest
  merge commit.

## Mandatory rules

### 1. Unit tests are required

Every new feature or bug fix ships with tests covering the changed behaviour:

- State transitions and message composition → `tests/test_state_machine.py`
- Chat resolution, token handling, HTTP failures → `tests/test_delivery.py`
- Manifest, registration, profile detection, formatting → `tests/test_plugin.py`

Do not merge a change whose tests fail locally.

### 2. Version bumps + CHANGELOG updates

Any behaviour change MUST bump the version of every module it touches and add a
`## YYYY-MM-DD` entry to `CHANGELOG.md` (append to an existing entry for the
same date).

Docs-only changes need no version bump, but a changelog entry is encouraged when
user-visible.

### 3. Language

Documentation, code comments, docstrings, commit messages and PR text are
written in **English**. The exception is user-facing message literals sent to
Feishu (Chinese), which are product strings and must stay as-is.

## Git workflow

- Branch from the latest `master`: `feat/<slug>` or `fix/<slug>`. Never commit
  directly to `master`.
- Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`), scoped
  when useful (`fix(plugin):`).
- Push the feature branch, let the maintainer review, then open a PR with an
  English description.
- Never force-push or rewrite public history; prefer `revert` over
  `reset --hard`.

## Safety invariants

- **Secrets**: credentials come from the profile `.env`; never log or echo the
  app secret or tenant token. Error bodies are truncated and contain no tokens.
- **Addressing**: only send to a chat id resolved from Hermes' session store with
  `source=feishu` and an `oc_`/`ou_`/`on_` prefix. CLI/one-shot rows store the
  session id in `chat_id` and must be rejected.
- **Latency**: hook callbacks run on the turn thread. Keep them to memory
  operations and a queue put; never perform I/O inline.
- **Failure isolation**: a Feishu failure must never fail a turn — log and drop.
- **Noise**: every new message type must respect the per-session rate window and
  the de-duplication rules.

## Development pitfalls

- Hermes imports the plugin once per process. After editing, delete
  `__pycache__/` and reload the plugin; a stale `.pyc` silently keeps the old
  code alive.
- `hermes chat -q` runs inside the gateway process, so it exercises whatever
  build the gateway has loaded, not the working tree.
- `post_api_request` fires for every LLM call; the handler must stay in the
  microsecond range.
