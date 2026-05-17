from __future__ import annotations

from unittest.mock import patch

from glab_pipeline.api import glab_api


def _make_run_result(stdout: str = "{}", returncode: int = 0, stderr: str = ""):
    class R:
        pass

    r = R()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def test_query_is_appended_to_endpoint_when_no_existing_query():
    with patch("glab_pipeline.api.subprocess.run") as run:
        run.return_value = _make_run_result(stdout='{"ok":true}')
        glab_api("projects/1/pipelines/2/jobs", query={"per_page": "100", "include_retried": "true"})
        cmd = run.call_args.args[0]
        endpoint = cmd[2]
        assert endpoint.startswith("projects/1/pipelines/2/jobs?")
        # urlencode is deterministic on dict order in py3.7+
        assert "per_page=100" in endpoint
        assert "include_retried=true" in endpoint


def test_query_is_appended_with_ampersand_when_endpoint_already_has_query():
    with patch("glab_pipeline.api.subprocess.run") as run:
        run.return_value = _make_run_result(stdout='{}')
        glab_api("projects/1/ci/lint?foo=bar", query={"dry_run": "true"})
        endpoint = run.call_args.args[0][2]
        assert endpoint == "projects/1/ci/lint?foo=bar&dry_run=true"


def test_query_values_are_url_encoded():
    with patch("glab_pipeline.api.subprocess.run") as run:
        run.return_value = _make_run_result(stdout='{}')
        glab_api("projects/1/x", query={"ref": "feature/foo bar"})
        endpoint = run.call_args.args[0][2]
        assert "ref=feature%2Ffoo+bar" in endpoint


def test_no_query_means_endpoint_unchanged():
    with patch("glab_pipeline.api.subprocess.run") as run:
        run.return_value = _make_run_result(stdout='{}')
        glab_api("projects/1/pipelines/2")
        endpoint = run.call_args.args[0][2]
        assert endpoint == "projects/1/pipelines/2"
