"""Typed values shared by the community-radar workflow."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class NormalizedPost:
    """A canonical Reddit post record retained as evidence."""

    post_id: str
    url: str
    subreddit: str
    title: str
    body: str
    author: str | None
    created_at: datetime
    score: int
    comment_count: int
    source_surfaces: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Community:
    """An approved Reddit community to collect from."""

    name: str


@dataclass(frozen=True, slots=True)
class CollectionSettings:
    """Collection limits and pacing that can be safely committed in YAML."""

    request_interval_seconds: float = 3.0
    comments_per_post: int = 100
    comment_depth: int = 3
    replies_per_comment: int = 20
    max_comment_length: int = 5000
    expand_more: bool = True
    expand_rounds: int = 5


@dataclass(frozen=True, slots=True)
class RadarConfig:
    """Validated configuration needed by the core analysis workflow."""

    project: str
    communities: tuple[Community, ...]
    current_window_days: int = 30
    baseline_window_days: int = 60
    shortlist_per_community: int = 30
    collection: CollectionSettings = CollectionSettings()


class PostWindow(StrEnum):
    """The fixed analysis windows for a collected post."""

    CURRENT = "current"
    BASELINE = "baseline"


@dataclass(frozen=True, slots=True)
class WindowedPost:
    """A normalized post with its 30/90-day comparison label."""

    post: NormalizedPost
    window: PostWindow


@dataclass(frozen=True, slots=True)
class ShortlistedPost:
    """A post selected for deep reading with its reproducible priority."""

    post: NormalizedPost
    window: PostWindow
    priority_score: float


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Secret-free state needed to resume or inspect a run."""

    run_id: str
    started_at: datetime
    config_sha256: str
    status: str
    completed_stages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TopicRecord:
    """A persistent identity for one community-specific topic."""

    topic_id: str
    community: str
    canonical_key: str
    label_en: str
    label_zh: str
