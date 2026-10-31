# after-install.md

The plugin is installed. Finish setup with the bundled one-shot installer, run
from the repository checkout (not from inside an installed plugin directory):

```bash
cd <path/to/hermes-model-switch-notify-plugin>
./post-install.sh --profile <name>
```

Without `--profile` the script targets the default profile. The plugin is
linked into `<hermes-home>/plugins/model-switch-notify` (default profile) or
`<hermes-home>/profiles/<name>/plugins/model-switch-notify` (named profile).
`--hermes-home DIR` and an exported `HERMES_HOME` are both honored, so the
install lands in the same home the plugin reads at runtime.

What it does:

1. Links this repository into the profile's plugins directory (an existing
   real directory is moved to `*.bak.<timestamp>`, never deleted; a plugin
   directory that already is this checkout is left untouched).
2. Links `skill/` into the profile's `skills/devops/`.
3. Enables the plugin in the profile config, passing `-p <name>` to every
   Hermes command it runs.

Then confirm the profile `.env` carries `FEISHU_APP_ID` and `FEISHU_APP_SECRET`
(`FEISHU_DOMAIN=lark` for Lark tenants), check
`hermes plugins info model-switch-notify`, and restart the gateway
(`/restart`) if hooks were wired by an older build.

Verify the install with `python3 -m pytest tests/ -q`.
