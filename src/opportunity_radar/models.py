"""Typed values shared by the community-radar workflow."""

from dataclasses import dataclass
from datetime import date, datetime
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
    aliases: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    category: str = ""
    brand: str = ""
    slang: tuple[str, ...] = ()
    community_id: str = ""
    status: str = "approved"


@dataclass(frozen=True, slots=True)
class CommunityCatalog:
    """A versioned, approved set of communities and their governance metadata."""

    version: str
    communities: tuple[Community, ...]


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


_DEPTH_PRESETS = {
    "quick": (300, 30),
    "standard": (1000, 80),
    "deep": (1000, 150),
    # Complete mode is bounded by the selected date window and Reddit's own
    # pagination/exhaustion signals, never by a business-side row quota.
    "complete": (None, None),
}


@dataclass(frozen=True, slots=True)
class CollectionScope:
    """One user-selected Reddit collection window and depth preset."""

    start_date: date
    end_date: date
    depth: str = "complete"

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if (self.end_date - self.start_date).days + 1 > 365:
            raise ValueError("collection range cannot exceed 365 days")
        if self.depth not in _DEPTH_PRESETS:
            raise ValueError("depth must be quick, standard, deep, or complete")

    @property
    def listing_limit_per_community(self) -> int | None:
        return _DEPTH_PRESETS[self.depth][0]

    @property
    def deep_read_limit_per_community(self) -> int | None:
        return _DEPTH_PRESETS[self.depth][1]


@dataclass(frozen=True, slots=True)
class CollectionCoverage:
    """Observed date coverage for one requested community."""

    community: str
    requested_start: date
    requested_end: date
    actual_start: date | None
    actual_end: date | None
    status: str
    scanned_posts: int


@dataclass(frozen=True, slots=True)
class RadarConfig:
    """Validated configuration needed by the core analysis workflow."""

    project: str
    communities: tuple[Community, ...]
    community_catalog_version: str = ""
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
