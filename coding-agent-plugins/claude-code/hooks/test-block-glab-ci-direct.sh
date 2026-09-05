#!/usr/bin/env bash
# Test suite for block-glab-ci-direct.sh and check-bash-classify.sh.
#
# Every case is run in three environments, because the hook has to behave sensibly in all
# of them:
#
#   real  the installed bash-classify (>= MIN_VERSION, or whatever BASH_CLASSIFY_BIN points at)
#   old   a stub that answers like a pre-0.10.0 binary: no `matches` key in its output
#   none  no bash-classify on PATH and a HOME with no ~/.local/bin/bash-classify
#
# In `old` and `none` the hook falls back to the text patterns it used before. Those
# patterns are wrong in both directions: they deny shell text that merely *names* a blocked
# command, and they miss a real call they cannot see on one line — a continuation line, or
# glab's `pipe`/`pipeline` aliases the pattern never knew about. Those rows are not a bug
# in the test, they are the degraded behaviour being pinned, and every deny from the
# fallback has to carry a note telling the agent why.
#
# The SessionStart hook is checked in the same three environments — silent in `real`, and
# advising the agent in the other two — plus two more: a binary that answers `--version`
# with no version at all, and a 0.10.x that runs match mode but knows no aliases.
#
# Set BASH_CLASSIFY_BIN to test against a build that is not on PATH (an unreleased
# version, or a CI install in a non-standard prefix). The version gate is then skipped and
# `match --help` is used to prove the binary understands match mode.
#
# Exits non-zero if any case fails.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$HERE/block-glab-ci-direct.sh"
CHECK="$HERE/check-bash-classify.sh"
CASES="$HERE/test-cases"
MIN_VERSION="0.11.0"

if [ ! -x "$HOOK" ]; then
  echo "hook not executable: $HOOK" >&2
  exit 2
fi

if [ ! -x "$CHECK" ]; then
  echo "hook not executable: $CHECK" >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to run this test suite" >&2
  exit 2
fi

# ---------------------------------------------------------------- environments

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

ORIG_PATH="$PATH"
REAL_HOME="$HOME"

# PATH with every directory that holds a bash-classify removed.
clean_path() {
  local out="" dir
  local -a dirs
  IFS=: read -ra dirs <<< "$PATH"
  for dir in "${dirs[@]}"; do
    [ -n "$dir" ] || continue
    [ -e "$dir/bash-classify" ] && continue
    out="${out:+$out:}$dir"
  done
  printf '%s' "$out"
}
CLEAN_PATH=$(clean_path)

mkdir -p "$TMP/home-empty" "$TMP/bin-old"
cat > "$TMP/bin-old/bash-classify" <<'STUB'
#!/usr/bin/env bash
# Stands in for a pre-0.10.0 bash-classify: it does not know the `match` subcommand, so it
# ignores the arguments, classifies stdin and exits 0 — with no `matches` key in sight.
if [ "${1:-}" = "--version" ]; then
  echo "bash-classify 0.9.1"
  exit 0
fi
cat > /dev/null
cat <<'JSON'
{"expression":"...","classification":"EXTERNAL_EFFECTS","risk":"MEDIUM","directories":[],"write_paths":[],"read_paths":[],"commands":[],"redirects":[],"parse_warnings":[]}
JSON
STUB
chmod +x "$TMP/bin-old/bash-classify"

mkdir -p "$TMP/bin-badversion"
cat > "$TMP/bin-badversion/bash-classify" <<'STUB'
#!/usr/bin/env bash
# A binary whose --version output carries no version number. Unknown is not "new enough".
if [ "${1:-}" = "--version" ]; then
  echo "bash-classify (development build)"
  exit 0
fi
cat > /dev/null
echo '{"matches":[],"parse_warnings":[]}'
STUB
chmod +x "$TMP/bin-badversion/bash-classify"

mkdir -p "$TMP/bin-nomatch-aliases"
cat > "$TMP/bin-nomatch-aliases/bash-classify" <<'STUB'
#!/usr/bin/env bash
# A 0.10.x: full match mode, but no subcommand aliases. The PreToolUse hook cannot tell it
# from a current one; only the SessionStart check can, by comparing versions.
if [ "${1:-}" = "--version" ]; then
  echo "bash-classify 0.10.0"
  exit 0
fi
cat > /dev/null
echo '{"matches":[],"parse_warnings":[]}'
STUB
chmod +x "$TMP/bin-nomatch-aliases/bash-classify"

