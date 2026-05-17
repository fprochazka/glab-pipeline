"""glab-pipeline CLI."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _make_context_parent() -> argparse.ArgumentParser:
    """Argparse parent parser with shared pipeline-context flags."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--pipeline-url",
        help="Full GitLab pipeline URL (https://<host>/<project>/-/pipelines/<id>).",
    )
    parent.add_argument(
        "--pipeline-id",
        type=int,
        help="Numeric pipeline ID (requires --project/--hostname or git auto-detect).",
    )
    parent.add_argument(
        "--mr-url",
        help="Full GitLab merge request URL; uses head_pipeline.",
    )
    parent.add_argument(
        "--mr-iid",
        type=int,
        help="Merge request IID (requires --project and --hostname).",
    )
    parent.add_argument(
        "--project",
        help="Project path (e.g. group/subgroup/repo).",
    )
    parent.add_argument(
        "--hostname",
        help="GitLab hostname (e.g. gitlab.com).",
    )
    return parent


def _run_inspect(args: argparse.Namespace) -> int:
    # Lazy import keeps `--help` cheap and avoids loading network deps when unused.
    from glab_pipeline.commands.inspect import run

    return run(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="glab-pipeline",
        description="Agent-friendly CLI for inspecting GitLab CI pipelines.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    context_parent = _make_context_parent()

    inspect_parser = subparsers.add_parser(
        "inspect",
        parents=[context_parent],
        help="Dump full pipeline state and print a problem-driven summary.",
        description=(
            "Dump the full state of a GitLab CI pipeline (pipeline.json, "
            "jobs.json, bridges.json, every job's trace, plus conditional "
            "lint/test-report/downstream fetches) and print a problem-driven "
            "summary to stdout."
        ),
    )
    inspect_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory to write dump files into "
        "(default: $TMPDIR/glab-pipeline-<pid>-<timestamp>/).",
    )
    inspect_parser.add_argument(
        "--full",
        action="store_true",
        help="Force lint + downstream + test-report fetches unconditionally.",
    )
    inspect_parser.set_defaults(func=_run_inspect)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
