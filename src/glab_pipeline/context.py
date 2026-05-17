from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from glab_pipeline.api import glab_api, glab_mr_view_json


@dataclass(frozen=True)
class PipelineContext:
    hostname: str
    project_id: int
    project_path: str  # e.g. "group/subgroup/repo"
    pipeline_id: int
    pipeline_url: str
    sha: str
    ref: str
    pipeline_raw: dict


_PIPELINE_PATH_RE = re.compile(r"^/(.+)/-/pipelines/(\d+)/?$")
_MR_PATH_RE = re.compile(r"^/(.+)/-/merge_requests/(\d+)/?$")


def _parse_pipeline_url(url: str) -> tuple[str, str, int]:
    """Parse a GitLab pipeline URL into (hostname, project_path, pipeline_id).

    Accepts URLs of the form: https?://<host>/<project_path>/-/pipelines/<id>
    where project_path may contain slashes (groups/subgroups).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid GitLab pipeline URL: {url}")
    match = _PIPELINE_PATH_RE.match(parsed.path)
    if not match:
        raise ValueError(f"Invalid GitLab pipeline URL: {url}")
    return parsed.netloc, match.group(1), int(match.group(2))


def _parse_mr_url(url: str) -> tuple[str, str, int]:
    """Parse a GitLab MR URL into (hostname, project_path, mr_iid)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Invalid GitLab MR URL: {url}")
    match = _MR_PATH_RE.match(parsed.path)
    if not match:
        raise ValueError(f"Invalid GitLab MR URL: {url}")
    return parsed.netloc, match.group(1), int(match.group(2))


def _build_pipeline_context(
    *,
    hostname: str,
    project_id: int,
    project_path: str,
    pipeline_raw: dict,
) -> PipelineContext:
    return PipelineContext(
        hostname=hostname,
        project_id=project_id,
        project_path=project_path,
        pipeline_id=pipeline_raw["id"],
        pipeline_url=pipeline_raw["web_url"],
        sha=pipeline_raw["sha"],
        ref=pipeline_raw["ref"],
        pipeline_raw=pipeline_raw,
    )


def _project_path_from_web_url(web_url: str) -> tuple[str, str]:
    """Extract (hostname, project_path) from a GitLab MR web URL."""
    parsed = urlparse(web_url)
    match = _MR_PATH_RE.match(parsed.path)
    if not match:
        raise ValueError(f"Cannot parse MR URL: {web_url}")
    return parsed.netloc, match.group(1)


def resolve_pipeline_context(args: argparse.Namespace) -> PipelineContext:
    """Resolve a PipelineContext from CLI args.

    Precedence:
      1. --pipeline-url
      2. --pipeline-id (+ project/hostname or git auto-detect)
      3. --mr-url / --mr-iid
      4. auto-detect from current branch's MR head_pipeline
    """
    # 1. --pipeline-url
    pipeline_url = getattr(args, "pipeline_url", None)
    if pipeline_url:
        hostname, project_path, pipeline_id = _parse_pipeline_url(pipeline_url)
        project_data = glab_api(
            f"projects/{quote(project_path, safe='')}", hostname=hostname
        )
        project_id = project_data["id"]
        pipeline_raw = glab_api(
            f"projects/{project_id}/pipelines/{pipeline_id}", hostname=hostname
        )
        return _build_pipeline_context(
            hostname=hostname,
            project_id=project_id,
            project_path=project_path,
            pipeline_raw=pipeline_raw,
        )

    # 2. --pipeline-id
    pipeline_id = getattr(args, "pipeline_id", None)
    if pipeline_id:
        hostname = getattr(args, "hostname", None)
        project = getattr(args, "project", None)
        if hostname and project:
            project_data = glab_api(
                f"projects/{quote(project, safe='')}", hostname=hostname
            )
            project_id = project_data["id"]
            project_path = project
        else:
            mr_data = glab_mr_view_json(hostname=hostname)
            hostname, project_path = _project_path_from_web_url(mr_data["web_url"])
            project_id = mr_data["project_id"]
        pipeline_raw = glab_api(
            f"projects/{project_id}/pipelines/{pipeline_id}", hostname=hostname
        )
        return _build_pipeline_context(
            hostname=hostname,
            project_id=project_id,
            project_path=project_path,
            pipeline_raw=pipeline_raw,
        )

    # 3. --mr-url / --mr-iid
    mr_url = getattr(args, "mr_url", None)
    mr_iid = getattr(args, "mr_iid", None)
    if mr_url or mr_iid:
        if mr_url:
            hostname, project_path, mr_iid = _parse_mr_url(mr_url)
        else:
            hostname = getattr(args, "hostname", None)
            project_path = getattr(args, "project", None)
            if not (hostname and project_path):
                raise ValueError(
                    "--mr-iid requires --hostname and --project (or use --mr-url)"
                )
        project_data = glab_api(
            f"projects/{quote(project_path, safe='')}", hostname=hostname
        )
        project_id = project_data["id"]
        mr_data = glab_api(
            f"projects/{project_id}/merge_requests/{mr_iid}", hostname=hostname
        )
        head_pipeline = mr_data.get("head_pipeline")
        if not head_pipeline:
            raise ValueError(
                f"No pipeline found for MR !{mr_iid} in {project_path}"
            )
        pipeline_id = head_pipeline["id"]
        pipeline_raw = glab_api(
            f"projects/{project_id}/pipelines/{pipeline_id}", hostname=hostname
        )
        return _build_pipeline_context(
            hostname=hostname,
            project_id=project_id,
            project_path=project_path,
            pipeline_raw=pipeline_raw,
        )

    # 4. Fallback: auto-detect from current branch
    hostname = getattr(args, "hostname", None)
    mr_data = glab_mr_view_json(hostname=hostname)
    head_pipeline = mr_data.get("head_pipeline")
    if not head_pipeline:
        raise ValueError("No pipeline found for current MR")
    hostname, project_path = _project_path_from_web_url(mr_data["web_url"])
    project_id = mr_data["project_id"]
    pipeline_id = head_pipeline["id"]
    pipeline_raw = glab_api(
        f"projects/{project_id}/pipelines/{pipeline_id}", hostname=hostname
    )
    return _build_pipeline_context(
        hostname=hostname,
        project_id=project_id,
        project_path=project_path,
        pipeline_raw=pipeline_raw,
    )
