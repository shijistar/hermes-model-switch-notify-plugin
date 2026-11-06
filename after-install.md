# after-install.md

The plugin is installed. Finish setup with the bundled one-shot installer. Run
it from the repository checkout or from an installed plugin directory — a
Hermes-managed install is a full checkout, and the script detects that the
plugin directory already is its own source:

```bash
cd <path/to/hermes-model-switch-notify-plugin>
./post-install.sh --profile <name>
```

Without `--profile` the script targets the default profile. The plugin is
linked into `<hermes-home>/plugins/model-switch-notify` (default profile) or
`<hermes-home>/profiles/<name>/plugins/model-switch-notify` (named profile).
`--hermes-home DIR` and an exported `HERMES_HOME` are both honored, in either
the root form or the profile-scoped form Hermes uses at runtime
(`<hermes-home>/profiles/<name>`), so the install lands in the same home the
plugin reads.

Choosing a home only decides where the files land; it does not move a gateway
that is already running. A gateway loads plugins from the home it was started
with, so when you install into a custom root, restart it with the same
`HERMES_HOME`; for a named profile, also pass `-p <name>`.

What it does:

1. Links this repository into the profile's plugins directory (an existing
   real directory is moved to `<profile>/plugin-backups/`, never deleted; a
   plugin directory that already is this checkout is left untouched).
2. Links `skill/` into the profile's `skills/devops/`.
3. Creates `config.toml` next to the plugin from `config.example.toml` when it
   is absent; an existing file is kept untouched. Review `[notify]` there —
   `language` defaults to `en`, and `zh-CN`/`zh-TW`/`auto` are also available.
4. Enables the plugin in the profile config, passing `-p <name>` to every
   Hermes command it runs.

Then confirm the profile `.env` carries `FEISHU_APP_ID` and `FEISHU_APP_SECRET`
(`FEISHU_DOMAIN=lark` for Lark tenants), check
`hermes -p <name> plugins info model-switch-notify` (`-p default` for the
default profile; prefix `HERMES_HOME=<hermes-home>` when the install used a
custom root), and restart the gateway (`/restart`) if hooks were wired by an
older build.

Verify the install with `python3 -m pytest tests/ -q`.
