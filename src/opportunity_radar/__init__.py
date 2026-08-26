"""Opportunity Radar core package."""

from .config import load_config
from .models import (
    Community,
    CollectionSettings,
    NormalizedPost,
    PostWindow,
    RadarConfig,
    RunManifest,
    ShortlistedPost,
    TopicRecord,
    WindowedPost,
)
from .normalization import normalize_and_deduplicate
from .scoring import score_shortlist
from .storage import TopicRegistry, RunPaths, create_run_paths, read_manifest, write_manifest
from .windowing import window_posts

__all__ = [
    "Community",
    "CollectionSettings",
    "NormalizedPost",
    "PostWindow",
    "RadarConfig",
    "RunManifest",
    "RunPaths",
    "ShortlistedPost",
    "TopicRecord",
    "TopicRegistry",
    "WindowedPost",
    "create_run_paths",
    "load_config",
    "normalize_and_deduplicate",
    "read_manifest",
    "score_shortlist",
    "window_posts",
    "write_manifest",
]