version_ge() {
  [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" = "$2" ]
}

# `real` runs with bash-classify first on PATH. With an override that is a symlink to the
# given binary, prepended to the *full* PATH — the override may be a wrapper that needs the
# rest of the environment (`uv`, for one) to still be reachable.
if [ -n "${BASH_CLASSIFY_BIN:-}" ]; then
  if [ ! -x "$BASH_CLASSIFY_BIN" ]; then
    echo "BASH_CLASSIFY_BIN is not an executable: $BASH_CLASSIFY_BIN" >&2
    exit 2
  fi
  if ! "$BASH_CLASSIFY_BIN" match --help >/dev/null 2>&1; then
    echo "BASH_CLASSIFY_BIN does not understand 'match': $BASH_CLASSIFY_BIN" >&2
    exit 2
  fi
  mkdir -p "$TMP/bin-real"
  ln -sf "$(cd "$(dirname "$BASH_CLASSIFY_BIN")" && pwd)/$(basename "$BASH_CLASSIFY_BIN")" "$TMP/bin-real/bash-classify"
  REAL_PATH="$TMP/bin-real:$ORIG_PATH"
  echo "real mode: BASH_CLASSIFY_BIN=$BASH_CLASSIFY_BIN (version gate skipped)"
  echo
else
  if ! command -v bash-classify >/dev/null 2>&1; then
    echo "bash-classify is not installed; the 'real' mode cannot run." >&2
    echo "install it with: uv tool install bash-classify" >&2
    echo "or point BASH_CLASSIFY_BIN at a build of it." >&2
    exit 2
  fi
  FOUND_VERSION=$(bash-classify --version 2>/dev/null | awk '{print $2}')
  if [ -z "$FOUND_VERSION" ] || ! version_ge "$FOUND_VERSION" "$MIN_VERSION"; then
    echo "bash-classify ${FOUND_VERSION:-<unknown>} is too old; this suite needs >= $MIN_VERSION" >&2
    echo "upgrade it with: uv tool install --force bash-classify" >&2
    echo "or point BASH_CLASSIFY_BIN at a newer build." >&2
    exit 2
  fi
  REAL_PATH="$ORIG_PATH"
fi

# ---------------------------------------------------------------- case runner

MODE=""
pass=0
fail=0
mode_fail=0

# _check EXPECT COMMAND LABEL
#
# EXPECT is ALLOW, BLOCK, or BLOCK+<substring the deny reason must contain>.
_check() {
  local expect="$1" cmd="$2" label="$3"
  local want_note="" out rc got reason problem=""

  case "$expect" in
    BLOCK+*)
      want_note="${expect#BLOCK+}"
      expect="BLOCK"
      ;;
  esac

  out=$(jq -nc --arg c "$cmd" '{tool_input:{command:$c}}' | "$HOOK" 2>/dev/null)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    problem="hook exited $rc (it must always exit 0)"
  fi

  if [ -n "$out" ]; then got=BLOCK; else got=ALLOW; fi
  if [ "$got" != "$expect" ]; then
    problem="${problem:+$problem; }expected $expect"
  fi

  if [ "$got" = "BLOCK" ] && [ -z "$problem" ]; then
    reason=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecisionReason // ""' 2>/dev/null)
    if [ -n "$want_note" ]; then
      case "$reason" in
        *"$want_note"*) ;;
        *) problem="deny reason does not mention '$want_note'" ;;
      esac
    else
      case "$MODE" in
        real)
          case "$reason" in
            *"(matched rule:"*) ;;
            *) problem="${problem:+$problem; }deny reason does not name the matched rule" ;;
          esac
          case "$reason" in
            *"Note:"*) problem="${problem:+$problem; }deny in real mode carries a degraded-mode note" ;;
          esac
          ;;
        old)
          case "$reason" in
            *"is outdated"*"uv tool install --force bash-classify"*) ;;
            *) problem="deny reason does not tell the agent bash-classify is outdated" ;;
          esac
          ;;
        none)
          case "$reason" in
            *"is not installed"*"uv tool install bash-classify"*) ;;
            *) problem="deny reason does not tell the agent bash-classify is missing" ;;
          esac
          ;;
      esac
    fi
  fi

  if [ -z "$problem" ]; then
    pass=$((pass + 1))
    printf '[ok]   %-5s %-6s | %s\n' "$MODE" "$got" "$label"
  else
    fail=$((fail + 1))
    mode_fail=$((mode_fail + 1))
    printf '[FAIL] %-5s %-6s | %s\n       %s\n' "$MODE" "$got" "$label" "$problem"
  fi
}

