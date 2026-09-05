#!/usr/bin/env bash
# SessionStart hook: tell the agent, once per session, when this plugin's Bash guard is
# running degraded.
#
# block-glab-ci-direct.sh decides with `bash-classify match`. Without bash-classify it
# falls back to matching raw command text, which wrongly denies commands that only mention
# `glab` in prose; with a version below 0.11.0 it runs match mode but cannot resolve glab's
# deprecated `pipe`/`pipeline` aliases, so those spellings are not caught. A PreToolUse
# hook cannot say anything while allowing — only a deny reason reaches the model — so the
# advice has to be injected here instead.
#
# Prints nothing when bash-classify is present and new enough. Always exits 0.

set -uo pipefail

MIN_VERSION="0.11.0"
MATCH_VERSION="0.10.0"

if ! command -v jq >/dev/null 2>&1; then
  exit 0
fi

# Same discovery as block-glab-ci-direct.sh.
BC=""
if command -v bash-classify >/dev/null 2>&1; then
  BC="bash-classify"
elif [ -x "$HOME/.local/bin/bash-classify" ]; then
  BC="$HOME/.local/bin/bash-classify"
fi

# advise FOUND CONSEQUENCE INSTALL_COMMAND
advise() {
  local context
  context="The glab-pipeline Claude Code plugin guards Bash calls with \`bash-classify match\`, which needs bash-classify >= $MIN_VERSION, but $1. Until that is fixed $2. Tell the user about this and offer to run: $3"
  jq -n --arg ctx "$context" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $ctx
    }
  }'
  exit 0
}

TEXT_FALLBACK="the plugin's PreToolUse hook falls back to matching raw command text, so it can wrongly block a command that only mentions \`glab\` — a heredoc, a commit message, a \`grep\` pattern — and it cannot resolve glab's deprecated \`pipe\`/\`pipeline\` aliases either"
ALIASES_ONLY="the plugin's PreToolUse hook still matches parsed commands, but it cannot resolve glab's deprecated \`pipe\`/\`pipeline\` aliases, so \`glab pipeline view\` and \`glab pipe get\` are not caught"

if [ -z "$BC" ]; then
  advise "it is not installed" "$TEXT_FALLBACK" "\`uv tool install bash-classify\`"
fi

RAW=$("$BC" --version 2>/dev/null | head -1) || RAW=""
VERSION=$(printf '%s' "$RAW" | awk '{print $2}')

# An unknown version is treated as too old: the hook cannot prove otherwise.
case "$VERSION" in
  '' | *[!0-9.]*)
    advise "its version could not be read" "$TEXT_FALLBACK" "\`uv tool install --force bash-classify\`"
    ;;
esac

version_ge() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]
}

if ! version_ge "$VERSION" "$MIN_VERSION"; then
  if version_ge "$VERSION" "$MATCH_VERSION"; then
    advise "the installed bash-classify $VERSION is outdated" "$ALIASES_ONLY" "\`uv tool install --force bash-classify\`"
  fi
  advise "the installed bash-classify $VERSION is outdated" "$TEXT_FALLBACK" "\`uv tool install --force bash-classify\`"
fi

exit 0
