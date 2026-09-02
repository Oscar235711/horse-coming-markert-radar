"""Argparse-based Python CLI for Task 4."""

from __future__ import annotations

import argparse
from datetime import date
import json
import sys
from typing import Any

from .cli_app import RadarCliApp
from .models import CollectionScope
from .server import serve_local


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor")

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--config", default="configs/diesel_90d.yaml")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--no-open", action="store_true")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--start-date")
    run_parser.add_argument("--end-date")
    run_parser.add_argument("--depth", choices=("quick", "standard", "deep", "complete"), default="complete")
    run_parser.add_argument("--analysis-engine", choices=("codex", "rules", "deepseek"), default="codex")
    run_parser.add_argument("--research-question", default="", help="自然语言研究问题；系统会自动扩展检索词")
    run_parser.add_argument("--communities", default="")
    run_parser.add_argument("--keywords", default="", help="可选，逗号分隔的已激活关键词")

    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--run-id", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--run-id", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--run-id", required=True)
    export_parser.add_argument("--formats", default="json,xlsx")

    communities_parser = subparsers.add_parser("communities")
    communities_subparsers = communities_parser.add_subparsers(dest="communities_command", required=True)

    suggest_parser = communities_subparsers.add_parser("suggest")
    suggest_parser.add_argument("--run-id", required=True)

    approve_parser = communities_subparsers.add_parser("approve")
    approve_parser.add_argument("--suggestion", required=True)
    approve_parser.add_argument("--suggestion-id", required=True)

    keywords_parser = subparsers.add_parser("keywords")
    keywords_subparsers = keywords_parser.add_subparsers(dest="keywords_command", required=True)
    keyword_suggest_parser = keywords_subparsers.add_parser("suggest")
    keyword_suggest_parser.add_argument("--run-id", required=True)
    keyword_approve_parser = keywords_subparsers.add_parser("approve")
    keyword_approve_parser.add_argument("--file", required=True)
    return parser


def main(argv: list[str] | None = None, *, app: RadarCliApp | None = None) -> int:
    # Windows can start Python with a legacy GBK console even when PowerShell
    # itself is configured for UTF-8.  Radar emits Chinese diagnostics and
    # report paths, so make the process boundary deterministic.  Test
    # capture streams and embedders may not expose ``reconfigure``; in that
    # case leave their stream untouched.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    arguments = parser.parse_args(argv)
    application = app or RadarCliApp()

    try:
        result = _dispatch(application, arguments)
    except Exception as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _dispatch(app: RadarCliApp, arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.command == "doctor":
        return app.doctor()
    if arguments.command == "serve":
        return serve_local(
            app,
            config_path=arguments.config,
            host=arguments.host,
            port=arguments.port,
            open_browser=not arguments.no_open,
        )
    if arguments.command == "run":
        if bool(arguments.start_date) != bool(arguments.end_date):
            raise ValueError("--start-date and --end-date must be provided together")
        scope = None
        if arguments.start_date and arguments.end_date:
            scope = CollectionScope(
                start_date=date.fromisoformat(arguments.start_date),
                end_date=date.fromisoformat(arguments.end_date),
                depth=arguments.depth,
            )
        communities = tuple(value.strip() for value in arguments.communities.split(",") if value.strip())
        keywords = tuple(value.strip() for value in arguments.keywords.split(",") if value.strip())
        run_kwargs = dict(
            run_id=arguments.run_id,
            scope=scope,
            analysis_engine=arguments.analysis_engine,
            selected_communities=communities,
        )
        if arguments.research_question:
            run_kwargs["research_question"] = arguments.research_question
        if keywords:
            run_kwargs["selected_keywords"] = keywords
        return app.run(
            arguments.config,
            **run_kwargs,
        )
    if arguments.command == "resume":
        return app.resume(arguments.run_id)
    if arguments.command == "status":
        return app.status(arguments.run_id)
    if arguments.command == "export":
        formats = tuple(value.strip() for value in arguments.formats.split(",") if value.strip())
        return app.export(arguments.run_id, formats=formats)
    if arguments.command == "communities" and arguments.communities_command == "suggest":
        return app.communities_suggest(arguments.run_id)
    if arguments.command == "communities" and arguments.communities_command == "approve":
        return app.communities_approve(arguments.suggestion, suggestion_id=arguments.suggestion_id)
    if arguments.command == "keywords" and arguments.keywords_command == "suggest":
        return app.keywords_suggest(arguments.run_id)
    if arguments.command == "keywords" and arguments.keywords_command == "approve":
        return app.keywords_approve(arguments.file)
    raise ValueError(f"unsupported command: {arguments.command}")
