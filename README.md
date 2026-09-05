# glab-pipeline

Agent-friendly CLI for inspecting GitLab CI pipelines. Built on top of [`glab`](https://docs.gitlab.com/cli/) for authentication.

## Why

The `glab` CLI shows pipeline status, but diagnosing a failed pipeline still means manually fetching each failing job, downloading traces, and stitching the picture together — and `glab ci view` is TUI-only, which doesn't help an AI agent. This tool dumps the full pipeline state to a temp directory (pipeline + jobs + bridges + full trace per job) and prints a problem-driven summary: the base header is always small, and extra sections (YAML errors, failed jobs, failed downstream pipelines, test failures) are appended only when applicable.

Conditional fetches keep dumps lean — `ci/lint` + `merged.yml` are only fetched when the pipeline has YAML errors or a job's `failure_reason` suggests a config issue (`missing_dependency_failure`, `unmet_prerequisites`, etc.); `test_report_summary` is only fetched when a failed job is in a test stage.

## Installation

Install as a [uv tool](https://docs.astral.sh/uv/concepts/tools/):

```bash
uv tool install glab-pipeline
```

To upgrade later:

```bash
uv tool upgrade glab-pipeline
```

For local development, clone and install editable instead:

```bash
git clone https://github.com/fprochazka/glab-pipeline.git
cd glab-pipeline
uv tool install --editable .
```

### Claude Code plugin

The repo includes a Claude Code plugin with:

- a **skill** that teaches AI agents how to use `glab-pipeline`
- a **PreToolUse hook** that blocks six command shapes and redirects the agent to `glab-pipeline inspect` instead. This keeps the agent reasoning over a structured dump rather than wrangling pipeline JSON across many uncoordinated API calls.

```bash
claude plugin marketplace add fprochazka/glab-pipeline
claude plugin install glab-pipeline@fprochazka-glab-pipeline
```

To upgrade after a new release:

```bash
uv tool upgrade glab-pipeline
uv tool install --force bash-classify
claude plugin marketplace update fprochazka-glab-pipeline
claude plugin update glab-pipeline@fprochazka-glab-pipeline
```

The hook blocks:

| Rule | Shape |
|---|---|
| `ci-view` | `glab ci view` |
| `ci-get` | `glab ci get` |
| `ci-trace` | `glab ci trace` |
| `pipelines-api` | `glab api` against `projects/<id>/pipelines/<id>...` |
| `job-trace-api` | `glab api` against `projects/<id>/jobs/<id>/trace` |
| `ci-lint-api` | `glab api` against `projects/<id>/ci/lint` |

The verdict comes from [`bash-classify`](https://github.com/fprochazka/bash-classify), which parses the command and reports which of those shapes it actually *invokes*. Text that merely names one — a heredoc body, an `echo` argument, a commit message, a `grep` pattern — is not an invocation and is allowed, while a wrapper (`sudo`, `timeout`, `bash -c`, `xargs`) does not hide one, and neither do glab's deprecated `pipe`/`pipeline` aliases for `ci`.

Without bash-classify the hook still works, but in a degraded mode: it falls back to matching the raw command text. That is wrong in both directions — it denies anything that so much as mentions a blocked command, and it misses a real call it cannot see on a single line, such as `glab pipeline view 1000` or an endpoint written on a continuation line. Every deny issued that way says so in its reason, so the agent can tell you to install or upgrade the tool. A bash-classify between 0.10.0 and 0.11.0 is a quieter middle case: it runs full match mode, so none of the above applies, but it does not resolve the `pipe`/`pipeline` aliases, so those two spellings pass silently until you upgrade.

## Usage

By default, the pipeline is auto-detected from the current git branch's open MR (via `glab mr view`). Override with `--pipeline-url`, `--pipeline-id`, `--mr-url`, or `--hostname`/`--project`/`--mr-iid`.

### inspect

Dump full pipeline state to a temp directory and print a problem-driven summary.

```bash
glab-pipeline inspect                              # auto-detect from current branch's MR
glab-pipeline inspect --pipeline-url <url>         # explicit pipeline
glab-pipeline inspect --pipeline-id 1234567        # plus --hostname/--project, or auto-detect
glab-pipeline inspect --mr-iid 42 --project g/r --hostname gitlab.com
glab-pipeline inspect --output-dir /path/to/dir    # default: $TMPDIR/glab-pipeline-<pid>-<ts>/
glab-pipeline inspect --with-merged-ci-config      # two-step lint that resolves include: against source branch
glab-pipeline inspect --with-test-report           # force test-report fetch even without failed test jobs
glab-pipeline inspect --with-downstream-pipelines  # fetch downstream detail for every bridge, not just failed
glab-pipeline inspect --with-artefacts             # download+unpack each job's artifacts archive (one zip per job)
glab-pipeline inspect --json | jq                  # print structured summary JSON to stdout (no human text)
```

The dump directory always contains:

- `pipeline.json` — full pipeline metadata (incl. `yaml_errors`, `detailed_status`)
- `jobs.json` — all jobs, including retried
- `bridges.json` — trigger jobs to child/downstream pipelines (omitted if none)
- `job-logs/<stage>-<name>-<id>.log` — **full trace for every job**, fetched in parallel
- `summary.json` — canonical structured summary (single source of truth); always written. Pass `--json` to print this to stdout instead of the human-readable text.

And conditionally:

- `lint.json` + `merged.yml` — when `yaml_errors` is set, the pipeline has 0 jobs, or any job's `failure_reason` hints at a config problem. With `--with-merged-ci-config` this switches to a **two-step lint** that fetches the raw `.gitlab-ci.yml` from the source branch and POSTs it to `/ci/lint`, properly resolving `include:` (useful when masked CI variables appear in include paths).
- `downstream/<bridge-name>-<dpid>.json` — when a bridge failed; one level deep. With `--with-downstream-pipelines` fetched for every bridge with a downstream pipeline.
- `test-report.json` — when a failed job is in a test stage (heuristic on stage/name). Forced by `--with-test-report`.
- `artifacts/<stage>-<name>-<id>/…` — when `--with-artefacts` is set; each job's artifacts archive unpacked (one zip per job, then extracted). Only jobs with a live, non-expired `archive` artifact are fetched; expired/missing/corrupt archives are skipped per-job, never fatal.

Use the summary first to find what failed and why, then read the relevant log/lint/test-report file directly.

## Requirements

- [`glab` CLI](https://docs.gitlab.com/cli/) installed and authenticated
- Python 3.12+

The Claude Code plugin's hook additionally needs:

- `jq`
- [`bash-classify`](https://github.com/fprochazka/bash-classify) 0.11.0 or newer — strongly recommended. Without it the hook falls back to matching raw command text, which both blocks commands that only mention a blocked command in a heredoc or a commit message, and lets glab's `pipe`/`pipeline` aliases through.

```bash
uv tool install bash-classify
```

## Development

```bash
git clone https://github.com/fprochazka/glab-pipeline.git
cd glab-pipeline
uv sync --dev
```

Run tests and linting:

```bash
uv run ruff format .
uv run ruff check .
uv run pytest
```

## Releasing

Version is derived automatically from git tags via `hatch-vcs` — no manual version bumping needed.

Before tagging, bump the version in both plugin manifest files:

- `coding-agent-plugins/claude-code/.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`

Wait for CI to pass on master, then tag, push, and create a GitHub release:

```bash
# Review changes since last release
git log $(git describe --tags --abbrev=0)..HEAD --oneline

git tag v<version>
git push origin v<version>
gh release create v<version> --title "v<version>" --notes "..."
```

The `publish.yml` GitHub Action builds and publishes to PyPI automatically via trusted publishing.
