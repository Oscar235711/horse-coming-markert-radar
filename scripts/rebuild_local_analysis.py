"""Rebuild one collected run with the local, no-DeepSeek VOC analyzer.

This is useful when a Reddit crawl already exists and we want to inspect the
data immediately.  It never calls a model or writes credentials; it reuses
the saved listings/threads and the same evidence gate/exporters as the main
CLI.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from datetime import UTC, datetime

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from opportunity_radar.cli_app import RadarCliApp, _rule_extract_post  # noqa: E402
from opportunity_radar.collector import _parse_records, _thread_from_raw  # noqa: E402
from opportunity_radar.config import load_config, load_diesel_domain_config  # noqa: E402
from opportunity_radar.normalization import normalize_and_deduplicate  # noqa: E402
from opportunity_radar.report import render_html  # noqa: E402
from opportunity_radar.library import update_project_library  # noqa: E402
from opportunity_radar.scoring import score_shortlist  # noqa: E402
from opportunity_radar.storage import create_run_paths, write_normalized_records  # noqa: E402
from opportunity_radar.topics import export_topic_analysis  # noqa: E402
from opportunity_radar.windowing import window_posts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default="20260828T-live")
    args = parser.parse_args()
    runs_root = REPO_ROOT / ".local" / "runs"
    paths = create_run_paths(runs_root, args.run_id)
    config_path = REPO_ROOT / "configs" / "diesel_90d.yaml"
    config = load_config(config_path)
    domain = load_diesel_domain_config(config_path)

    raw_records: list[dict[str, object]] = []
    for path in sorted(paths.raw_listings_dir.glob("*.json")):
        # Community__surface.json is the on-disk projection written by the
        # collector; split only once so a future community name can contain an
        # underscore without changing the source surface contract.
        stem = path.stem
        community, _, surface = stem.partition("__")
        try:
            records = _parse_records(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for record in records:
            item = dict(record)
            item["source_surface"] = surface or "saved"
            item.setdefault("subreddit", community)
            raw_records.append(item)
    posts = normalize_and_deduplicate(raw_records)
    post_by_short_id = {post.post_id.removeprefix("t3_"): post for post in posts}
    # Reapply the production shortlist rule so a local rebuild uses the same
    # 30-post-per-community budget as a normal run, while still retaining all
    # normalized posts in the run's JSONL archive.
    as_of = datetime.now(UTC)
    shortlist_ids: set[str] = set()
    for community in config.communities:
        community_posts = tuple(post for post in posts if post.subreddit.casefold() == community.name.casefold())
        shortlist_ids.update(item.post.post_id for item in score_shortlist(window_posts(community_posts, as_of=as_of), limit=30))

    threads = []
    for path in sorted(paths.raw_threads_dir.glob("*.json")):
        post = post_by_short_id.get(path.stem)
        if post is not None and post.post_id not in shortlist_ids:
            post = None
        if post is None:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            threads.append(_thread_from_raw(raw, post))
        except Exception:
            continue
    threads.sort(key=lambda thread: thread.post.created_at, reverse=True)
    write_normalized_records(
        paths,
        posts,
        [
            {"post_id": thread.post.post_id, "parent_id": "", "depth": 1, **{
                "comment_id": comment.comment_id,
                "body": comment.body,
                "url": comment.url,
                "author": comment.author,
            }}
            for thread in threads for comment in thread.comments
        ],
    )

    app = RadarCliApp(runs_root=runs_root, library_root=REPO_ROOT / "library", environment={"DEEPSEEK_API_KEY": ""})
    eligible, audit = app._gate_threads(threads, config, domain)
    analyses = {thread.post.post_id: _rule_extract_post(thread, domain) for thread in eligible}
    analysis = app._aggregate_run(config, eligible, analyses, paths=paths)
    library_status = update_project_library(
        app._library_root,
        analysis,
        run_id=args.run_id,
        posts=[thread.post for thread in eligible],
        comments=[
            {"post_id": thread.post.post_id, "comment_id": comment.comment_id, "body": comment.body,
             "url": comment.url, "author": comment.author}
            for thread in eligible for comment in thread.comments
        ],
        now=app._now(),
    )
    analysis["project_library"] = {
        "version": library_status.get("versions", {}),
        "counts": library_status.get("counts", {}),
        "root": "library",
    }
    analysis["collection_source"] = "saved OpenCLI Reddit crawl"
    analysis["analysis_note"] = "本报告由本地规则/VOC分析生成，未调用DeepSeek；产品方向均为机会假设。"
    analysis["crawl_counts"] = {
        "saved_listing_records": len(raw_records),
        "normalized_posts": len(posts),
        "saved_threads": len(threads),
        "eligible_threads": len(eligible),
        "saved_comments": sum(len(thread.comments) for thread in threads),
    }
    analysis["evidence_gate"] = {
        "qualified_posts": len(audit.get("qualified_posts", [])),
        "excluded_posts": len(audit.get("excluded_posts", [])),
        "comments": len(audit.get("comments", [])),
    }
    exported = export_topic_analysis(
        analysis,
        output_dir=paths.artifacts_dir,
        formats=("json", "xlsx"),
        environment={"DEEPSEEK_API_KEY": ""},
    )
    render_html(json.loads(exported.analysis_json.read_text(encoding="utf-8")), paths.artifacts_dir / "report.html")

    # Keep the run status useful to `radar status` after this offline rebuild.
    state = json.loads(paths.state_path.read_text(encoding="utf-8")) if paths.state_path.exists() else {}
    state.setdefault("counts", {})
    state["counts"].update({
        "candidate_count": len(posts),
        "shortlist_count": state["counts"].get("shortlist_count", 0),
        "deep_read_count": len(threads),
        "eligible_post_count": len(eligible),
        "excluded_post_count": len(threads) - len(eligible),
        "analyzed_posts": len(analyses),
        "comment_evidence_count": sum(len(thread.comments) for thread in threads),
        "topic_count": len(analysis.get("topics", [])),
        "failure_count": 0,
    })
    state["stage"] = "exported"
    state["status"] = "completed"
    state["artifacts"] = {
        "analysis_json": str(exported.analysis_json),
        "community_topics_json": str(exported.community_topics_json),
        "community_topics_xlsx": str(exported.workbook_path),
        "report_html": str(paths.artifacts_dir / "report.html"),
    }
    paths.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "run_id": args.run_id,
        "saved_listing_records": len(raw_records),
        "normalized_posts": len(posts),
        "threads": len(threads),
        "eligible": len(eligible),
        "comments": sum(len(thread.comments) for thread in threads),
        "topics": len(analysis.get("topics", [])),
        "analysis_json": str(exported.analysis_json),
        "report_html": str(paths.artifacts_dir / "report.html"),
        "workbook": str(exported.workbook_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