# _session_check EXPECT
#
# EXPECT is QUIET (no output at all) or SAY+<substring the additionalContext must carry>.
_session_check() {
  local expect="$1" want="" out rc ctx problem=""

  case "$expect" in
    SAY+*)
      want="${expect#SAY+}"
      expect="SAY"
      ;;
  esac

  out=$("$CHECK" 2>/dev/null)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    problem="hook exited $rc (it must always exit 0)"
  fi

  if [ "$expect" = "QUIET" ]; then
    [ -n "$out" ] && problem="${problem:+$problem; }expected no output, got: $out"
  elif [ -z "$out" ]; then
    problem="${problem:+$problem; }expected advice mentioning '$want', got no output"
  else
    ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null)
    if [ "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.hookEventName // ""' 2>/dev/null)" != "SessionStart" ]; then
      problem="${problem:+$problem; }output is not a SessionStart hookSpecificOutput"
    else
      case "$ctx" in
        *"$want"*) ;;
        *) problem="${problem:+$problem; }advice does not mention '$want'" ;;
      esac
    fi
  fi

  if [ -z "$problem" ]; then
    pass=$((pass + 1))
    printf '[ok]   %-5s %-6s | %s\n' "$MODE" "$expect" "check-bash-classify.sh"
  else
    fail=$((fail + 1))
    mode_fail=$((mode_fail + 1))
    printf '[FAIL] %-5s %-6s | %s\n       %s\n' "$MODE" "$expect" "check-bash-classify.sh" "$problem"
  fi
}

# run_case EXPECT_REAL EXPECT_OLD EXPECT_NONE COMMAND
run_case() {
  local expect
  case "$MODE" in
    real) expect="$1" ;;
    old) expect="$2" ;;
    none) expect="$3" ;;
  esac
  _check "$expect" "$4" "$4"
}

# run_file EXPECT_REAL EXPECT_OLD EXPECT_NONE RELATIVE_PATH
run_file() {
  local expect cmd
  case "$MODE" in
    real) expect="$1" ;;
    old) expect="$2" ;;
    none) expect="$3" ;;
  esac
  if [ ! -f "$CASES/$4" ]; then
    echo "[FAIL] missing test case file: $CASES/$4"
    fail=$((fail + 1))
    mode_fail=$((mode_fail + 1))
    return
  fi
  cmd=$(cat "$CASES/$4")
  _check "$expect" "$cmd" "$4"
}

# ---------------------------------------------------------------- the cases

