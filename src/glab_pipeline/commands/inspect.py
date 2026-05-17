"""inspect — dump full pipeline state + problem-driven summary."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import random
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from glab_pipeline.api import GlabApiError, glab_api
from glab_pipeline.context import resolve_pipeline_context
from glab_pipeline.models import (
    Bridge,
    Job,
    Pipeline,
    parse_bridges,
    parse_jobs,
    parse_pipeline,
)
from glab_pipeline.sanitize import sanitize_filename_part

YAML_HINT_REASONS = frozenset(
    {
        "unmet_prerequisites",
        "missing_dependency_failure",
        "config_error",
        "pipeline_loop_detected",
        "downstream_pipeline_creation_failed",
    }
)

TEST_STAGE_RE = re.compile(r"test|spec|qa", re.IGNORECASE)
TEST_NAME_RE = re.compile(
    r"\b(test|spec|rspec|pytest|jest|vitest|phpunit)\b", re.IGNORECASE
)

# Bridge statuses that are NOT considered failures.
_BRIDGE_OK_STATUSES = frozenset({"success", "manual", "skipped"})

MAX_PARALLEL = 10
MAX_RETRIES = 5
INITIAL_RETRY_DELAY = 1.0


@dataclass(frozen=True)
class ExtrasPlan:
    """Decisions about which conditional fetches to perform."""

    need_lint: bool
    need_test_report: bool
    need_downstream: bool
    yaml_hint_jobs: tuple[int, ...]
    failed_test_jobs: tuple[int, ...]
    failed_bridges: tuple[int, ...]


def is_test_job(job: Job) -> bool:
    """Heuristic: does this job look like a test job?"""
    return bool(TEST_STAGE_RE.search(job.stage) or TEST_NAME_RE.search(job.name))


def decide_extras(
    pipeline: Pipeline,
    jobs: list[Job],
    bridges: list[Bridge],
    *,
    full: bool = False,
) -> ExtrasPlan:
    """Decide which conditional fetches to perform based on pipeline state."""
    yaml_hint_jobs = tuple(
        j.id for j in jobs if j.failure_reason in YAML_HINT_REASONS
    )
    failed_test_jobs = tuple(
        j.id for j in jobs if j.status == "failed" and is_test_job(j)
    )
    failed_bridges = tuple(
        b.id for b in bridges if b.status not in _BRIDGE_OK_STATUSES
    )

    need_lint = bool(
        full
        or pipeline.yaml_errors
        or len(jobs) == 0
        or yaml_hint_jobs
    )
    need_test_report = bool(full or failed_test_jobs)
    need_downstream = bool(full or failed_bridges)

    return ExtrasPlan(
        need_lint=need_lint,
        need_test_report=need_test_report,
        need_downstream=need_downstream,
        yaml_hint_jobs=yaml_hint_jobs,
        failed_test_jobs=failed_test_jobs,
        failed_bridges=failed_bridges,
    )


# ---------------------------------------------------------------------------
# Summary formatting (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SummaryInputs:
    pipeline: Pipeline
    jobs: list[Job]
    bridges: list[Bridge]
    plan: ExtrasPlan
    output_dir: Path
    job_log_paths: dict[int, Path]
    downstream_paths: dict[int, Path]
    has_lint_file: bool
    has_test_report_file: bool
    test_report: dict | None


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    total = int(seconds)
    m, s = divmod(total, 60)
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def build_summary_dict(s: SummaryInputs) -> dict[str, Any]:
    """Build a canonical JSON-serializable summary dict from SummaryInputs.

    This is the single source of truth for the summary; format_summary renders
    a human-readable string from this dict.
    """
    p = s.pipeline
    output_dir = s.output_dir.resolve()

    # Files section: omit keys for files that weren't written.
    files: dict[str, Any] = {
        "pipeline": str(output_dir / "pipeline.json"),
        "jobs": str(output_dir / "jobs.json"),
        "jobs_count": len(s.jobs),
    }
    if s.bridges:
        files["bridges"] = str(output_dir / "bridges.json")
        files["bridges_count"] = len(s.bridges)
    if s.has_lint_file:
        files["lint"] = str(output_dir / "lint.json")
        merged_yml = output_dir / "merged.yml"
        if merged_yml.exists():
            files["merged_yaml"] = str(merged_yml)
    if s.has_test_report_file:
        files["test_report"] = str(output_dir / "test-report.json")

    # Failed jobs
    hint_set = set(s.plan.yaml_hint_jobs)
    failed_jobs_list: list[dict[str, Any]] = []
    for j in s.jobs:
        if j.status != "failed":
            continue
        log_path = s.job_log_paths.get(j.id)
        failed_jobs_list.append(
            {
                "id": j.id,
                "name": j.name,
                "stage": j.stage,
                "failure_reason": j.failure_reason,
                "log": str(log_path.resolve()) if log_path is not None else None,
                "yaml_hint": j.id in hint_set,
            }
        )

    # Failed downstream
    failed_bridge_ids = set(s.plan.failed_bridges)
    failed_downstream_list: list[dict[str, Any]] = []
    for b in s.bridges:
        if b.id not in failed_bridge_ids:
            continue
        dp = b.downstream_pipeline or {}
        detail = s.downstream_paths.get(b.id)
        failed_downstream_list.append(
            {
                "bridge_id": b.id,
                "bridge_name": b.name,
                "downstream_pipeline_id": dp.get("id"),
                "downstream_status": dp.get("status"),
                "detail": str(detail.resolve()) if detail is not None else None,
            }
        )

    # Test failures
    test_failures: dict[str, Any] | None = None
    if s.has_test_report_file:
        tr = s.test_report or {}
        total = tr.get("total") if isinstance(tr, dict) else None
        if isinstance(total, dict) and "failed" in total and "count" in total:
            test_failures = {
                "failed": total["failed"],
                "total": total["count"],
            }

    return {
        "pipeline": {
            "id": p.id,
            "status": p.status,
            "url": p.web_url,
            "ref": p.ref,
            "sha": p.sha,
            "sha_short": (p.sha or "")[:7],
            "source": p.source,
            "created_at": p.created_at,
            "duration_seconds": p.duration,
            "duration_human": _format_duration(p.duration),
        },
        "output_dir": str(output_dir),
        "files": files,
        "yaml_errors": p.yaml_errors,
        "failed_jobs": failed_jobs_list,
        "failed_downstream": failed_downstream_list,
        "test_failures": test_failures,
    }


def format_summary(summary: dict[str, Any]) -> str:
    """Render the canonical summary dict as human-readable text."""
    p = summary["pipeline"]
    files = summary["files"]
    output_dir = summary["output_dir"]
    lines: list[str] = []

    lines.append(f"PIPELINE {p['id']} — status: {p['status']}")
    lines.append(f"URL:     {p['url']}")
    short_sha = p["sha_short"]
    source = p["source"] or "unknown"
    lines.append(f"Ref:     {p['ref']}   SHA: {short_sha}   Source: {source}")
    lines.append(
        f"Created: {p['created_at']}   Duration: {p['duration_human']}"
    )
    lines.append("")
    lines.append("Files Created:")
    lines.append(f"  Pipeline:   {files['pipeline']}")
    lines.append(
        f"  Jobs:       {files['jobs']}   "
        f"({files['jobs_count']} jobs, all logs in job-logs/)"
    )
    if "bridges" in files:
        lines.append(
            f"  Bridges:    {files['bridges']}   "
            f"({files['bridges_count']} bridges)"
        )
    lines.append("")
    lines.append(f"All files in: {output_dir}/")

    # YAML errors / lint section
    yaml_errors = summary["yaml_errors"]
    if yaml_errors:
        lines.append("")
        lines.append("YAML Errors:")
        for ln in yaml_errors.splitlines() or [yaml_errors]:
            lines.append(f"  {ln}")
        lines.append("  → lint.json, merged.yml")
    elif "lint" in files:
        lines.append("")
        lines.append("Lint result: see lint.json, merged.yml")

    # Failed jobs section
    failed_jobs = summary["failed_jobs"]
    if failed_jobs:
        lines.append("")
        lines.append(f"Failed Jobs ({len(failed_jobs)}):")
        for j in failed_jobs:
            reason = j["failure_reason"] or "—"
            lines.append(
                f"  {j['name']}  (stage={j['stage']}, reason={reason})"
            )
            if j["log"] is not None:
                lines.append(f"    Log: {j['log']}")
            if j["yaml_hint"]:
                lines.append("    → likely YAML/needs issue, see lint.json")

    # Failed downstream pipelines
    failed_downstream = summary["failed_downstream"]
    if failed_downstream:
        lines.append("")
        lines.append(
            f"Failed Downstream Pipelines ({len(failed_downstream)}):"
        )
        for d in failed_downstream:
            dpid = d["downstream_pipeline_id"] if d["downstream_pipeline_id"] is not None else "—"
            dpstatus = d["downstream_status"] if d["downstream_status"] is not None else "—"
            lines.append(
                f"  {d['bridge_name']} → pipeline {dpid} ({dpstatus})"
            )
            if d["detail"] is not None:
                lines.append(f"    Detail: {d['detail']}")

    # Test failures
    if "test_report" in files:
        tf = summary["test_failures"]
        if tf is not None:
            lines.append("")
            lines.append(
                f"Test Failures ({tf['failed']} failed / "
                f"{tf['total']} total):"
            )
            lines.append("  See test-report.json")
        else:
            lines.append("")
            lines.append("Test failures present — see test-report.json")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _fetch_trace_raw(
    project_id: int, job_id: int, hostname: str | None
) -> str:
    """Fetch a job's trace via `glab api` subprocess (plain text endpoint).

    Implements retry+backoff. Raises GlabApiError on final failure so the
    caller can record the error in the per-job log file.
    """
    cmd = ["glab", "api", f"projects/{project_id}/jobs/{job_id}/trace"]
    if hostname:
        cmd.extend(["--hostname", hostname])

    delay = INITIAL_RETRY_DELAY
    last_stderr = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            )
        except subprocess.TimeoutExpired as exc:
            last_stderr = f"timeout after 60s: {exc}"
        else:
            if result.returncode == 0:
                return result.stdout
            last_stderr = result.stderr.strip()
        if attempt < MAX_RETRIES:
            jitter = random.uniform(0, delay / 2)
            time.sleep(delay + jitter)
            delay *= 2

    raise GlabApiError(
        f"glab api trace failed after {MAX_RETRIES} retries: {last_stderr}",
        stderr=last_stderr,
    )


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


def _job_log_name(job: Job) -> str:
    return (
        f"{sanitize_filename_part(job.stage)}-"
        f"{sanitize_filename_part(job.name)}-{job.id}.log"
    )


def _downstream_filename(bridge: Bridge, dpid: int) -> str:
    return f"{sanitize_filename_part(bridge.name)}-{dpid}.json"


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    ctx = resolve_pipeline_context(args)
    pipeline = parse_pipeline(ctx.pipeline_raw)

    # Output dir
    if getattr(args, "output_dir", None):
        output_dir = Path(args.output_dir)
    else:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = (
            Path(tempfile.gettempdir())
            / f"glab-pipeline-{ctx.pipeline_id}-{ts}"
        )
    job_logs_dir = output_dir / "job-logs"
    job_logs_dir.mkdir(parents=True, exist_ok=True)

    # 1. pipeline.json (already fetched)
    _write_json(output_dir / "pipeline.json", ctx.pipeline_raw)

    # 2. jobs.json
    jobs_raw = glab_api(
        f"projects/{ctx.project_id}/pipelines/{ctx.pipeline_id}/jobs",
        paginate=True,
        query={"per_page": "100", "include_retried": "true"},
        hostname=ctx.hostname,
    ) or []
    _write_json(output_dir / "jobs.json", jobs_raw)
    jobs = parse_jobs(jobs_raw)

    # 3. bridges.json (optional)
    bridges_raw = glab_api(
        f"projects/{ctx.project_id}/pipelines/{ctx.pipeline_id}/bridges",
        paginate=True,
        query={"per_page": "100"},
        hostname=ctx.hostname,
    ) or []
    if bridges_raw:
        _write_json(output_dir / "bridges.json", bridges_raw)
    bridges = parse_bridges(bridges_raw)

    # 4. Decide extras
    full = bool(getattr(args, "full", False))
    plan = decide_extras(pipeline, jobs, bridges, full=full)

    # 5. Conditional fetches in parallel
    has_lint_file = False
    has_test_report_file = False
    test_report: dict | None = None
    downstream_paths: dict[int, Path] = {}

    bridges_by_id = {b.id: b for b in bridges}

    def fetch_lint():
        return glab_api(
            f"projects/{ctx.project_id}/ci/lint",
            query={
                "content_ref": ctx.sha,
                "dry_run": "true",
                "include_jobs": "true",
            },
            hostname=ctx.hostname,
        )

    def fetch_test_report():
        return glab_api(
            f"projects/{ctx.project_id}/pipelines/{ctx.pipeline_id}/test_report_summary",
            hostname=ctx.hostname,
        )

    def fetch_downstream(bridge: Bridge):
        dp = bridge.downstream_pipeline or {}
        dpid = dp.get("id")
        if not dpid:
            return None
        project_id = dp.get("project_id") or ctx.project_id
        data = glab_api(
            f"projects/{project_id}/pipelines/{dpid}",
            hostname=ctx.hostname,
        )
        return bridge, dpid, data

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_PARALLEL
    ) as ex:
        futures: dict[concurrent.futures.Future, str] = {}
        if plan.need_lint:
            futures[ex.submit(fetch_lint)] = "lint"
        if plan.need_test_report:
            futures[ex.submit(fetch_test_report)] = "test_report"
        if plan.need_downstream:
            for bid in plan.failed_bridges:
                b = bridges_by_id.get(bid)
                if b is None or not b.downstream_pipeline:
                    continue
                futures[ex.submit(fetch_downstream, b)] = f"downstream:{bid}"

        for fut in concurrent.futures.as_completed(futures):
            tag = futures[fut]
            try:
                result = fut.result()
            except (GlabApiError, Exception) as exc:  # noqa: BLE001
                print(
                    f"warning: failed to fetch {tag}: {exc}",
                    file=sys.stderr,
                )
                continue
            if tag == "lint" and result is not None:
                _write_json(output_dir / "lint.json", result)
                has_lint_file = True
                merged_yaml = result.get("merged_yaml")
                if merged_yaml:
                    (output_dir / "merged.yml").write_text(merged_yaml)
            elif tag == "test_report" and result is not None:
                _write_json(output_dir / "test-report.json", result)
                has_test_report_file = True
                test_report = result if isinstance(result, dict) else None
            elif tag.startswith("downstream:") and result is not None:
                bridge, dpid, data = result
                ds_dir = output_dir / "downstream"
                ds_dir.mkdir(parents=True, exist_ok=True)
                path = ds_dir / _downstream_filename(bridge, dpid)
                _write_json(path, data)
                downstream_paths[bridge.id] = path

    # 6. Fetch all traces in parallel
    job_log_paths: dict[int, Path] = {}

    def fetch_trace(job: Job) -> tuple[Job, str, str | None]:
        try:
            text = _fetch_trace_raw(ctx.project_id, job.id, ctx.hostname)
            return job, text, None
        except GlabApiError as exc:
            return job, "", str(exc)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_PARALLEL
    ) as ex:
        for job, text, err in ex.map(fetch_trace, jobs):
            log_path = job_logs_dir / _job_log_name(job)
            if err is None:
                log_path.write_text(text)
            else:
                log_path.write_text(
                    f"ERROR: failed to fetch trace after {MAX_RETRIES} retries\n{err}\n"
                )
                print(
                    f"warning: failed to fetch trace for job {job.id} ({job.name}): {err}",
                    file=sys.stderr,
                )
            job_log_paths[job.id] = log_path

    # 7. Build summary
    summary_dict = build_summary_dict(
        SummaryInputs(
            pipeline=pipeline,
            jobs=jobs,
            bridges=bridges,
            plan=plan,
            output_dir=output_dir,
            job_log_paths=job_log_paths,
            downstream_paths=downstream_paths,
            has_lint_file=has_lint_file,
            has_test_report_file=has_test_report_file,
            test_report=test_report,
        )
    )
    summary_json = json.dumps(summary_dict, indent=2, ensure_ascii=False)
    (output_dir / "summary.json").write_text(summary_json + "\n")

    if getattr(args, "json", False):
        print(summary_json)
    else:
        print(format_summary(summary_dict), end="")
    return 0
