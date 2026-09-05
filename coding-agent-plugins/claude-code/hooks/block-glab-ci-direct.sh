#!/usr/bin/env bash
# PreToolUse hook: deny Bash commands that inspect pipelines, jobs or job logs directly
# through `glab`, and point the agent at the glab-pipeline CLI instead.
#
# The verdict comes from `bash-classify match`, which parses the expression and reports
# which of the shapes in blocked-commands.yaml it actually *invokes*. Text that merely
# names one of them — a heredoc body, an `echo` argument, a commit message, a `grep`
# pattern — is not an invocation and is allowed.
#
# When bash-classify cannot answer (not installed, too old, a parse warning, or a broken
# rules file), the hook falls back to the text patterns it used before. Those patterns
# over-block: they deny any command whose text contains a blocked phrase. Every deny
# issued from the fallback carries a note saying so, so the agent can tell the user.
#
# Never fails closed: a tooling problem degrades to the text patterns; it never denies everything.
# The one case decided before any of this is a missing `jq` — the script then exits 127
# without a verdict, exactly as it did before.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULES="$HERE/blocked-commands.yaml"
MIN_VERSION="0.11.0"

REASON="Direct \`glab\` pipeline inspection is blocked (matched: \`glab ci view|get|trace\`, or raw \`glab api projects/.../pipelines|jobs/.../trace|ci/lint\`). Use \`glab-pipeline inspect\` instead — it dumps full pipeline state (pipeline.json, jobs.json, per-job logs, lint, test report, downstream) and prints a problem-driven summary. Install with \`uv tool install glab-pipeline\`. Load the \`glab-pipeline\` skill for usage."

CMD=$(jq -r '.tool_input.command // empty')

if [ -z "$CMD" ]; then
  exit 0
fi

deny() {
  jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# Degraded mode: the pre-bash-classify text patterns, unchanged. They match the raw
# command text, so they also fire on text that only mentions a blocked command.
fallback() {
  local note="$1"
  if printf '%s' "$CMD" | grep -qE 'glab[[:space:]]+ci[[:space:]]+(view|get|trace)\b' \
    || printf '%s' "$CMD" | grep -qE 'glab[[:space:]]+api\b[^|;&]*projects/[^[:space:]]+/pipelines/' \
    || printf '%s' "$CMD" | grep -qE 'glab[[:space:]]+api\b[^|;&]*projects/[^[:space:]]+/jobs/[^[:space:]]+/trace' \
    || printf '%s' "$CMD" | grep -qE 'glab[[:space:]]+api\b[^|;&]*projects/[^[:space:]]+/ci/lint'; then
    deny "$REASON

Note: $note"
  fi
  exit 0
}

BC=""
if command -v bash-classify >/dev/null 2>&1; then
  BC="bash-classify"
elif [ -x "$HOME/.local/bin/bash-classify" ]; then
  BC="$HOME/.local/bin/bash-classify"
fi

if [ -z "$BC" ]; then
  fallback "bash-classify is not installed, so this plugin's Bash guard runs in degraded text-pattern mode and can wrongly block a command that only mentions these commands in text. Tell the user and offer to run: \`uv tool install bash-classify\`."
fi

RC=0
OUT=$(printf '%s' "$CMD" | "$BC" match --rules "$RULES" 2>/dev/null) || RC=$?

if [ "$RC" -ne 0 ]; then
  fallback "bash-classify match failed (exit $RC); check the plugin's blocked-commands.yaml."
fi

# A pre-0.10.0 binary ignores the `match` argument, classifies stdin and exits 0, so the
# output shape — not the exit code — is what tells the two apart. Unreadable output is
# treated the same way: it cannot answer, so fall back.
#
# This detects "has no match mode at all", not "is older than MIN_VERSION": a 0.10.x binary
# answers in the right shape but does not resolve glab's `pipe`/`pipeline` aliases, so
# `glab pipeline view` slips through it. Comparing versions here is deliberately avoided —
# it would cost a `--version` call on every Bash tool use. A once-per-session check is the
# right place for it.
if ! printf '%s' "$OUT" | jq -e 'has("matches")' >/dev/null 2>&1; then
  FOUND=$("$BC" --version 2>/dev/null | head -1) || FOUND=""
  [ -n "$FOUND" ] || FOUND="the installed bash-classify"
  fallback "$FOUND is outdated; this plugin needs bash-classify >= $MIN_VERSION. Tell the user and offer to run: \`uv tool install --force bash-classify\`."
fi

# A parse warning means the expression could not be fully read, so an empty `matches`
# list proves nothing.
WARNINGS=$(printf '%s' "$OUT" | jq -r '.parse_warnings | length' 2>/dev/null) || WARNINGS=1
if [ "$WARNINGS" != "0" ]; then
  fallback "bash-classify could not fully parse this command, so a text pattern was used instead; the pattern can misfire on heredocs or quoted text that merely mentions these commands."
fi

# The count decides; the names are only for the message, so a match object without a
# `rule` key still denies.
COUNT=$(printf '%s' "$OUT" | jq -r '.matches | length' 2>/dev/null) || COUNT=""
case "$COUNT" in
  '' | *[!0-9]*)
    fallback "bash-classify match returned output this hook could not read; a text pattern was used instead."
    ;;
esac

if [ "$COUNT" -gt 0 ]; then
  MATCHED=$(printf '%s' "$OUT" | jq -r '[.matches[].rule // "unnamed"] | unique | join(", ")' 2>/dev/null) || MATCHED=""
  [ -n "$MATCHED" ] || MATCHED="unnamed"
  deny "$REASON (matched rule: $MATCHED)"
fi

exit 0
