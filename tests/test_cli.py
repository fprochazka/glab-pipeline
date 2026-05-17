from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from glab_pipeline import cli


def test_top_level_help_lists_inspect(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "inspect" in out


def test_inspect_help_lists_context_flags(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["inspect", "--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    for flag in (
        "--pipeline-url",
        "--pipeline-id",
        "--mr-url",
        "--mr-iid",
        "--project",
        "--hostname",
        "--output-dir",
        "--with-merged-ci-config",
        "--with-test-report",
        "--with-downstream-pipelines",
        "--json",
    ):
        assert flag in out
    assert "--full" not in out


def test_bare_invocation_prints_help_returns_zero(capsys):
    rc = cli.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "inspect" in out


def test_inspect_dispatches_to_run_with_namespace():
    captured: dict[str, argparse.Namespace] = {}

    def fake_run(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    with patch("glab_pipeline.commands.inspect.run", side_effect=fake_run):
        rc = cli.main(["inspect", "--pipeline-id", "42"])
    assert rc == 0
    args = captured["args"]
    assert args.pipeline_id == 42
    assert args.command == "inspect"
    assert args.with_merged_ci_config is False
    assert args.with_test_report is False
    assert args.with_downstream_pipelines is False
    assert args.output_dir is None
    assert args.json is False


def test_inspect_with_flags_set_true():
    captured: dict[str, argparse.Namespace] = {}

    def fake_run(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    with patch("glab_pipeline.commands.inspect.run", side_effect=fake_run):
        rc = cli.main(
            [
                "inspect",
                "--pipeline-id",
                "42",
                "--with-merged-ci-config",
                "--with-test-report",
                "--with-downstream-pipelines",
            ]
        )
    assert rc == 0
    args = captured["args"]
    assert args.with_merged_ci_config is True
    assert args.with_test_report is True
    assert args.with_downstream_pipelines is True


def test_inspect_json_flag_sets_true():
    captured: dict[str, argparse.Namespace] = {}

    def fake_run(args: argparse.Namespace) -> int:
        captured["args"] = args
        return 0

    with patch("glab_pipeline.commands.inspect.run", side_effect=fake_run):
        rc = cli.main(["inspect", "--pipeline-id", "42", "--json"])
    assert rc == 0
    assert captured["args"].json is True
