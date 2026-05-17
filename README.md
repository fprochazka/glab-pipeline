# glab-pipeline

Agent-friendly CLI for inspecting GitLab CI pipelines. Dumps full pipeline state (jobs, traces, status) and prints a problem-driven summary that highlights what actually failed and why — designed for AI agents that need to triage broken pipelines without wading through raw API JSON.

## Why

The `glab` CLI shows pipeline status, but inspecting a failed pipeline still means manually fetching each failing job, downloading traces, and stitching the picture together. This tool wraps those calls into a single command, writes per-job artifacts to disk for incremental re-reads, and surfaces the failing jobs and their relevant log tails up front.

## Installation

```bash
uv tool install glab-pipeline
```

## Usage

By default, the MR / pipeline is auto-detected from the current git branch (via `glab mr view`).

### inspect

```bash
glab-pipeline inspect
```

Dumps the full pipeline state to a local directory (one file per job, with trace) and prints a summary focused on failures.

## Requirements

- [`glab` CLI](https://docs.gitlab.com/cli/) installed and authenticated
- Python 3.12+

## Development

```bash
git clone https://github.com/fprochazka/glab-pipeline.git
cd glab-pipeline
uv sync --dev
uv run ruff check .
uv run pytest
```

## Releasing

Version is derived automatically from git tags via `hatch-vcs`. Tag, push, and the GitHub release flow handles publishing.
