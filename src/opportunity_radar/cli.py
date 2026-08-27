"""Argparse-based Python CLI for Task 4."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .cli_app import RadarCliApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--run-id")

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
    return parser


def main(argv: list[str] | None = None, *, app: RadarCliApp | None = None) -> int:
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
    if arguments.command == "run":
        return app.run(arguments.config, run_id=arguments.run_id)
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
    raise ValueError(f"unsupported command: {arguments.command}")
