# model-switch-notify skill

`skill/` is a Hermes agent skill that teaches an agent how to install, verify
and troubleshoot the `model-switch-notify` plugin — the component that reports
model-route changes (fallback switches, primary failures, recoveries) to the
active Feishu chat.

- `SKILL.md` — frontmatter (name, description, version) plus the operational
  workflow: install, configuration, verification, troubleshooting and removal.
- The plugin itself lives at the repository root (`model_switch_notify.py`,
  `plugin.yaml`); `SKILL.md` frontmatter `version` is tracked separately from
  `../plugin.yaml`.

## Deploy to a Hermes profile

```bash
./post-install.sh --profile <name>
```

The installer links the repository into `<profile>/plugins/model-switch-notify`,
links this directory into `<profile>/skills/devops/model-switch-notify`, and
enables the plugin.
