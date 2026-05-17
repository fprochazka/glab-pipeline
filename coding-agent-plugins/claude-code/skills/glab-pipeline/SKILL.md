---
name: glab-pipeline
description: >-
  This skill should be used when the user asks to "inspect a pipeline",
  "debug a failed CI job", "check pipeline status", "look at pipeline logs",
  "why did the pipeline fail", "dump pipeline state", "investigate CI failure",
  "check MR pipeline", or needs to triage a broken GitLab CI pipeline.
  Provides CLI reference for the glab-pipeline tool.
---

# glab-pipeline CLI

Agent-friendly CLI for inspecting GitLab CI pipelines. Dumps full pipeline state
(jobs, traces, lint, test reports, downstream pipelines) to a local directory
and prints a problem-driven summary that highlights what actually failed.

## Install

```bash
uv tool install glab-pipeline
```

## Usage

**The pipeline is auto-detected from the current git branch's MR** (via `glab mr view`).
No flags needed when the source branch is checked out.

### inspect

```bash
glab-pipeline inspect                                  # auto-detect from current branch
glab-pipeline inspect --pipeline-url <url>             # full pipeline URL
glab-pipeline inspect --pipeline-id <id>               # numeric pipeline ID (needs --project/--hostname)
glab-pipeline inspect --mr-url <url>                   # MR URL — uses head_pipeline
glab-pipeline inspect --mr-iid <iid>                   # MR IID (needs --project/--hostname)
glab-pipeline inspect --full                           # force lint + test-report + downstream fetches
```

Writes the dump to `$TMPDIR/glab-pipeline-<pipeline-id>-<timestamp>/` and prints
the summary to stdout.

## What gets dumped

Always:
- `pipeline.json` — full pipeline object from GitLab API
- `jobs.json` — all jobs (paginated, includes retried)
- `job-logs/<stage>-<name>-<id>.log` — raw trace for every job
- `summary.txt` — same problem-driven summary printed to stdout

Conditional (or always with `--full`):
- `bridges.json` — present only if pipeline has child/downstream pipelines
- `lint.json` + `merged.yml` — when pipeline has YAML errors, no jobs, or jobs failed with config/needs reasons
- `test-report.json` — when failed jobs look like test jobs (stage or name matches test/spec/qa/pytest/jest/etc.)
- `downstream/<bridge-name>-<dpid>.json` — for each failed bridge's downstream pipeline

## How to read the output

1. **Start with `summary.txt`** — lists failed jobs with their failure reasons and points at the relevant files
2. **For script/runtime failures:** read `job-logs/<failed-job>.log` — the tail usually has the error
3. **For YAML/needs/config errors:** read `lint.json` and `merged.yml` — shows what GitLab actually parsed
4. **For test failures:** read `test-report.json` — structured per-test results
5. **For failed child pipelines:** read `downstream/<bridge>-<dpid>.json` — then recurse with `glab-pipeline inspect --pipeline-id <dpid>`

## When NOT to use

For pipeline actions (not inspection), use `glab ci` directly:
- `glab ci status` — quick status check
- `glab ci list` — list recent pipelines
- `glab ci run` / `glab ci retry` / `glab ci cancel` — trigger/manage runs
- `glab ci lint <file>` — lint a local `.gitlab-ci.yml`
- `glab ci artifact` — download artifacts
