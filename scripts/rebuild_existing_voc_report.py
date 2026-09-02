"""Rebuild a strict Chinese DeepSeek VOC report from an existing raw run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from opportunity_radar.cli_app import RadarCliApp
from opportunity_radar.config import load_config, load_diesel_domain_config
from opportunity_radar.metrics import build_report_metrics
from opportunity_radar.models import CollectionScope
from opportunity_radar.report import render_html
from opportunity_radar.storage import create_run_paths
from opportunity_radar.topics import export_topic_analysis


def _load_env_file(path: Path) -> dict[str, str]:
    """Load only KEY=VALUE pairs; never print or persist secret values."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key not in {"DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_FLASH_MODEL", "DEEPSEEK_PRO_MODEL", "DEEPSEEK_MAX_TOKENS"}:
            continue
        value = value.strip().strip('"').strip("'")
        if value:
            values[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--env-file", default="D:/zuop/hermes/.env")
    arguments = parser.parse_args()

    environment = dict(os.environ)
    environment.update(_load_env_file(Path(arguments.env_file)))
    app = RadarCliApp(environment=environment)
    paths = create_run_paths(app.runs_root, arguments.source_run)
    state = json.loads(paths.state_path.read_text(encoding="utf-8"))
    config = load_config(paths.config_snapshot_path)
    scope_doc = state.get("collection_scope", {})
    scope = CollectionScope(
        start_date=__import__("datetime").date.fromisoformat(scope_doc["start_date"]),
        end_date=__import__("datetime").date.fromisoformat(scope_doc["end_date"]),
        depth=str(scope_doc.get("depth", "standard")),
    )
    collection = app._collector.load_from_raw(
        config.communities,
        paths=paths,
        as_of=app._now(),
        shortlist_limit=config.shortlist_per_community,
        scope=scope,
    )
    domain = load_diesel_domain_config(paths.config_snapshot_path)
    eligible, _audit = app._gate_threads(collection.deep_reads, config, domain)
    analyses = app._load_saved_analyses(paths)
    analyzed_threads = tuple(thread for thread in eligible if thread.post.post_id in analyses)
    analysis = app._aggregate_run(
        config,
        analyzed_threads,
        analyses,
        # Reuse the saved post-level DeepSeek analyses and run the community
        # consolidation through the configured Higress/DeepSeek Pro client.
        pro_consolidator=app._pro_consolidator,
        model_mode="deepseek_pro",
    )
    analysis["report_metrics"] = build_report_metrics(
        communities=tuple(dict.fromkeys(thread.post.subreddit for thread in analyzed_threads)),
        collection=collection,
        analyzed_threads=analyzed_threads,
        topics=tuple(analysis.get("topics", [])),
    )
    analysis["research_scope"] = {
        "start_date": scope.start_date.isoformat(),
        "end_date": scope.end_date.isoformat(),
        "depth": scope.depth,
        "coverage": state.get("coverage", {}),
        "note": "本预览复用既有原始证据；完整全站扩展任务完成后将由新结果替换。",
    }
    output = Path(arguments.output).resolve()
    artifacts = export_topic_analysis(analysis, output_dir=output, formats=("json", "xlsx"))
    report = render_html(analysis, output / "report.html")
    print(json.dumps({
        "analysis_json": str(artifacts.analysis_json),
        "xlsx": str(artifacts.workbook_path),
        "report_html": str(report),
        "analyzed_posts": len(analyzed_threads),
        "topics": len(analysis.get("topics", [])),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
