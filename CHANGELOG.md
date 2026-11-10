# Changelog

## 1.0.0 (2026-11-10)

The `glab-pipeline` command moved into [glab-cli-extras](https://github.com/fprochazka/glab-cli-extras). This package no longer has code of its own: it depends on glab-cli-extras 0.3.0 or later, which provides the `glab-pipeline` command. Replace it:

```bash
uv tool uninstall glab-pipeline && uv tool install glab-cli-extras
```

Breaking changes, with what to do:

- While this package is installed, glab-cli-extras prints one deprecation line to stderr on every run. Stdout, `--json` output and the exit code are those of glab-cli-extras. If a script treats any stderr output as a failure, switch it to glab-cli-extras.
- The dump goes into the pipeline's dir under the glab-cli-extras base dir, `<base>/<host>/<group>/<project>/-/pipelines/<id>/`, instead of `$TMPDIR/glab-pipeline-<id>-<timestamp>/`, and a rerun reuses what is on disk. Take the path from the command output, or pass `--output-dir`.
- Only failed jobs' logs are downloaded by default. Every other job gets a placeholder file with the command that downloads its log. Pass `--logs=all` for every log.
- A partial set of context flags, such as `--project` without `--hostname`, is a usage error instead of being ignored.

The Claude Code plugin in this repo is unchanged. Its hook and skill call `glab-pipeline`, which glab-cli-extras provides.
