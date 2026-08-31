"""Build the offline diesel-pickup Opportunity Radar demo.

This is a fixture-only presentation demo; it makes no Reddit or model calls.
Replace the input JSON with a run's ``analysis.json`` to render real results.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opportunity_radar.report import render_html
from opportunity_radar.topics import export_topic_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an offline diesel radar demo")
    parser.add_argument("--input", default="configs/diesel_demo_analysis.json")
    parser.add_argument("--output", default="outputs/diesel-demo")
    args = parser.parse_args()
    analysis = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    exported = export_topic_analysis(analysis, output_dir=output, formats=("json", "xlsx"))
    # Render the exact canonical projection used by the workbook so totals cannot drift.
    canonical = json.loads(exported.analysis_json.read_text(encoding="utf-8"))
    report_path = render_html(canonical, output / "report.html")
    print(json.dumps({
        "status": "ok",
        "mode": analysis.get("model_mode", "offline_demo_fixture"),
        "analysis_json": str(exported.analysis_json.resolve()),
        "report_html": str(report_path.resolve()),
        "excel": str(exported.workbook_path.resolve()),
        "community_topic_map": str((output / "community_topic_map.json").resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
