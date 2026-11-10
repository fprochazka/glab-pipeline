# glab-pipeline

> [!WARNING]
> **This package is deprecated.** The `glab-pipeline` command now ships in [glab-cli-extras](https://github.com/fprochazka/glab-cli-extras). Replace this package with it:
>
> ```bash
> uv tool uninstall glab-pipeline && uv tool install glab-cli-extras
> ```
>
> Version 1.0.0 of this package has no code of its own. It installs glab-cli-extras 0.3.0 or later, which provides the `glab-pipeline` command. While this package is installed, glab-cli-extras prints a one-line deprecation notice to stderr on every run. Stdout and the exit code are those of glab-cli-extras.

Agent-friendly CLI for inspecting GitLab CI pipelines: it dumps a pipeline's state and job logs and prints a problem-driven summary. Built on top of [`glab`](https://docs.gitlab.com/cli/) for authentication.

## Installation

```bash
uv tool install glab-cli-extras
```

The command is `glab-pipeline`, as before. To upgrade later, run `uv tool upgrade glab-cli-extras`.

## Usage

```bash
glab-pipeline inspect                              # the head pipeline of the current branch's MR
glab-pipeline inspect --pipeline-url <url>         # an explicit pipeline
glab-pipeline inspect --logs=all                   # every job's log, not only the failed jobs' logs
glab-pipeline inspect --json | jq                  # the summary as JSON instead of text
```

The full reference is in the [glab-pipeline section of the glab-cli-extras README](https://github.com/fprochazka/glab-cli-extras#glab-pipeline). Three things differ from glab-pipeline 0.3.0:

- The dump goes into the pipeline's dir under the glab-cli-extras base dir, `<base>/<host>/<group>/<project>/-/pipelines/<id>/`, instead of `$TMPDIR/glab-pipeline-<id>-<timestamp>/`. A rerun reuses what is on disk. Take the path from the command output; see [Where files go](https://github.com/fprochazka/glab-cli-extras#where-files-go).
- Only failed jobs' logs are downloaded by default; every other job gets a placeholder file that gives the command to download its log. `--logs=all` downloads every log.
- A partial set of context flags, such as `--project` without `--hostname`, is a usage error instead of being ignored.

## Claude Code plugin

> [!WARNING]
> **This plugin is replaced by the `glab` plugin of glab-cli-extras**, which carries the `glab:glab-pipeline` skill and the same Bash guard. Uninstall this one first, so the two guards don't both run on every Bash call:
>
> ```bash
> claude plugin uninstall glab-pipeline@fprochazka-glab-pipeline
> claude plugin marketplace remove fprochazka-glab-pipeline
> claude plugin marketplace add git@github.com:fprochazka/glab-cli-extras.git
> claude plugin install glab@fprochazka-glab-cli-extras
> ```
>
> The rest of this section describes the old plugin.

The repo includes a Claude Code plugin with:

- a **skill** that teaches AI agents how to use `glab-pipeline`
- a **PreToolUse hook** that blocks six command shapes and redirects the agent to `glab-pipeline inspect` instead. This keeps the agent reasoning over a structured dump rather than wrangling pipeline JSON across many uncoordinated API calls.

```bash
claude plugin marketplace add fprochazka/glab-pipeline
claude plugin install glab-pipeline@fprochazka-glab-pipeline
```

To upgrade after a new release:

```bash
uv tool upgrade glab-cli-extras
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

Without bash-classify the hook still works, but in a degraded mode: it falls back to matching the raw command text. That is wrong in both directions — it denies anything that so much as mentions a blocked command, and it misses real calls it cannot see: the pattern never knew glab's `pipe`/`pipeline` aliases, so `glab pipeline view 1000` passes, and a line-based pattern cannot see an endpoint written on a continuation line. Every deny issued that way says so in its reason, and a SessionStart hook says the same thing once at the start of a session, so the agent can tell you to install or upgrade the tool (plugin SessionStart hooks need Claude Code 2.1.257 or newer; versions 2.1.216 to 2.1.252 silently skipped them). A bash-classify between 0.10.0 and 0.11.0 is a quieter middle case: it runs full match mode, so none of the above applies, but it does not resolve the `pipe`/`pipeline` aliases, so those two spellings pass silently until you upgrade.

## Requirements

- [`glab` CLI](https://docs.gitlab.com/cli/) installed and authenticated
- Python 3.12+

The Claude Code plugin's hook additionally needs:

- `jq`
- [`bash-classify`](https://github.com/fprochazka/bash-classify) 0.11.0 or newer. Without it the hook still runs, but falls back to matching raw command text, which both blocks commands that only mention a blocked command in a heredoc or a commit message, and lets glab's `pipe`/`pipeline` aliases through.

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

The plugin manifests carry their own version. Bump it in both files only when the plugin changes:

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
