#!/usr/bin/env bash
set -euo pipefail

CMD=$(jq -r '.tool_input.command // empty')

if [ -z "$CMD" ]; then
  exit 0
fi

REASON="Direct \`glab\` pipeline inspection is blocked (matched: \`glab ci view|get|trace\`, or raw \`glab api projects/.../pipelines|jobs/.../trace|ci/lint\`). Use \`glab-pipeline inspect\` instead — it dumps full pipeline state (pipeline.json, jobs.json, per-job logs, lint, test report, downstream) and prints a problem-driven summary. Install with \`uv tool install glab-pipeline\`. Load the \`glab-pipeline\` skill for usage."

if printf '%s' "$CMD" | grep -qE 'glab[[:space:]]+ci[[:space:]]+(view|get|trace)\b' \
  || printf '%s' "$CMD" | grep -qE 'glab[[:space:]]+api\b[^|;&]*projects/[^[:space:]]+/pipelines/' \
  || printf '%s' "$CMD" | grep -qE 'glab[[:space:]]+api\b[^|;&]*projects/[^[:space:]]+/jobs/[^[:space:]]+/trace' \
  || printf '%s' "$CMD" | grep -qE 'glab[[:space:]]+api\b[^|;&]*projects/[^[:space:]]+/ci/lint'; then
  jq -n --arg reason "$REASON" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
fi

exit 0
