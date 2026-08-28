"""YAML configuration loading for the community radar."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import CollectionSettings, Community, CommunityCatalog, RadarConfig


@dataclass(frozen=True, slots=True)
class DieselDictionaries:
    """Explicit, inspectable vocabulary used only for diesel-pickup relevance."""

    platforms: tuple[str, ...]
    products: tuple[str, ...]
    vehicle_terms: tuple[str, ...]
    scenarios: tuple[str, ...]
    brands: tuple[str, ...]
    slang: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DieselExclusions:
    """Hard boundaries that prevent generic automotive samples from entering analysis."""

    non_diesel_terms: tuple[str, ...]
    excluded_subreddits: tuple[str, ...]
    promotional_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KeywordSearchSettings:
    enabled: bool
    max_candidate_keywords: int
    max_posts_per_keyword: int
    require_human_approval: bool


@dataclass(frozen=True, slots=True)
class ReportSettings:
    formats: tuple[str, ...]
    offline_html: bool


@dataclass(frozen=True, slots=True)
class DieselDomainConfig:
    dictionaries: DieselDictionaries
    exclusions: DieselExclusions
    keyword_search: KeywordSearchSettings
    report: ReportSettings
    user_deep_dive_enabled: bool


def load_config(path: str | Path) -> RadarConfig:
    """Load approved communities while preserving the fixed 30/90-day policy."""
    document_path = Path(path)
    raw_document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    if not isinstance(raw_document, Mapping):
        raise ValueError("configuration must be a YAML mapping")

    _validate_fixed_windows(raw_document)
    catalog = _load_catalog_reference(raw_document, document_path)
    communities = catalog.communities if catalog is not None else _load_communities(raw_document)
    project = str(raw_document.get("project", document_path.stem))
    return RadarConfig(
        project=project,
        communities=communities,
        community_catalog_version=catalog.version if catalog is not None else str(raw_document.get("community_catalog_version", "")),
        collection=_load_collection(raw_document),
    )


def load_diesel_domain_config(path: str | Path) -> DieselDomainConfig:
    """Load V2's diesel-only dictionaries and non-secret runtime settings."""
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError("diesel configuration must be a YAML mapping")
    dictionaries = _mapping(document.get("dictionaries"), "dictionaries")
    exclusions = _mapping(document.get("exclusions"), "exclusions")
    keyword_search = _mapping(document.get("keyword_search"), "keyword_search")
    report = _mapping(document.get("report"), "report")
    profile = _mapping(document.get("user_deep_dive"), "user_deep_dive")
    return DieselDomainConfig(
        dictionaries=DieselDictionaries(
            platforms=_text_list(dictionaries.get("platforms"), "dictionaries.platforms", required=True),
            products=_text_list(dictionaries.get("products"), "dictionaries.products", required=True),
            vehicle_terms=_text_list(dictionaries.get("vehicle_terms"), "dictionaries.vehicle_terms", required=True),
            scenarios=_text_list(dictionaries.get("scenarios"), "dictionaries.scenarios", required=True),
            brands=_text_list(dictionaries.get("brands"), "dictionaries.brands", required=True),
            slang=_text_list(dictionaries.get("slang"), "dictionaries.slang", required=True),
        ),
        exclusions=DieselExclusions(
            non_diesel_terms=_text_list(exclusions.get("non_diesel_terms"), "exclusions.non_diesel_terms", required=True),
            excluded_subreddits=_text_list(exclusions.get("excluded_subreddits"), "exclusions.excluded_subreddits", required=True),
            promotional_terms=_text_list(exclusions.get("promotional_terms"), "exclusions.promotional_terms", required=True),
        ),
        keyword_search=KeywordSearchSettings(
            enabled=_as_bool(keyword_search.get("enabled"), "keyword_search.enabled"),
            max_candidate_keywords=_positive_int(keyword_search.get("max_candidate_keywords"), "keyword_search.max_candidate_keywords"),
            max_posts_per_keyword=_positive_int(keyword_search.get("max_posts_per_keyword"), "keyword_search.max_posts_per_keyword"),
            require_human_approval=_as_bool(keyword_search.get("require_human_approval"), "keyword_search.require_human_approval"),
        ),
        report=ReportSettings(
            formats=_text_list(report.get("formats"), "report.formats", required=True),
            offline_html=_as_bool(report.get("offline_html"), "report.offline_html"),
        ),
        user_deep_dive_enabled=_as_bool(profile.get("enabled"), "user_deep_dive.enabled"),
    )


def load_community_catalog(path: str | Path) -> CommunityCatalog:
    """Load a versioned community catalog with the governance fields Task 4 requires."""
    document_path = Path(path)
    raw_document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    if not isinstance(raw_document, Mapping):
        raise ValueError("community catalog must be a YAML mapping")
    version = raw_document.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("community catalog version must be a non-empty string")
    communities = _load_communities(raw_document, require_metadata=True)
    return CommunityCatalog(version=version.strip(), communities=communities)


