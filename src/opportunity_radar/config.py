"""YAML configuration loading for the community radar."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .models import CollectionSettings, Community, CommunityCatalog, RadarConfig


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
        elif isinstance(value, Mapping) and isinstance(value.get("name"), str):
            name = value["name"].strip()
            aliases = _text_list(value.get("aliases"), "aliases", required=require_metadata)
            include = _text_list(value.get("include"), "include", required=require_metadata)
            exclude = _text_list(value.get("exclude"), "exclude", required=require_metadata)
            slang = _text_list(value.get("slang"), "slang", required=require_metadata)
            category = _required_text(value.get("category"), "category") if require_metadata else _optional_text(value.get("category"))
            brand = _required_text(value.get("brand"), "brand") if require_metadata else _optional_text(value.get("brand"))
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
