from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest

from glab_pipeline.context import (
    PipelineContext,
    _parse_mr_url,
    _parse_pipeline_url,
    resolve_pipeline_context,
)


def _ns(**kwargs) -> argparse.Namespace:
    """Build a Namespace with the inspect-CLI shape; default missing fields to None."""
    defaults = {
        "pipeline_url": None,
        "pipeline_id": None,
        "mr_url": None,
        "mr_iid": None,
        "hostname": None,
        "project": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestParsePipelineUrl:
    def test_simple_url(self) -> None:
        host, path, pid = _parse_pipeline_url(
            "https://gitlab.com/group/project/-/pipelines/123"
        )
        assert host == "gitlab.com"
        assert path == "group/project"
        assert pid == 123

    def test_nested_groups(self) -> None:
        host, path, pid = _parse_pipeline_url(
            "https://gitlab.example.com/org/team/sub/repo/-/pipelines/9999"
        )
        assert host == "gitlab.example.com"
        assert path == "org/team/sub/repo"
        assert pid == 9999

    def test_trailing_slash(self) -> None:
        host, path, pid = _parse_pipeline_url(
            "https://gitlab.com/group/project/-/pipelines/42/"
        )
        assert host == "gitlab.com"
        assert path == "group/project"
        assert pid == 42

    def test_http_scheme(self) -> None:
        host, path, pid = _parse_pipeline_url(
            "http://gitlab.local/team/app/-/pipelines/7"
        )
        assert host == "gitlab.local"
        assert path == "team/app"
        assert pid == 7

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitLab pipeline URL"):
            _parse_pipeline_url("https://github.com/user/repo/actions/runs/1")

    def test_missing_id_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitLab pipeline URL"):
            _parse_pipeline_url("https://gitlab.com/group/project/-/pipelines/")


class TestParseMrUrl:
    def test_simple_url(self) -> None:
        host, path, iid = _parse_mr_url(
            "https://gitlab.com/group/project/-/merge_requests/42"
        )
        assert host == "gitlab.com"
        assert path == "group/project"
        assert iid == 42

    def test_nested_groups(self) -> None:
        host, path, iid = _parse_mr_url(
            "https://gitlab.example.com/org/team/sub/repo/-/merge_requests/99"
        )
        assert host == "gitlab.example.com"
        assert path == "org/team/sub/repo"
        assert iid == 99

    def test_trailing_slash(self) -> None:
        host, path, iid = _parse_mr_url(
            "https://gitlab.com/g/p/-/merge_requests/1/"
        )
        assert host == "gitlab.com"
        assert path == "g/p"
        assert iid == 1

    def test_http_scheme(self) -> None:
        host, path, iid = _parse_mr_url(
            "http://gitlab.local/team/app/-/merge_requests/5"
        )
        assert host == "gitlab.local"
        assert path == "team/app"
        assert iid == 5

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid GitLab MR URL"):
            _parse_mr_url("https://github.com/user/repo/pull/1")


class TestResolvePipelineContextByUrl:
    @patch("glab_pipeline.context.glab_api")
    def test_resolves_from_pipeline_url(
        self, mock_api, sample_pipeline_failed: dict
    ) -> None:
        # First call: project lookup. Second call: pipeline fetch.
        mock_api.side_effect = [{"id": 7}, sample_pipeline_failed]
        args = _ns(
            pipeline_url="https://gitlab.example.com/foo/bar/-/pipelines/48"
        )
        ctx = resolve_pipeline_context(args)

        assert isinstance(ctx, PipelineContext)
        assert ctx.hostname == "gitlab.example.com"
        assert ctx.project_id == 7
        assert ctx.project_path == "foo/bar"
        assert ctx.pipeline_id == 48
        assert ctx.sha == sample_pipeline_failed["sha"]
        assert ctx.ref == "feature/x"
        assert ctx.pipeline_url == sample_pipeline_failed["web_url"]
        assert ctx.pipeline_raw is sample_pipeline_failed

        calls = mock_api.call_args_list
        assert calls[0].args == ("projects/foo%2Fbar",)
        assert calls[0].kwargs == {"hostname": "gitlab.example.com"}
        assert calls[1].args == ("projects/7/pipelines/48",)
        assert calls[1].kwargs == {"hostname": "gitlab.example.com"}

    @patch("glab_pipeline.context.glab_api")
    def test_resolves_nested_groups_from_pipeline_url(
        self, mock_api, sample_pipeline_success: dict
    ) -> None:
        mock_api.side_effect = [{"id": 9}, sample_pipeline_success]
        args = _ns(
            pipeline_url="https://gitlab.example.com/org/team/sub/repo/-/pipelines/47"
        )
        ctx = resolve_pipeline_context(args)
        assert ctx.project_path == "org/team/sub/repo"
        assert mock_api.call_args_list[0].args == (
            "projects/org%2Fteam%2Fsub%2Frepo",
        )


class TestResolvePipelineContextById:
    @patch("glab_pipeline.context.glab_api")
    def test_with_hostname_and_project(
        self, mock_api, sample_pipeline_failed: dict
    ) -> None:
        mock_api.side_effect = [{"id": 7}, sample_pipeline_failed]
        args = _ns(
            pipeline_id=48,
            hostname="gitlab.example.com",
            project="foo/bar",
        )
        ctx = resolve_pipeline_context(args)
        assert ctx.project_id == 7
        assert ctx.project_path == "foo/bar"
        assert ctx.pipeline_id == 48
        calls = mock_api.call_args_list
        assert calls[0].args == ("projects/foo%2Fbar",)
        assert calls[1].args == ("projects/7/pipelines/48",)

    @patch("glab_pipeline.context.glab_mr_view_json")
    @patch("glab_pipeline.context.glab_api")
    def test_without_project_auto_detects(
        self,
        mock_api,
        mock_mr_view,
        sample_mr_with_head_pipeline: dict,
        sample_pipeline_failed: dict,
    ) -> None:
        mock_mr_view.return_value = sample_mr_with_head_pipeline
        mock_api.return_value = sample_pipeline_failed
        args = _ns(pipeline_id=48)
        ctx = resolve_pipeline_context(args)
        assert ctx.project_id == 1
        assert ctx.project_path == "foo/bar"
        assert ctx.hostname == "gitlab.example.com"
        assert ctx.pipeline_id == 48
        mock_api.assert_called_once_with(
            "projects/1/pipelines/48", hostname="gitlab.example.com"
        )


class TestResolvePipelineContextByMr:
    @patch("glab_pipeline.context.glab_api")
    def test_from_mr_url(
        self,
        mock_api,
        sample_mr_with_head_pipeline: dict,
        sample_pipeline_failed: dict,
    ) -> None:
        # project lookup, mr fetch, pipeline fetch
        mock_api.side_effect = [
            {"id": 1},
            sample_mr_with_head_pipeline,
            sample_pipeline_failed,
        ]
        args = _ns(
            mr_url="https://gitlab.example.com/foo/bar/-/merge_requests/42"
        )
        ctx = resolve_pipeline_context(args)
        assert ctx.pipeline_id == 48
        assert ctx.project_path == "foo/bar"
        assert ctx.hostname == "gitlab.example.com"
        calls = mock_api.call_args_list
        assert calls[0].args == ("projects/foo%2Fbar",)
        assert calls[1].args == ("projects/1/merge_requests/42",)
        assert calls[2].args == ("projects/1/pipelines/48",)

    @patch("glab_pipeline.context.glab_api")
    def test_from_mr_iid_with_project(
        self,
        mock_api,
        sample_mr_with_head_pipeline: dict,
        sample_pipeline_failed: dict,
    ) -> None:
        mock_api.side_effect = [
            {"id": 1},
            sample_mr_with_head_pipeline,
            sample_pipeline_failed,
        ]
        args = _ns(
            mr_iid=42, hostname="gitlab.example.com", project="foo/bar"
        )
        ctx = resolve_pipeline_context(args)
        assert ctx.pipeline_id == 48

    def test_mr_iid_without_project_raises(self) -> None:
        args = _ns(mr_iid=42)
        with pytest.raises(ValueError, match="--mr-iid requires"):
            resolve_pipeline_context(args)

    @patch("glab_pipeline.context.glab_api")
    def test_mr_with_no_head_pipeline_raises(
        self, mock_api, sample_mr_with_head_pipeline: dict
    ) -> None:
        mr = dict(sample_mr_with_head_pipeline)
        mr["head_pipeline"] = None
        mock_api.side_effect = [{"id": 1}, mr]
        args = _ns(
            mr_url="https://gitlab.example.com/foo/bar/-/merge_requests/42"
        )
        with pytest.raises(ValueError, match="No pipeline found for MR"):
            resolve_pipeline_context(args)


class TestResolvePipelineContextFallback:
    @patch("glab_pipeline.context.glab_mr_view_json")
    @patch("glab_pipeline.context.glab_api")
    def test_auto_detect_from_branch(
        self,
        mock_api,
        mock_mr_view,
        sample_mr_with_head_pipeline: dict,
        sample_pipeline_failed: dict,
    ) -> None:
        mock_mr_view.return_value = sample_mr_with_head_pipeline
        mock_api.return_value = sample_pipeline_failed
        args = _ns()
        ctx = resolve_pipeline_context(args)
        assert ctx.pipeline_id == 48
        assert ctx.project_id == 1
        assert ctx.project_path == "foo/bar"
        assert ctx.hostname == "gitlab.example.com"
        mock_api.assert_called_once_with(
            "projects/1/pipelines/48", hostname="gitlab.example.com"
        )

    @patch("glab_pipeline.context.glab_mr_view_json")
    def test_fallback_no_head_pipeline_raises(
        self, mock_mr_view, sample_mr_with_head_pipeline: dict
    ) -> None:
        mr = dict(sample_mr_with_head_pipeline)
        mr["head_pipeline"] = None
        mock_mr_view.return_value = mr
        args = _ns()
        with pytest.raises(ValueError, match="No pipeline found for current MR"):
            resolve_pipeline_context(args)
