"""Small self-contained Community -> Topic -> Evidence HTML report.

The report intentionally has no CDN, fetch, or server dependency so a run can be
opened directly from Windows Explorer.  It is a projection of ``analysis.json``;
the model is never called while rendering.
"""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any, Mapping


def render_html(analysis: Mapping[str, Any], output_path: str | Path) -> Path:
    """Write a Chinese/English, filterable offline report and return its path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(analysis), ensure_ascii=False, separators=(",", ":"))
    safe_payload = payload.replace("<", "\\u003c")
    topics = [item for item in analysis.get("topics", []) if isinstance(item, Mapping)]
    communities = list(dict.fromkeys(str(item) for item in analysis.get("communities", []) if item))
    if not communities:
        communities = list(dict.fromkeys(str(item.get("community", "未知")) for item in topics))
    formal = [item for item in topics if item.get("status") == "formal"]
    weak = [item for item in topics if item.get("status") != "formal"]
    cards = "\n".join(_topic_card(item) for item in sorted(topics, key=lambda value: (-float(value.get("heat_score", 0) or 0), str(value.get("label_en", "")))))
    community_options = "<option value=\"\">全部社区</option>" + "".join(
        f"<option value=\"{escape(name, quote=True)}\">{escape(name)}</option>" for name in communities
    )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Opportunity Radar｜柴油皮卡社区热点</title>
<style>
:root{{--bg:#f4f7fb;--ink:#122033;--muted:#617087;--line:#dce4ef;--blue:#2f6fed;--orange:#e78936;--green:#2b9b72}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
header{{background:linear-gradient(135deg,#132b4d,#285d9e);color:#fff;padding:28px max(22px,calc((100% - 1180px)/2)) 24px}}
h1{{margin:0;font-size:25px}}header p{{margin:5px 0 0;color:#dbe9ff}}main{{max-width:1180px;margin:20px auto;padding:0 18px}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}}.stat,.panel,.topic{{background:#fff;border:1px solid var(--line);border-radius:12px;box-shadow:0 4px 14px #17365d0d}}
.stat{{padding:15px 17px}}.stat b{{display:block;font-size:25px;color:var(--blue)}}.stat span{{color:var(--muted)}}
.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}input,select{{border:1px solid var(--line);border-radius:8px;background:#fff;padding:9px 11px;color:var(--ink)}}input{{min-width:270px}}
.layout{{display:grid;grid-template-columns:250px 1fr;gap:16px}}.panel{{padding:16px;align-self:start;position:sticky;top:12px}}.panel h2{{font-size:15px;margin:0 0 10px}}.community{{display:block;padding:7px 9px;border-radius:7px;color:var(--ink)}}.community:hover{{background:#eef4ff}}
.topic{{padding:18px;margin-bottom:14px}}.topic-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}h2{{font-size:18px;margin:0 0 2px}}h3{{font-size:14px;margin:16px 0 4px;color:#294a73}}.en{{color:var(--muted);font-size:12px}}.badge{{display:inline-block;border-radius:999px;padding:3px 9px;background:#e9f1ff;color:#2355a5;font-size:12px;margin:2px 3px 2px 0}}.badge.trend{{background:#e9f8f1;color:var(--green)}}.badge.weak{{background:#fff2df;color:#a7651d}}.heat{{font-size:25px;font-weight:700;color:var(--orange);white-space:nowrap}}.summary{{background:#f6f9fd;border-left:3px solid var(--blue);padding:8px 11px;margin:10px 0}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px 20px}}.field{{min-width:0}}.field strong{{display:block;color:#294a73;font-size:12px}}.field ul{{margin:2px 0 0;padding-left:18px}}.field li{{margin:2px 0}}
.evidence{{border-top:1px solid var(--line);margin-top:13px;padding-top:10px}}.ev{{padding:8px 0;border-bottom:1px dashed var(--line)}}.ev:last-child{{border:0}}.ev a{{color:var(--blue);font-weight:600;text-decoration:none}}.ev a:hover{{text-decoration:underline}}.zh{{color:#31445b;margin-top:2px}}.meta{{color:var(--muted);font-size:12px}}
.keywords span{{font-size:12px;margin:3px 4px 3px 0;padding:4px 8px;border-radius:14px;background:#edf3fc;display:inline-block}}.empty{{color:var(--muted);padding:20px;text-align:center}}
@media(max-width:760px){{.stats{{grid-template-columns:repeat(2,1fr)}}.layout{{grid-template-columns:1fr}}.panel{{position:static}}.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>Opportunity Radar｜柴油皮卡社区热点</h1><p>社区 → 热门话题 → 具体帖子/评论证据　·　结果是机会假设，不是开品结论</p></header>
<main><section class="stats"><div class="stat"><b>{len(communities)}</b><span>扫描社区</span></div><div class="stat"><b>{len(formal)}</b><span>正式话题</span></div><div class="stat"><b>{len(weak)}</b><span>弱信号</span></div><div class="stat"><b>{escape(str(analysis.get('generated_at', ''))[:10])}</b><span>运行日期</span></div></section>
<div class="toolbar"><select id="communityFilter">{community_options}</select><input id="search" placeholder="搜索话题、痛点、车型或关键词…"><span class="meta" style="padding:9px 0">当前页面来自同一份 analysis.json</span></div>
<div class="layout"><aside class="panel"><h2>社区</h2>{''.join(f'<div class="community">{escape(name)}</div>' for name in communities)}<h2 style="margin-top:18px">关键词</h2><div class="keywords">{_keywords(analysis, topics)}</div><p class="meta">点击卡片下方证据链接可回到 Reddit 原帖。未知项不会被补写成事实。</p></aside><section id="topics">{cards or '<div class="panel empty">暂无满足证据门槛的话题</div>'}</section></div></main>
<script id="analysis-data" type="application/json">{safe_payload}</script>
<script>
const filter=document.querySelector('#communityFilter'), search=document.querySelector('#search');
function apply(){{const c=filter.value.toLowerCase(), q=search.value.toLowerCase();document.querySelectorAll('.topic').forEach(el=>{{const ok=(!c||el.dataset.community===c)&&(!q||el.innerText.toLowerCase().includes(q));el.style.display=ok?'block':'none';}})}}
filter.addEventListener('change',apply);search.addEventListener('input',apply);
</script></body></html>"""
    output.write_text(html, encoding="utf-8")
    # Keep a graph-ready projection next to the report for the next visual layer.
    (output.parent / "community_topic_map.json").write_text(
        json.dumps(build_topic_map(analysis), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


def build_topic_map(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Return community/topic nodes and edges without introducing a graph runtime."""
    topics = [item for item in analysis.get("topics", []) if isinstance(item, Mapping)]
    communities = [str(item) for item in analysis.get("communities", []) if item]
    return {
        "nodes": ([{"id": f"community:{name}", "type": "community", "label": name} for name in communities]
                  + [{"id": str(item.get("topic_id", "")), "type": "topic", "label": item.get("label_zh", item.get("label_en", "")), "community": item.get("community")} for item in topics]),
        "edges": [{"source": f"community:{item.get('community')}", "target": item.get("topic_id")} for item in topics if item.get("topic_id")],
    }


def _topic_card(topic: Mapping[str, Any]) -> str:
    community = str(topic.get("community", "未知"))
    label_zh = str(topic.get("label_zh", "未命名话题"))
    label_en = str(topic.get("label_en", "Unnamed topic"))
    evidence = [item for item in topic.get("evidence", []) if isinstance(item, Mapping)]
    return f'''<article class="topic" data-community="{escape(community.casefold(), quote=True)}"><div class="topic-head"><div><span class="badge">{escape(community)}</span><h2>{escape(label_zh)}</h2><div class="en">{escape(label_en)}</div></div><div class="heat">{float(topic.get("heat_score", 0) or 0):.0f}<span class="meta"> /100</span></div></div>
<div><span class="badge trend">趋势：{escape(str(topic.get("trend", "unknown")))}</span><span class="badge">帖子 {escape(str(topic.get("post_count", 0)))}</span><span class="badge">作者 {escape(str(topic.get("author_count", 0)))}</span><span class="badge">评论者 {escape(str(topic.get("commenter_count", 0)))}</span></div>
<div class="summary"><strong>摘要：</strong>{escape(str(topic.get("summary", "unknown")))}</div><div class="grid">{_field("用户痛点", topic.get("pains"))}{_field("用户需求", topic.get("needs"))}{_field("当前方案", topic.get("current_solutions"))}{_field("方案不足", topic.get("gaps"))}{_field("机会假设", topic.get("opportunity_hypotheses"))}{_field("车型/平台/场景", [*(topic.get("vehicles") or []), *(topic.get("platforms") or []), *(topic.get("scenarios") or [])])}</div>{_evidence(evidence)}</article>'''


def _field(label: str, values: Any) -> str:
    values = values if isinstance(values, list) else ([values] if values else [])
    items = "".join(f"<li>{escape(str(value))}</li>" for value in values if value)
    return f'<div class="field"><strong>{escape(label)}</strong><ul>{items or "<li>未知</li>"}</ul></div>'


def _evidence(items: list[Mapping[str, Any]]) -> str:
    if not items:
        return '<div class="evidence meta">暂无可回溯证据</div>'
    body = "".join(
        f'<div class="ev"><a href="{escape(str(item.get("url", "")), quote=True)}" target="_blank" rel="noreferrer">打开 Reddit 证据</a> <span class="meta">{escape(str(item.get("stance", "supporting")))}</span><div>{escape(str(item.get("claim_en", "")))}</div><div class="zh">中文：{escape(str(item.get("claim_zh", "")))}</div></div>'
        for item in items
    )
    return f'<div class="evidence"><h3>帖子/评论证据（{len(items)}）</h3>{body}</div>'


def _keywords(analysis: Mapping[str, Any], topics: list[Mapping[str, Any]]) -> str:
    values: list[str] = []
    for item in analysis.get("keyword_candidates", []) if isinstance(analysis.get("keyword_candidates"), list) else []:
        if isinstance(item, Mapping):
            values.append(str(item.get("term", "")))
        elif item:
            values.append(str(item))
    if not values:
        for topic in topics:
            values.extend(str(value) for value in (topic.get("category_tags") or []) if value)
            values.extend(str(value) for value in (topic.get("platforms") or []) if value)
    return "".join(f"<span>{escape(value)}</span>" for value in dict.fromkeys(values) if value) or "<span>暂无</span>"
