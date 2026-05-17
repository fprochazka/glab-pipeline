from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pipeline:
    id: int
    iid: int | None
    status: str
    source: str | None
    ref: str
    sha: str
    web_url: str
    yaml_errors: str | None
    created_at: str | None
    updated_at: str | None
    started_at: str | None
    finished_at: str | None
    duration: int | None  # seconds
    queued_duration: float | None
    name: str | None
    user: dict | None  # keep raw


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    stage: str
    status: str  # success/failed/canceled/skipped/manual/...
    failure_reason: str | None
    allow_failure: bool
    web_url: str
    duration: float | None
    started_at: str | None
    finished_at: str | None
    created_at: str | None


@dataclass(frozen=True)
class Bridge:
    id: int
    name: str
    stage: str
    status: str
    failure_reason: str | None
    downstream_pipeline: dict | None  # keep raw; has id, status, web_url, ref, sha


def parse_pipeline(d: dict) -> Pipeline:
    """Parse a pipeline dict from the GitLab API into a Pipeline dataclass."""
    return Pipeline(
        id=d["id"],
        iid=d.get("iid"),
        status=d["status"],
        source=d.get("source"),
        ref=d["ref"],
        sha=d["sha"],
        web_url=d["web_url"],
        yaml_errors=d.get("yaml_errors"),
        created_at=d.get("created_at"),
        updated_at=d.get("updated_at"),
        started_at=d.get("started_at"),
        finished_at=d.get("finished_at"),
        duration=d.get("duration"),
        queued_duration=d.get("queued_duration"),
        name=d.get("name"),
        user=d.get("user"),
    )


def parse_job(d: dict) -> Job:
    """Parse a job dict from the GitLab API into a Job dataclass."""
    return Job(
        id=d["id"],
        name=d["name"],
        stage=d["stage"],
        status=d["status"],
        failure_reason=d.get("failure_reason"),
        allow_failure=d.get("allow_failure", False),
        web_url=d["web_url"],
        duration=d.get("duration"),
        started_at=d.get("started_at"),
        finished_at=d.get("finished_at"),
        created_at=d.get("created_at"),
    )


def parse_bridge(d: dict) -> Bridge:
    """Parse a bridge dict from the GitLab API into a Bridge dataclass."""
    return Bridge(
        id=d["id"],
        name=d["name"],
        stage=d["stage"],
        status=d["status"],
        failure_reason=d.get("failure_reason"),
        downstream_pipeline=d.get("downstream_pipeline"),
    )


def parse_jobs(items: list[dict]) -> list[Job]:
    return [parse_job(j) for j in items]


def parse_bridges(items: list[dict]) -> list[Bridge]:
    return [parse_bridge(b) for b in items]
