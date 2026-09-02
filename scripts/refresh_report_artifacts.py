"""Refresh HTML/XLSX projections from an existing canonical analysis.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from opportunity_radar.report import render_html
from opportunity_radar.topics import export_topic_analysis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", required=True)
    args = parser.parse_args()
    source = Path(args.analysis).resolve()
    analysis = json.loads(source.read_text(encoding="utf-8"))
    if any(isinstance(topic, dict) and topic.get("model_mode") == "deepseek_pro" for topic in analysis.get("topics", [])):
        analysis["model_mode"] = "deepseek_pro"
    for topic in analysis.get("topics", []):
        for evidence in topic.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            evidence.setdefault("quote_original", evidence.get("claim_en", ""))
            evidence.setdefault("translation_zh", evidence.get("claim_zh", ""))
        for field in ("summary", "seller_insight", "scenes", "user_tasks", "pains", "needs", "current_solutions", "gaps", "opportunity_hypotheses", "consequences", "risks"):
            for claim in topic.get("claim_evidence", {}).get(field, []) if isinstance(topic.get("claim_evidence", {}).get(field), list) else []:
                if isinstance(claim, dict):
                    claim.setdefault("explanation", "")
    output_dir = source.parent
    export_topic_analysis(analysis, output_dir=output_dir, formats=("json", "xlsx"))
    render_html(analysis, output_dir / "report.html")
    print(json.dumps({"analysis": str(source), "report": str(output_dir / "report.html"), "xlsx": str(output_dir / "community_topics.xlsx")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
