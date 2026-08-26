"""Opportunity Radar core package."""

from .config import load_config
from .collector import (
    CollectionFailure,
    CollectionResult,
    OpenCliCollector,
    ThreadComment,
    ThreadDocument,
)
from .deepseek import (
    DEFAULT_BASE_URL,
    FLASH_MODEL,
    PRO_MODEL,
    DeepSeekClient,
    DeepSeekError,
    EvidenceClaim,
    HttpResponse,
    PostAnalysis,
    TopicCandidate,
)
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
    "CollectionFailure",
    "CollectionResult",
    "DEFAULT_BASE_URL",
    "DeepSeekClient",
    "DeepSeekError",
    "EvidenceClaim",
    "FLASH_MODEL",
    "HttpResponse",
    "NormalizedPost",
    "OpenCliCollector",
    "PostWindow",
    "PostAnalysis",
    "PRO_MODEL",
    "RadarConfig",
    "RunManifest",
    "RunPaths",
    "ShortlistedPost",
    "TopicRecord",
    "TopicCandidate",
    "TopicRegistry",
    "WindowedPost",
    "ThreadComment",
    "ThreadDocument",
    "create_run_paths",
    "load_config",
    "normalize_and_deduplicate",
    "read_manifest",
    "score_shortlist",
    "window_posts",
    "write_manifest",
]
