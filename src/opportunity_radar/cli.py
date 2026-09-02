"""Argparse-based Python CLI for Task 4."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any

from .cli_app import RadarCliApp
from .last30days_adapter import DEFAULT_HOT30_DOMAIN, Hot30Adapter, Last30DaysAdapter, project_root
from .models import CollectionScope
from .server import serve_local


DEFAULT_HOT30_RUNS_ROOT = Path(".local") / "runs" / "hot30"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor")

    hot30_parser = subparsers.add_parser("hot30", help="运行 vendored last30days 多平台热点引擎")
    hot30_subparsers = hot30_parser.add_subparsers(dest="hot30_command", required=True)
    hot30_plan = hot30_subparsers.add_parser("plan", help="生成三阶段 nominate/judge/finalize 命令")
    hot30_plan.add_argument("--run-id", required=True)
    hot30_plan.add_argument("--domain", default=DEFAULT_HOT30_DOMAIN)
    hot30_plan.add_argument("--runs-root")
    hot30_run = hot30_subparsers.add_parser("run", help="调用 Last30DaysAdapter 执行多平台热点")
    hot30_run.add_argument("--run-id", required=True)
    hot30_run.add_argument("--domain", default=DEFAULT_HOT30_DOMAIN)
    hot30_run.add_argument("--runs-root")
    hot30_run.add_argument("--dry-run", action="store_true", help="只输出三阶段命令，不启动采集")
    hot30_run.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)

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
    if arguments.command == "hot30":
        return _dispatch_hot30(arguments)
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


def _hot30_adapter(runs_root: str | None) -> Hot30Adapter:
    kwargs: dict[str, Any] = {"project_root": project_root()}
    kwargs["runs_root"] = Path(runs_root) if runs_root else project_root() / DEFAULT_HOT30_RUNS_ROOT
    return Hot30Adapter(**kwargs)


def _portable_path(value: str, *, root: Path, runs_root: Path) -> str:
    """Render local paths as copyable placeholders, never user-specific absolutes."""
    normalized = str(value).replace("\\", "/")
    project_prefix = str(root).replace("\\", "/").rstrip("/")
    runs_prefix = str(runs_root).replace("\\", "/").rstrip("/")
    if normalized == project_prefix or normalized.startswith(project_prefix + "/"):
        return "<PROJECT_ROOT>" + normalized[len(project_prefix):]
    if normalized == runs_prefix or normalized.startswith(runs_prefix + "/"):
        return "<RUNS_ROOT>" + normalized[len(runs_prefix):]
    return normalized


def _portable_plan(adapter: Hot30Adapter, run: Any, commands: Any) -> tuple[dict[str, str], dict[str, list[str]]]:
    root = project_root()
    runs_root = adapter.runs_root
    paths = {key: _portable_path(value, root=root, runs_root=runs_root) for key, value in run.as_dict().items()}
    rendered: dict[str, list[str]] = {}
    for name, command in commands.as_dict().items():
        rendered[name] = [
            "python" if index == 0 else "vendor/last30days/scripts/last30days.py" if index == 1
            else _portable_path(token, root=root, runs_root=runs_root)
            for index, token in enumerate(command)
        ]
    return paths, rendered


def _hot30_plan(arguments: argparse.Namespace) -> dict[str, Any]:
    adapter = _hot30_adapter(arguments.runs_root)
    run = adapter.prepare_run(arguments.run_id)
    paths, commands = _portable_plan(adapter, run, adapter.protocol_commands(run, domain=arguments.domain, emit="compact"))
    return {
        "status": "planned",
        "mode": "hot30",
        "run_id": arguments.run_id,
        "domain": " ".join(str(arguments.domain or "").split()),
        "paths": paths,
        "commands": commands,
    }


def _dispatch_hot30(arguments: argparse.Namespace) -> dict[str, Any]:
    if arguments.hot30_command == "plan":
        return _hot30_plan(arguments)
    if arguments.hot30_command != "run":
        raise ValueError(f"unsupported hot30 command: {arguments.hot30_command}")
    if arguments.dry_run:
        return _hot30_plan(arguments)
    runs_root = arguments.runs_root or str(project_root() / DEFAULT_HOT30_RUNS_ROOT)
    adapter = Last30DaysAdapter(project_root=project_root(), runs_root=Path(runs_root))
    # Let the adapter's single-segment validator own this boundary.  Do not
    # concatenate an untrusted run id before validation (``..`` must not escape
    # the configured runs root).
    output_dir = adapter.prepare_run(arguments.run_id).artifacts_dir
    return adapter.run_hot30(arguments.domain, output_dir, emit="compact")