def write_community_catalog(path: str | Path, catalog: CommunityCatalog) -> None:
    """Persist a versioned catalog with stable ordering and UTF-8 YAML."""
    document = {
        "version": catalog.version,
        "communities": [
            {
                "name": community.name,
                "aliases": list(community.aliases),
                "include": list(community.include),
                "exclude": list(community.exclude),
                "category": community.category,
                "brand": community.brand,
                "slang": list(community.slang),
                "community_id": community.community_id or f"r/{community.name}",
                "status": community.status,
            }
            for community in catalog.communities
        ],
    }
    Path(path).write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _validate_fixed_windows(document: Mapping[str, Any]) -> None:
    expected_values = {
        "time_range_days": 90,
        "current_window_days": 30,
        "baseline_window_days": 60,
    }
    for key, expected in expected_values.items():
        if key in document and document[key] != expected:
            raise ValueError("community radar requires the fixed 30/90-day windows")

    windows = document.get("windows", {})
    if windows is None:
        return
    if not isinstance(windows, Mapping):
        raise ValueError("windows must be a YAML mapping")
    nested_expected_values = {
        "current_days": 30,
        "baseline_days": 60,
        "total_days": 90,
    }
    for key, expected in nested_expected_values.items():
        if key in windows and windows[key] != expected:
            raise ValueError("community radar requires the fixed 30/90-day windows")


def _load_catalog_reference(document: Mapping[str, Any], document_path: Path) -> CommunityCatalog | None:
    catalog_path = document.get("community_catalog_path")
    if catalog_path is None:
        return None
    if not isinstance(catalog_path, str) or not catalog_path.strip():
        raise ValueError("community_catalog_path must be a non-empty string")
    resolved = Path(catalog_path.strip())
    if not resolved.is_absolute():
        resolved = document_path.parent / resolved
    return load_community_catalog(resolved)


def _load_communities(document: Mapping[str, Any], *, require_metadata: bool = False) -> tuple[Community, ...]:
    configured = document.get("communities", document.get("subreddits", ()))
    if not isinstance(configured, list) or not configured:
        raise ValueError("configuration must contain at least one community")

    communities: list[Community] = []
    for value in configured:
        if isinstance(value, str):
            name = value.strip()
            aliases = ()
            include = ()
            exclude = ()
            category = ""
            brand = ""
            slang = ()
            community_id = f"r/{name}"
            status = "approved"
        elif isinstance(value, Mapping) and isinstance(value.get("name"), str):
            name = value["name"].strip()
            aliases = _text_list(value.get("aliases"), "aliases", required=require_metadata)
            include = _text_list(value.get("include"), "include", required=require_metadata)
            exclude = _text_list(value.get("exclude"), "exclude", required=require_metadata)
            slang = _text_list(value.get("slang"), "slang", required=require_metadata)
            category = _required_text(value.get("category"), "category") if require_metadata else _optional_text(value.get("category"))
            brand = _required_text(value.get("brand"), "brand") if require_metadata else _optional_text(value.get("brand"))
            community_id = _optional_text(value.get("community_id")) or f"r/{name}"
            status = _optional_text(value.get("status")) or "approved"
        else:
            raise ValueError("each community must be a name or mapping with a name")
        if not name:
            raise ValueError("community names cannot be empty")
        if require_metadata and not aliases:
            raise ValueError("community aliases must contain at least one value")
        communities.append(
            Community(
                name=name,
                aliases=aliases,
                include=include,
                exclude=exclude,
                category=category,
                brand=brand,
                slang=slang,
                community_id=community_id,
                status=status,
            )
        )
    return tuple(communities)


def _load_collection(document: Mapping[str, Any]) -> CollectionSettings:
    configured = document.get("collection", {})
    if configured is None:
        configured = {}
    if not isinstance(configured, Mapping):
        raise ValueError("collection must be a YAML mapping")
    defaults = CollectionSettings()
    return CollectionSettings(
        request_interval_seconds=_positive_float(
            configured.get("request_interval_seconds", defaults.request_interval_seconds),
            "collection.request_interval_seconds",
        ),
        comments_per_post=_positive_int(
            configured.get("comments_per_post", defaults.comments_per_post),
            "collection.comments_per_post",
        ),
        comment_depth=_positive_int(
            configured.get("comment_depth", defaults.comment_depth), "collection.comment_depth"
        ),
        replies_per_comment=_positive_int(
            configured.get("replies_per_comment", defaults.replies_per_comment),
            "collection.replies_per_comment",
        ),
        max_comment_length=_positive_int(
            configured.get("max_comment_length", defaults.max_comment_length),
            "collection.max_comment_length",
        ),
        expand_more=_as_bool(configured.get("expand_more", defaults.expand_more), "collection.expand_more"),
        expand_rounds=_positive_int(
            configured.get("expand_rounds", defaults.expand_rounds), "collection.expand_rounds"
        ),
    )


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a YAML mapping")
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    try:
        converted = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a positive integer") from error
    if converted < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return converted


def _positive_float(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive number")
    try:
        converted = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a positive number") from error
    if converted <= 0:
        raise ValueError(f"{field_name} must be a positive number")
    return converted


def _as_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be true or false")
    return value


def _text_list(value: object, field_name: str, *, required: bool) -> tuple[str, ...]:
    if value is None:
        if required:
            raise ValueError(f"{field_name} must be a list of strings")
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    items = tuple(_required_text(item, field_name) for item in value)
    if required and not items:
        raise ValueError(f"{field_name} must contain at least one value")
    return items


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
