# after-install.md

The plugin is installed. Finish setup with the bundled one-shot installer:

```bash
cd "$HERMES_HOME/plugins/model-switch-notify"
./post-install.sh --profile <name>
```

Without `--profile`, the script derives the profile from where it runs (an
installed plugin under `profiles/<name>/plugins/…`) and falls back to the
default profile.

What it does:

1. Links this repository into `<profile>/plugins/model-switch-notify` (an
   existing real directory is moved to `*.bak.<timestamp>`, never deleted).
2. Links `skill/` into `<profile>/skills/devops/model-switch-notify`.
3. Enables the plugin in the profile config.

Then confirm the profile `.env` carries `FEISHU_APP_ID` and `FEISHU_APP_SECRET`,
check `hermes plugins info model-switch-notify`, and restart the gateway
(`/restart`) if hooks were wired by an older build.

Verify the install with `python3 -m pytest tests/ -q`.