all_cases() {
  #         real   old    none   command
  # ---------------- glab ci view|get|trace ----------------
  run_case BLOCK BLOCK BLOCK 'glab ci view 1000 2>&1 | head -50'
  run_case BLOCK BLOCK BLOCK 'glab ci view --help'
  run_case BLOCK BLOCK BLOCK 'glab ci view lint --web'
  run_case BLOCK BLOCK BLOCK 'glab ci get --with-job-details -F json'
  run_case BLOCK BLOCK BLOCK 'glab ci get -R group/project --with-job-details'
  run_case BLOCK BLOCK BLOCK 'glab ci trace 2000 > /tmp/work/ci-job-2000.log 2>&1'
  run_case BLOCK BLOCK BLOCK 'glab ci trace deploy-test -p 1000 -R group/project'
  run_case BLOCK BLOCK BLOCK 'glab ci trace --pipeline-id 1000 tests-app'

  # ---------------- raw API: pipelines, job traces, ci/lint ----------------
  run_case BLOCK BLOCK BLOCK 'glab api "projects/:id/pipelines/1000/jobs?per_page=100"'
  run_case BLOCK BLOCK BLOCK 'glab api "projects/group%2Fproject/pipelines/1000"'
  run_case BLOCK BLOCK BLOCK 'GITLAB_HOST=gitlab.example.com glab api "projects/42/pipelines/1000"'
  run_case BLOCK BLOCK BLOCK 'glab api projects/42/pipelines/1000 --hostname gitlab.example.com'
  run_case BLOCK BLOCK BLOCK 'glab api "projects/group%2Fproject/jobs/2000/trace" > /tmp/work/job.log'
  run_case BLOCK BLOCK BLOCK 'glab api "projects/42/jobs/2000/trace" 2>/dev/null | grep -i "test-env"'
  run_case BLOCK BLOCK BLOCK 'glab api -X POST projects/group%2Fproject/ci/lint --input lint-payload.json'
  run_case BLOCK BLOCK BLOCK 'glab api --method POST projects/:id/ci/lint --field "content=x"'

  # ---------------- wrappers do not launder a blocked command ----------------
  run_case BLOCK BLOCK BLOCK 'sudo glab ci trace 2000'
  run_case BLOCK BLOCK BLOCK 'timeout 60 glab api "projects/:id/pipelines/1000/jobs"'
  run_case BLOCK BLOCK BLOCK 'bash -c "glab ci get -F json"'
  run_case BLOCK BLOCK BLOCK 'xargs -I{} glab api "projects/:id/jobs/{}/trace" < ids.txt'
  run_case BLOCK BLOCK BLOCK '/usr/bin/glab api "projects/:id/pipelines/1000"'

  # ---------------- glab's own deprecated aliases for `ci` ----------------
  # bash-classify >= 0.11.0 resolves `pipe`/`pipeline` to `ci`, so the three-word rules
  # catch them with no rule of their own. The old text pattern never knew the aliases,
  # so degraded mode lets them through — a gap, documented here rather than papered over.
  run_case BLOCK ALLOW ALLOW 'glab pipeline trace 2000'
  run_file BLOCK ALLOW ALLOW block/pipeline-view-alias.sh
  run_file BLOCK ALLOW ALLOW block/pipe-get-alias.sh

  # An expression the parser cannot fully read: `matches` proves nothing, so the hook has
  # to fall back and say so.
  run_case 'BLOCK+could not fully parse' BLOCK BLOCK 'eval "glab ci trace $(("'

  # ---------------- allowed glab ci commands ----------------
  run_case ALLOW ALLOW ALLOW 'glab ci list 2>&1 | head -10'
  run_case ALLOW ALLOW ALLOW 'glab ci list --per-page 8'
  run_case ALLOW ALLOW ALLOW 'glab ci status --compact'
  run_case ALLOW ALLOW ALLOW 'glab ci status --pipeline-id 1000'
  run_case ALLOW ALLOW ALLOW 'glab ci lint .gitlab-ci.yml 2>&1 | tail -5'

  # ---------------- allowed glab api calls ----------------
  # The pipelines LIST endpoint has no id segment after `pipelines`, so neither the rule
  # nor the pattern fires.
  run_case ALLOW ALLOW ALLOW 'glab api "projects/:id/pipelines?ref=feature/branch&per_page=1" | jq'
  run_case ALLOW ALLOW ALLOW "glab api 'projects/alice%2Fproject-test/pipelines?ref=master&per_page=1'"
  run_case ALLOW ALLOW ALLOW 'glab api "projects/group%2Fproject/merge_requests/123/pipelines"'
  run_case ALLOW ALLOW ALLOW 'glab api projects/:id/jobs/2000 2>/dev/null | jq -r ".name"'

  # ---------------- unrelated commands ----------------
  run_case ALLOW ALLOW ALLOW 'glab-pipeline inspect --pipeline-id 1000'
  run_case ALLOW ALLOW ALLOW 'glab-discussion read --dump'
  run_case ALLOW ALLOW ALLOW 'git status'
  run_case ALLOW ALLOW ALLOW 'jq ".[] | {id}" /tmp/work/jobs.json'
  run_case ALLOW ALLOW ALLOW 'glab auth status'
  run_case ALLOW ALLOW ALLOW ''

  # ---------------- text that only mentions a blocked command ----------------
  run_case ALLOW BLOCK BLOCK 'echo "do not use glab ci get, use glab-pipeline inspect"'
  run_case ALLOW BLOCK BLOCK "printf '%s\\n' 'glab ci trace is blocked; run glab-pipeline inspect'"
  run_case ALLOW BLOCK BLOCK "grep -rn 'glab ci view\\|glab ci get\\|glab ci trace' docs/"
  run_case ALLOW BLOCK BLOCK "git commit -m \"Block 'glab ci trace' in PreToolUse hook\" && git log --oneline -1"
  run_case ALLOW BLOCK BLOCK 'for cmd in "glab ci list" "glab ci view 1000" "glab ci trace 2000"; do echo "$cmd"; done'
  # A pattern the text matcher cannot read as a command, so even degraded mode allows it.
  run_case ALLOW ALLOW ALLOW "rg --no-messages -l -e 'glab ci (view|get|trace)' -g '*.jsonl' . | wc -l"

  # ---------------- multi-line cases, one per file ----------------
  run_file BLOCK BLOCK BLOCK block/api-pipeline-jobs-comment-and-loop.sh
  run_file BLOCK BLOCK BLOCK block/api-pipeline-jobs-nested-loop-timeout.sh
  run_file BLOCK BLOCK BLOCK block/api-pipeline-status-poll-loop.sh
  run_file BLOCK BLOCK BLOCK block/ci-get-var-capture-poll-loop.sh
  run_file BLOCK BLOCK BLOCK block/ci-get-then-ci-trace.sh
  run_file BLOCK BLOCK BLOCK block/heredoc-then-pipe-to-blocked.sh
  run_file BLOCK BLOCK BLOCK block/api-ci-lint-continuation-lines.sh
  # The endpoint sits on its own continuation line, so the line-based pattern never sees a
  # `glab api` and a path together. Parsing does.
  run_file BLOCK ALLOW ALLOW block/api-pipeline-test-report.sh

  run_file ALLOW BLOCK BLOCK allow/heredoc-brief-mentions-ci-commands.sh
  run_file ALLOW BLOCK BLOCK allow/heredoc-skill-mentions-ci.sh
  run_file ALLOW BLOCK BLOCK allow/git-commit-heredoc-message.sh
  run_file ALLOW BLOCK BLOCK allow/comment-only-mention.sh
  run_file ALLOW ALLOW ALLOW allow/api-merge-request-pipelines-list-per-page.sh
}

