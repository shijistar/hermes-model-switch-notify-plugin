#!/usr/bin/env bash
#
# One-shot installer for the model-switch-notify Hermes plugin.
#
# Steps:
#   1. Optionally `hermes plugins install <this-repo> --enable` (--install-plugin).
#   2. Otherwise link this repository into the profile's plugins directory.
#      An existing real directory is moved aside, never deleted.
#   3. Link skill/ into <profile>/skills/devops/model-switch-notify.
#   4. Enable the plugin in the profile config.
#   5. Print verification commands.
#
# Usage:
#   ./post-install.sh [--hermes-home DIR] [--profile NAME] [--install-plugin]
#
# Defaults:
#   HERMES_HOME = $HOME/.hermes
#   profile     = derived from the path this script runs from, else the
#                 default profile (HERMES_HOME itself)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HERMES_HOME_ARG=""
PROFILE_ARG=""
INSTALL_PLUGIN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hermes-home)
      HERMES_HOME_ARG="$2"; shift 2 ;;
    --profile)
      PROFILE_ARG="$2"; shift 2 ;;
    --install-plugin)
      INSTALL_PLUGIN=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0"; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;34m[install]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- hermes home
if [[ -n "$HERMES_HOME_ARG" ]]; then
  HERMES_HOME="$HERMES_HOME_ARG"
elif [[ -n "${HERMES_HOME:-}" && -d "${HERMES_HOME}" ]]; then
  # An exported HERMES_HOME is the same value the plugin itself reads at
  # runtime; honor it so install and runtime agree on the target.
  HERMES_HOME="$HERMES_HOME"
elif [[ -d "$HOME/.hermes" ]]; then
  HERMES_HOME="$HOME/.hermes"
else
  die "Could not find a Hermes home; pass --hermes-home DIR"
fi
[[ -d "$HERMES_HOME" ]] || die "HERMES_HOME does not exist: $HERMES_HOME"

# ------------------------------------------------------------------- profile
PROFILE_DIR="$HERMES_HOME"
PROFILE_NAME=""
if [[ -n "$PROFILE_ARG" ]]; then
  PROFILE_DIR="$HERMES_HOME/profiles/$PROFILE_ARG"
  [[ -d "$PROFILE_DIR" ]] || die "Unknown profile: $PROFILE_ARG"
  PROFILE_NAME="$PROFILE_ARG"
elif [[ "$SCRIPT_DIR" == *"/profiles/"*"/plugins/"* ]]; then
  _derived="${SCRIPT_DIR%%/plugins/*}"
  _derived="${_derived##*/profiles/}"
  _derived="${_derived%%/*}"
  if [[ -d "$HERMES_HOME/profiles/$_derived" ]]; then
    PROFILE_DIR="$HERMES_HOME/profiles/$_derived"
    PROFILE_NAME="$_derived"
  fi
fi

PLUGIN_DIR="$PROFILE_DIR/plugins/model-switch-notify"
SKILL_LINK="$PROFILE_DIR/skills/devops/model-switch-notify"

# The selected profile must apply to *every* Hermes command below, including
# `plugins install` (it defaults to the currently active profile otherwise).
# With no --profile the links land in the default profile, so its commands
# must target it explicitly instead of whatever profile happens to be active.
profile_args=()
if [[ -n "$PROFILE_NAME" ]]; then
  profile_args=(-p "$PROFILE_NAME")
else
  profile_args=(-p default)
fi

info "HERMES_HOME = $HERMES_HOME"
info "Profile dir = $PROFILE_DIR"
info "Plugin src  = $SCRIPT_DIR"

mkdir -p "$PROFILE_DIR/plugins" "$PROFILE_DIR/skills/devops"

# ------------------------------------------------------------- 1. plugin
if [[ "$INSTALL_PLUGIN" -eq 1 ]]; then
  info "Installing with hermes plugins install ..."
  HERMES_HOME="$HERMES_HOME" hermes "${profile_args[@]}" plugins install "file://$SCRIPT_DIR" --enable
else
  script_real="$(cd "$SCRIPT_DIR" && pwd -P)"
  installed_real=""
  if [[ -e "$PLUGIN_DIR" || -L "$PLUGIN_DIR" ]]; then
    installed_real="$(cd "$PLUGIN_DIR" 2>/dev/null && pwd -P || true)"
  fi
  if [[ -n "$installed_real" && "$installed_real" == "$script_real" ]]; then
    # Running from the installed plugin directory itself: linking it onto
    # itself would create a self-referential or dangling symlink.
    ok "Plugin directory already is this checkout; keeping it"
  else
    if [[ -e "$PLUGIN_DIR" && ! -L "$PLUGIN_DIR" ]]; then
      BACKUP="$PLUGIN_DIR.bak.$(date +%Y%m%d-%H%M%S)"
      mv "$PLUGIN_DIR" "$BACKUP"
      ok "Moved existing plugin directory to $BACKUP (nothing deleted)"
    fi
    ln -sfn "$SCRIPT_DIR" "$PLUGIN_DIR"
    ok "Linked $PLUGIN_DIR -> $SCRIPT_DIR"
  fi
fi

# -------------------------------------------------------------- 2. skill
if [[ -L "$SKILL_LINK" ]]; then
  ln -sfn "$SCRIPT_DIR/skill" "$SKILL_LINK"
  ok "Refreshed skill link $SKILL_LINK"
elif [[ -e "$SKILL_LINK" ]]; then
  warn "$SKILL_LINK exists and is not a symlink; leaving it untouched"
else
  ln -s "$SCRIPT_DIR/skill" "$SKILL_LINK"
  ok "Linked skill $SKILL_LINK"
fi

# ------------------------------------------------------------- 3. enable
HERMES_HOME="$HERMES_HOME" hermes "${profile_args[@]}" plugins enable model-switch-notify

# ------------------------------------------------------------ 4. summary
printf '\033[1;32m\nInstall summary\033[0m\n'
printf '  Plugin:  %s\n' "$PLUGIN_DIR"
printf '  Skill:   %s\n' "$SKILL_LINK"
printf '\033[1;32m\nNext steps:\033[0m\n'
printf '  1. Run the tests:   python3 -m pytest tests/ -q\n'
printf '  2. Check the plugin: hermes plugins info model-switch-notify\n'
printf '  3. Ensure the profile .env has FEISHU_APP_ID / FEISHU_APP_SECRET.\n'
printf '  4. If hooks were wired by an older build, restart the gateway (/restart).\n'
