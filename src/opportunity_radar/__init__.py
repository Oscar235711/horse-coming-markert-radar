"""Opportunity Radar core package."""

from .cli_app import RadarCliApp
from .config import load_community_catalog, load_config, write_community_catalog
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
    CommunityCatalog,
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
from .topics import (
    EXCEL_SHEET_NAMES,
    EvidenceBackedClaim,
    PostSignal,
    ProTopicProposal,
    TopicAggregationResult,
    TopicAggregator,
    TopicEvidence,
    TopicExportArtifacts,
    export_topic_analysis,
)

__all__ = [
    "Community",
    "CollectionSettings",
    "CollectionFailure",
    "CollectionResult",
    "DEFAULT_BASE_URL",
    "DeepSeekClient",
    "DeepSeekError",
    "CommunityCatalog",
    "EvidenceClaim",
    "EvidenceBackedClaim",
    "EXCEL_SHEET_NAMES",
    "FLASH_MODEL",
    "HttpResponse",
    "NormalizedPost",
    "OpenCliCollector",
    "PostWindow",
    "PostAnalysis",
    "PostSignal",
    "PRO_MODEL",
    "ProTopicProposal",
    "RadarCliApp",
    "RadarConfig",
    "RunManifest",
    "RunPaths",
    "ShortlistedPost",
    "TopicRecord",
    "TopicCandidate",
    "TopicAggregationResult",
    "TopicAggregator",
    "TopicEvidence",
    "TopicExportArtifacts",
    "TopicRegistry",
    "WindowedPost",
    "ThreadComment",
    "ThreadDocument",
    "create_run_paths",
    "load_community_catalog",
    "load_config",
    "normalize_and_deduplicate",
    "read_manifest",
    "score_shortlist",
    "window_posts",
    "write_manifest",
    "write_community_catalog",
    "export_topic_analysis",
]
