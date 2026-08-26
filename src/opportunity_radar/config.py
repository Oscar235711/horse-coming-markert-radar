"""YAML configuration loading for the community radar."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .models import CollectionSettings, Community, RadarConfig


def load_config(path: str | Path) -> RadarConfig:
    """Load approved communities while preserving the fixed 30/90-day policy."""
    document_path = Path(path)
    raw_document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    if not isinstance(raw_document, Mapping):
        raise ValueError("configuration must be a YAML mapping")

    _validate_fixed_windows(raw_document)
    communities = _load_communities(raw_document)
    project = str(raw_document.get("project", document_path.stem))
    return RadarConfig(
        project=project,
        communities=communities,
        collection=_load_collection(raw_document),
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


def _load_communities(document: Mapping[str, Any]) -> tuple[Community, ...]:
    configured = document.get("communities", document.get("subreddits", ()))
    if not isinstance(configured, list) or not configured:
        raise ValueError("configuration must contain at least one community")

    names: list[str] = []
    for value in configured:
        if isinstance(value, str):
            name = value.strip()
        elif isinstance(value, Mapping) and isinstance(value.get("name"), str):
            name = value["name"].strip()
        else:
            raise ValueError("each community must be a name or mapping with a name")
        if not name:
            raise ValueError("community names cannot be empty")
        names.append(name)
    return tuple(Community(name=name) for name in names)


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