# ---------------------------------------------------------------- run

for MODE in real old none; do
  case "$MODE" in
    real)
      PATH="$REAL_PATH"
      HOME="$REAL_HOME"
      ;;
    old)
      PATH="$TMP/bin-old:$CLEAN_PATH"
      HOME="$TMP/home-empty"
      ;;
    none)
      PATH="$CLEAN_PATH"
      HOME="$TMP/home-empty"
      ;;
  esac
  export PATH HOME

  mode_fail=0
  echo "================ mode: $MODE ================"
  all_cases
  case "$MODE" in
    real) _session_check QUIET ;;
    old) _session_check 'SAY+is outdated' ;;
    none) _session_check 'SAY+it is not installed' ;;
  esac
  echo "---------------- mode $MODE: $([ "$mode_fail" -eq 0 ] && echo "all cases passed" || echo "$mode_fail failed")"
  echo
done

PATH="$ORIG_PATH"
HOME="$REAL_HOME"
export PATH HOME

# ---------------------------------------------------------------- version-only checks

# Two states the PreToolUse hook cannot see, because both answer `match` in the right
# shape. Only the SessionStart check, which compares versions, catches them.
echo "================ mode: version-checks ================"
mode_fail=0
HOME="$TMP/home-empty"

MODE="badver"
PATH="$TMP/bin-badversion:$CLEAN_PATH"
export PATH HOME
_session_check 'SAY+version could not be read'

MODE="0.10.x"
PATH="$TMP/bin-nomatch-aliases:$CLEAN_PATH"
export PATH HOME
_session_check 'SAY+aliases'

PATH="$ORIG_PATH"
HOME="$REAL_HOME"
export PATH HOME
echo

# ---------------------------------------------------------------- broken rules file

# A rules file the tool refuses is a plugin bug, not something the agent can fix. The hook
# still has to fall back rather than let everything through.
echo "================ mode: broken-rules ================"
MODE="broken"
mkdir -p "$TMP/broken"
cp "$HOOK" "$TMP/broken/"
printf 'rules:\n  - name: no-command-key\n' > "$TMP/broken/blocked-commands.yaml"
BROKEN_HOOK="$TMP/broken/$(basename "$HOOK")"

broken_case() {
  local expect="$1" cmd="$2" out got reason problem=""
  out=$(jq -nc --arg c "$cmd" '{tool_input:{command:$c}}' | "$BROKEN_HOOK" 2>/dev/null)
  if [ -n "$out" ]; then got=BLOCK; else got=ALLOW; fi
  if [ "$got" != "$expect" ]; then
    problem="expected $expect"
  elif [ "$got" = "BLOCK" ]; then
    reason=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecisionReason // ""')
    case "$reason" in
      *"match failed"*) ;;
      *) problem="deny reason does not report the failed match" ;;
    esac
  fi
  if [ -z "$problem" ]; then
    pass=$((pass + 1))
    printf '[ok]   %-5s %-6s | %s\n' "$MODE" "$got" "$cmd"
  else
    fail=$((fail + 1))
    printf '[FAIL] %-5s %-6s | %s\n       %s\n' "$MODE" "$got" "$cmd" "$problem"
  fi
}

broken_case BLOCK 'glab ci trace 2000'
broken_case ALLOW 'glab ci list'
echo

echo "passed: $pass"
echo "failed: $fail"
[ "$fail" -eq 0 ]
