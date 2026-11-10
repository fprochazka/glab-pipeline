# glab-pipeline

**This package is deprecated.** The `glab-pipeline` command now ships in [glab-cli-extras](https://github.com/fprochazka/glab-cli-extras), with the same commands and options. Its documentation is there.

Replace the command:

```bash
uv tool uninstall glab-pipeline && uv tool install glab-cli-extras
```

Version 1.0.0 of this package has no code of its own. It installs glab-cli-extras, which provides the `glab-pipeline` command and prints a one-line deprecation notice to stderr while this package is installed.

Replace the Claude Code plugin with the `glab` plugin of glab-cli-extras, which carries the `glab:glab-pipeline` skill and the same Bash guard. Uninstall the old one first, so the two guards don't both run on every Bash call:

```bash
claude plugin uninstall glab-pipeline@fprochazka-glab-pipeline
claude plugin marketplace remove fprochazka-glab-pipeline
claude plugin marketplace add git@github.com:fprochazka/glab-cli-extras.git
claude plugin install glab@fprochazka-glab-cli-extras
```
