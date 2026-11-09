"""The glab-pipeline command, which glab-cli-extras now provides.

glab-cli-extras declares a glab-pipeline console script too, and the installer keeps one of the two.
Both run this same function, and so does `python -m glab_pipeline`. glab-cli-extras' function prints
the deprecation notice to stderr when this package is installed, so the wrapper prints nothing
of its own and the notice appears once.
"""

from glab_cli_extras.cli.pipeline import main

__all__ = ["main"]
