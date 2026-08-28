"""Self-contained WhatToSell-style community/topic graph report."""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any, Mapping


def render_html(analysis: Mapping[str, Any], output_path: str | Path) -> Path:
    """Write an offline, clickable community → topic → evidence report."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    topics = [item for item in analysis.get("topics", []) if isinstance(item, Mapping)]
    communities = list(dict.fromkeys(str(item) for item in analysis.get("communities", []) if item))
    if not communities:
        communities = list(dict.fromkeys(str(item.get("community", "未知")) for item in topics))
    payload = json.dumps(dict(analysis), ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    formal = sum(1 for item in topics if item.get("status") == "formal")
    html = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Opportunity Radar｜社区话题图谱</title>
<style>
:root{{--bg:#f4f2ee;--ink:#1a1a1a;--muted:#77736c;--line:#dedad4;--blue:#4d6575;--orange:#c8922a;--green:#3b8068}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
header{{height:57px;padding:0 24px;background:#f4f2ee;border-bottom:1px solid #e8e4de;display:flex;justify-content:space-between;align-items:center;position:relative;z-index:10}}
h1{{font:700 18px/1 "IBM Plex Mono",ui-monospace,monospace;margin:0;letter-spacing:-.02em}}header p{{display:none}}.brand{{font:700 12px/1 ui-monospace,monospace;color:#1a1a1a;white-space:nowrap}}header .brand::first-letter{{color:var(--orange)}}
main{{height:calc(100vh - 57px);padding:0;margin:0;max-width:none;position:relative}}.toolbar{{position:fixed;z-index:5;top:70px;left:50%;transform:translateX(-50%);display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
select,input{{border:1px solid #d8d3cb;background:#fff;border-radius:999px;padding:8px 12px;color:var(--ink);box-shadow:0 1px 4px #493b250e}}input{{min-width:280px}}.hint{{color:var(--muted);font:11px ui-monospace,monospace;background:#f4f2eeaa;padding:4px 8px;border-radius:999px}}
.legend{{position:fixed;z-index:4;left:16px;bottom:18px;width:218px;display:flex;flex-direction:column;gap:8px;color:#6b6861;font-size:11px;margin:0;padding:14px;background:#f4f2eeeb;border-top:1px solid #dedad4}}.legend i{{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:-2px;margin-right:5px}}.hollow{{border:1.5px solid #8a8378;background:transparent}}.solid{{background:var(--orange)}}
.graph-shell{{position:fixed;z-index:1;inset:57px 340px 0 250px;background:#f4f2ee;overflow:hidden}}svg{{display:block;width:100%;height:100%;min-height:0;background:#f4f2ee}}
.edge{{stroke:#d0c9be;stroke-width:1.2;opacity:.78}}.community-node,.topic-node{{cursor:pointer}}.community-node circle{{fill:transparent;stroke:#8a8378;stroke-width:1.5}}.community-node:hover circle,.community-node.active circle{{stroke:#1a1a1a;stroke-width:2.8}}.topic-node circle{{stroke:#f4f2ee;stroke-width:2}}.topic-node:hover circle,.topic-node.active circle{{stroke:#1a1a1a;stroke-width:3}}.node-label{{font-size:12px;fill:#27231f;pointer-events:none;text-anchor:middle;font-weight:600}}.topic-label{{font-size:11px;fill:#5b554d;pointer-events:none;text-anchor:middle}}.community-count{{font-size:10px;fill:#8a8378;pointer-events:none;text-anchor:middle}}
.below{{display:block;margin:0}}.side,.detail{{position:fixed;z-index:6;top:57px;bottom:0;background:#f4f2ee;border:0;border-radius:0;padding:16px;overflow:auto}}.side{{left:0;width:250px;border-right:1px solid #dedad4}}.detail{{right:0;width:340px;border-left:1px solid #dedad4}}.side h2,.detail h2{{font-size:16px;margin:0 0 5px}}.side p{{color:var(--muted);font-size:11px}}.topic-list{{display:flex;flex-direction:column;gap:5px;margin-top:12px}}button.topic-link{{border:0;text-align:left;background:#eeece7;color:var(--ink);padding:8px 10px;border-radius:5px;cursor:pointer}}button.topic-link:hover,button.topic-link.active{{background:#e4ded3;color:#6b4d12}}.empty{{color:var(--muted);padding:28px 5px;text-align:center;font-size:12px}}
.detail-head{{display:flex;justify-content:space-between;gap:15px;align-items:flex-start}}.detail h2{{font-size:20px}}.en{{color:var(--muted);font-size:11px}}.score{{font-size:24px;font-weight:700;color:var(--orange);white-space:nowrap}}.tag{{display:inline-block;border-radius:999px;background:#e9e5de;color:#665f56;padding:3px 8px;font-size:11px;margin:3px 4px 3px 0}}.tag.green{{background:#e2eee8;color:#356d58}}.tag.weak{{background:#f5e7cf;color:#9b641e}}
.detail-grid{{display:grid;grid-template-columns:1fr;gap:10px;margin-top:14px}}.field strong{{color:#6c5a38;font-size:11px;display:block}}.field ul{{margin:3px 0 0;padding-left:16px}}.field li{{margin:2px 0}}.summary{{background:#eeece7;border-left:2px solid var(--orange);padding:9px 11px;margin-top:12px;font-size:12px}}.evidence{{border-top:1px solid #dedad4;margin-top:15px;padding-top:11px}}.ev{{padding:8px 0;border-bottom:1px dashed #d5d0c8;font-size:12px}}.ev:last-child{{border:0}}.ev a{{color:#496577;font-weight:600;text-decoration:none}}.ev a:hover{{text-decoration:underline}}.zh{{color:#514c45;margin-top:2px}}.meta{{color:var(--muted);font-size:11px}}
@media(max-width:760px){{header{{height:50px;padding:0 14px}}main{{height:calc(100vh - 50px)}}.graph-shell{{inset:50px 0 0 0}}.side,.detail{{position:relative;top:auto;left:auto;right:auto;width:auto;bottom:auto;border:0}}.side{{display:none}}.detail{{position:fixed;z-index:8;left:12px;right:12px;top:58%;bottom:10px;border:1px solid #dedad4;box-shadow:0 8px 24px #493b2522}}.legend{{display:none}}.toolbar{{top:61px;left:12px;right:12px;transform:none}}input{{min-width:0;width:100%}}}}
</style></head><body>
<header><div><h1>Opportunity Radar<span style="color:#c8922a">.</span></h1></div><div style="display:flex;align-items:center;gap:18px"><span style="font:11px ui-monospace,monospace;color:#77736c">中文</span><span style="font:12px ui-monospace,monospace;color:#555">社区图谱</span><span style="font:12px ui-monospace,monospace;color:#555">分析说明</span><span class="brand">SUNCENTAUTO · Diesel Pickup</span></div></header>
<main><div class="toolbar"><select id="communityFilter"><option value="">全部社区</option>__COMMUNITY_OPTIONS__</select><input id="search" placeholder="搜索话题、痛点、车型或关键词…"><span class="hint">__COMMUNITY_COUNT__ 个社区 · __TOPIC_COUNT__ 个话题 · __FORMAL_COUNT__ 个正式话题</span></div>
<div class="legend"><span><i class="hollow"></i>社区（大小 = 关联话题数）</span><span><i class="solid"></i>话题（大小 = 热度）</span><span>点击社区查看其话题，点击话题查看分析</span></div>
<section class="graph-shell"><svg id="graph" viewBox="0 0 1200 650" role="img" aria-label="社区与话题关系图"></svg></section>
<section class="below"><aside class="side"><h2>当前社区</h2><p id="communityIntro">点击图中的空心社区节点。</p><div id="topicList" class="topic-list"></div></aside><article id="detail" class="detail"><div class="empty">点击一个实心话题节点，查看痛点、需求、方案不足、机会假设和 Reddit 证据。</div></article></section></main>
<script id="analysis-data" type="application/json">__PAYLOAD__</script>
<script>
const DATA=JSON.parse(document.querySelector('#analysis-data').textContent), TOPICS=(DATA.topics||[]).filter(Boolean), norm=(v)=>String(v??'').trim().replace(/^r\\//i,'').toLowerCase(), COMMUNITIES=[...new Set([...(DATA.communities||[]),...TOPICS.map(t=>t.community)].filter(Boolean).map(String))];
const svg=document.querySelector('#graph'), list=document.querySelector('#topicList'), detail=document.querySelector('#detail'), intro=document.querySelector('#communityIntro'), filter=document.querySelector('#communityFilter'), search=document.querySelector('#search');
const NS='http://www.w3.org/2000/svg'; let activeCommunity='', activeTopic='';
const esc=(v)=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
const arr=(v)=>Array.isArray(v)?v.filter(Boolean):[];
function node(tag,attrs={{}}){{const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));return n;}}
function topicMatches(t){{const q=search.value.trim().toLowerCase(),c=filter.value,hay=JSON.stringify(t).toLowerCase();return(!c||norm(t.community)===norm(c))&&(!q||hay.includes(q));}}
function field(label,values){{const vals=arr(values);return`<div class="field"><strong>${esc(label)}</strong><ul>${vals.length?vals.map(v=>`<li>${esc(v)}</li>`).join(''):'<li>未知</li>'}</ul></div>`;}}
function showCommunityListOnly(name){{const ts=TOPICS.filter(t=>norm(t.community)===norm(name)).sort((a,b)=>(Number(b.heat_score)||0)-(Number(a.heat_score)||0));intro.textContent=name+' · '+ts.length+' 个话题';list.innerHTML=ts.length?ts.map(t=>`<button class="topic-link ${String(t.topic_id)===String(activeTopic)?'active':''}" data-id="${esc(t.topic_id)}"><b>${esc(t.label_zh||t.label_en)}</b><span class="meta">　${esc(t.trend||'unknown')} · 热度 ${esc(t.heat_score||0)}</span></button>`).join(''):'<div class="meta">暂无话题</div>';list.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>showTopic(b.dataset.id)));}}
function layout(){{const width=1200,height=650,centers=COMMUNITIES.map((name,i)=>{{const cols=COMMUNITIES.length<=2?COMMUNITIES.length:2,rows=Math.ceil(COMMUNITIES.length/cols);return{{name,x:width*(i%cols+1)/(cols+1),y:height*(Math.floor(i/cols)+1)/(rows+1)}};}});const visible=TOPICS.filter(topicMatches);svg.innerHTML='';const edgeLayer=node('g'),nodeLayer=node('g');svg.append(edgeLayer,nodeLayer);const groups={{}};visible.forEach(t=>(groups[norm(t.community)]??=[]).push(t));centers.forEach(c=>{{const ts=groups[norm(c.name)]||[],cr=28+Math.min(32,ts.length*4),g=node('g',{{class:'community-node '+(norm(activeCommunity)===norm(c.name)?'active':'')}});g.append(node('circle',{{cx:c.x,cy:c.y,r:cr}}));const label=node('text',{{x:c.x,y:c.y+4,class:'node-label'}});label.textContent=c.name;g.append(label);const count=node('text',{{x:c.x,y:c.y+cr+17,class:'community-count'}});count.textContent=ts.length+' 个话题';g.append(count);g.addEventListener('click',()=>showCommunity(c.name));nodeLayer.append(g);ts.forEach((t,j)=>{{const angle=(Math.PI*2*j/Math.max(1,ts.length))-Math.PI/2,radius=Math.max(95,Math.min(190,105+ts.length*8)),x=c.x+Math.cos(angle)*radius,y=c.y+Math.sin(angle)*radius,r=10+Math.min(18,Math.sqrt(Number(t.heat_score)||0)*.9),line=node('line',{{x1:c.x,y1:c.y,x2:x,y2:y,class:'edge'}});edgeLayer.append(line);const tg=node('g',{{class:'topic-node '+(activeTopic===t.topic_id?'active':'')}});tg.append(node('circle',{{cx:x,cy:y,r,fill:t.status==='formal'?'#ef8b42':'#d9a04f'}}));const tl=node('text',{{x,y:y+r+15,class:'topic-label'}});tl.textContent=String(t.label_zh||t.label_en||'未命名').slice(0,18);tg.append(tl);tg.addEventListener('click',e=>{{e.stopPropagation();showTopic(t.topic_id);}});nodeLayer.append(tg);}});}});}}
function showCommunity(name){{activeCommunity=name;activeTopic='';filter.value=name;layout();showCommunityListOnly(name);detail.innerHTML='<div class="empty">已选中 '+esc(name)+'。点击实心话题节点或左侧话题查看分析。</div>';}}
function showTopic(id){{const t=TOPICS.find(x=>String(x.topic_id)===String(id));if(!t)return;activeTopic=id;activeCommunity=String(t.community);filter.value=activeCommunity;layout();showCommunityListOnly(activeCommunity);const ev=arr(t.evidence);detail.innerHTML=`<div class="detail-head"><div><span class="tag">${esc(t.community)}</span><h2>${esc(t.label_zh||'未命名话题')}</h2><div class="en">${esc(t.label_en||'')}</div></div><div class="score">${esc(t.heat_score||0)}<span class="meta"> /100</span></div></div><div><span class="tag green">趋势：${esc(t.trend||'unknown')}</span><span class="tag">帖子 ${esc(t.post_count||0)}</span><span class="tag">作者 ${esc(t.author_count||0)}</span><span class="tag">评论者 ${esc(t.commenter_count||0)}</span>${t.status!=='formal'?'<span class="tag weak">弱信号</span>':''}</div><div class="summary"><b>摘要：</b>${esc(t.summary||'未知')}</div><div class="detail-grid">${field('涉及车型/平台/场景',[...arr(t.vehicles),...arr(t.platforms),...arr(t.scenarios)])}${field('用户痛点',t.pains)}${field('用户需求',t.needs)}${field('当前方案',t.current_solutions)}${field('方案不足',t.gaps)}${field('机会假设',t.opportunity_hypotheses)}${field('验证问题',t.validation_questions)}</div><div class="evidence"><h3>帖子/评论证据（${ev.length}）</h3>${ev.length?ev.map(e=>`<div class="ev"><a href="${esc(e.url)}" target="_blank" rel="noreferrer">打开 Reddit 证据</a><span class="meta">　${esc(e.stance||'supporting')}</span><div>${esc(e.claim_en||'')}</div><div class="zh">中文：${esc(e.claim_zh||'')}</div></div>`).join(''):'<div class="meta">暂无可回溯证据</div>'}</div>`;}}
filter.addEventListener('change',()=>{{activeCommunity=filter.value;activeTopic='';layout();if(filter.value)showCommunityListOnly(filter.value);else{{intro.textContent='点击图中的空心社区节点。';list.innerHTML='';detail.innerHTML='<div class="empty">点击一个实心话题节点，查看详细分析。</div>';}}}});search.addEventListener('input',layout);layout();
</script></body></html>'''
    html = html.replace("{{", "{").replace("}}", "}").replace("__COMMUNITY_OPTIONS__", "".join(
        f'<option value="{escape(name, quote=True)}">{escape(name)}</option>' for name in communities
    )).replace("__COMMUNITY_COUNT__", str(len(communities))).replace("__TOPIC_COUNT__", str(len(topics))).replace(
        "__FORMAL_COUNT__", str(formal)
    ).replace("__PAYLOAD__", payload)
    output.write_text(html, encoding="utf-8")
    (output.parent / "community_topic_map.json").write_text(json.dumps(build_topic_map(analysis), ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def build_topic_map(analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Return graph-ready community/topic nodes and edges."""
    topics = [item for item in analysis.get("topics", []) if isinstance(item, Mapping)]
    communities = [str(item) for item in analysis.get("communities", []) if item]
    return {
        "nodes": ([{"id": f"community:{name}", "type": "community", "label": name} for name in communities]
                  + [{"id": str(item.get("topic_id", "")), "type": "topic", "label": item.get("label_zh", item.get("label_en", "")), "community": item.get("community")} for item in topics]),
        "edges": [{"source": f"community:{item.get('community')}", "target": item.get("topic_id")} for item in topics if item.get("topic_id")],
    }
