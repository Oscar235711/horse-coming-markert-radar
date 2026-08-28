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
:root{{--bg:#f7f8fc;--ink:#172033;--muted:#748096;--line:#e1e6ef;--blue:#376cf0;--orange:#ef8b42;--green:#39a37c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
header{{padding:22px max(20px,calc((100% - 1280px)/2));background:#fff;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;align-items:flex-start}}
h1{{font-size:23px;margin:0;letter-spacing:.2px}}header p{{margin:4px 0 0;color:var(--muted)}}.brand{{font-weight:700;color:var(--blue);white-space:nowrap}}
main{{max-width:1280px;margin:0 auto;padding:16px 20px 40px}}.toolbar{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}}
select,input{{border:1px solid var(--line);background:#fff;border-radius:8px;padding:9px 11px;color:var(--ink)}}input{{min-width:290px}}.hint{{color:var(--muted);font-size:12px}}
.legend{{display:flex;gap:18px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:12px;margin:4px 0 10px}}.legend i{{display:inline-block;width:13px;height:13px;border-radius:50%;vertical-align:-2px;margin-right:5px}}.hollow{{border:2px solid var(--blue);background:#fff}}.solid{{background:var(--orange)}}
.graph-shell{{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:0 6px 20px #253b690b;overflow:hidden}}svg{{display:block;width:100%;height:min(66vh,650px);min-height:440px;background:radial-gradient(circle at 50% 48%,#fbfcff 0,#f5f7fc 70%,#f0f3f9 100%)}}
.edge{{stroke:#cfd8e9;stroke-width:1.4;opacity:.75}}.community-node,.topic-node{{cursor:pointer}}.community-node circle{{fill:#fff;stroke:var(--blue);stroke-width:2.5}}.community-node:hover circle,.community-node.active circle{{stroke:#111f40;stroke-width:4}}.topic-node circle{{stroke:#fff;stroke-width:2}}.topic-node:hover circle,.topic-node.active circle{{stroke:#172033;stroke-width:3}}.node-label{{font-size:12px;fill:#27344d;pointer-events:none;text-anchor:middle;font-weight:600}}.topic-label{{font-size:11px;fill:#51617b;pointer-events:none;text-anchor:middle}}.community-count{{font-size:11px;fill:var(--blue);pointer-events:none;text-anchor:middle}}
.below{{display:grid;grid-template-columns:260px 1fr;gap:14px;margin-top:14px}}.side,.detail{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}}.side h2,.detail h2{{font-size:17px;margin:0 0 5px}}.side p{{color:var(--muted);font-size:12px}}.topic-list{{display:flex;flex-direction:column;gap:5px;margin-top:12px}}button.topic-link{{border:0;text-align:left;background:#f5f7fb;color:var(--ink);padding:8px 10px;border-radius:7px;cursor:pointer}}button.topic-link:hover,button.topic-link.active{{background:#eaf0ff;color:#2457c8}}.empty{{color:var(--muted);padding:30px;text-align:center}}
.detail-head{{display:flex;justify-content:space-between;gap:15px;align-items:flex-start}}.detail h2{{font-size:21px}}.en{{color:var(--muted);font-size:12px}}.score{{font-size:25px;font-weight:700;color:var(--orange);white-space:nowrap}}.tag{{display:inline-block;border-radius:999px;background:#edf2ff;color:#2858bd;padding:3px 8px;font-size:12px;margin:3px 4px 3px 0}}.tag.green{{background:#e9f8f1;color:#237c59}}.tag.weak{{background:#fff1de;color:#9b641e}}
.detail-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px 22px;margin-top:14px}}.field strong{{color:#34547d;font-size:12px;display:block}}.field ul{{margin:3px 0 0;padding-left:18px}}.field li{{margin:2px 0}}.summary{{background:#f7f9fd;border-left:3px solid var(--blue);padding:9px 11px;margin-top:12px}}.evidence{{border-top:1px solid var(--line);margin-top:15px;padding-top:11px}}.ev{{padding:8px 0;border-bottom:1px dashed var(--line)}}.ev:last-child{{border:0}}.ev a{{color:var(--blue);font-weight:600;text-decoration:none}}.ev a:hover{{text-decoration:underline}}.zh{{color:#394b63;margin-top:2px}}.meta{{color:var(--muted);font-size:12px}}
@media(max-width:760px){{header{{display:block}}.brand{{display:block;margin-top:8px}}.below{{grid-template-columns:1fr}}.detail-grid{{grid-template-columns:1fr}}svg{{min-height:410px}}input{{min-width:0;width:100%}}}}
</style></head><body>
<header><div><h1>Opportunity Radar｜社区话题图谱</h1><p>空心圆 = Reddit 社区　·　实心圆 = 热门话题/机会假设　·　点击节点下钻到证据</p></div><div class="brand">SUNCENTAUTO · Diesel Pickup</div></header>
<main><div class="toolbar"><select id="communityFilter"><option value="">全部社区</option>__COMMUNITY_OPTIONS__</select><input id="search" placeholder="搜索话题、痛点、车型或关键词…"><span class="hint">__COMMUNITY_COUNT__ 个社区 · __TOPIC_COUNT__ 个话题 · __FORMAL_COUNT__ 个正式话题</span></div>
<div class="legend"><span><i class="hollow"></i>社区（大小 = 关联话题数）</span><span><i class="solid"></i>话题（大小 = 热度）</span><span>点击社区查看其话题，点击话题查看分析</span></div>
<section class="graph-shell"><svg id="graph" viewBox="0 0 1200 650" role="img" aria-label="社区与话题关系图"></svg></section>
<section class="below"><aside class="side"><h2>当前社区</h2><p id="communityIntro">点击图中的空心社区节点。</p><div id="topicList" class="topic-list"></div></aside><article id="detail" class="detail"><div class="empty">点击一个实心话题节点，查看痛点、需求、方案不足、机会假设和 Reddit 证据。</div></article></section></main>
<script id="analysis-data" type="application/json">__PAYLOAD__</script>
<script>
const DATA=JSON.parse(document.querySelector('#analysis-data').textContent), TOPICS=(DATA.topics||[]).filter(Boolean), COMMUNITIES=[...new Set((DATA.communities||[]).map(String))];
const svg=document.querySelector('#graph'), list=document.querySelector('#topicList'), detail=document.querySelector('#detail'), intro=document.querySelector('#communityIntro'), filter=document.querySelector('#communityFilter'), search=document.querySelector('#search');
const NS='http://www.w3.org/2000/svg'; let activeCommunity='', activeTopic='';
const esc=(v)=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
const arr=(v)=>Array.isArray(v)?v.filter(Boolean):[];
function node(tag,attrs={{}}){{const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));return n;}}
function topicMatches(t){{const q=search.value.trim().toLowerCase(),c=filter.value,hay=JSON.stringify(t).toLowerCase();return(!c||String(t.community)===c)&&(!q||hay.includes(q));}}
function field(label,values){{const vals=arr(values);return`<div class="field"><strong>${esc(label)}</strong><ul>${vals.length?vals.map(v=>`<li>${esc(v)}</li>`).join(''):'<li>未知</li>'}</ul></div>`;}}
function showCommunityListOnly(name){{const ts=TOPICS.filter(t=>String(t.community)===name).sort((a,b)=>(Number(b.heat_score)||0)-(Number(a.heat_score)||0));intro.textContent=name+' · '+ts.length+' 个话题';list.innerHTML=ts.length?ts.map(t=>`<button class="topic-link ${String(t.topic_id)===String(activeTopic)?'active':''}" data-id="${esc(t.topic_id)}"><b>${esc(t.label_zh||t.label_en)}</b><span class="meta">　${esc(t.trend||'unknown')} · 热度 ${esc(t.heat_score||0)}</span></button>`).join(''):'<div class="meta">暂无话题</div>';list.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>showTopic(b.dataset.id)));}}
function layout(){{const width=1200,height=650,centers=COMMUNITIES.map((name,i)=>{{const cols=COMMUNITIES.length<=2?COMMUNITIES.length:2,rows=Math.ceil(COMMUNITIES.length/cols);return{{name,x:width*(i%cols+1)/(cols+1),y:height*(Math.floor(i/cols)+1)/(rows+1)}};}});const visible=TOPICS.filter(topicMatches);svg.innerHTML='';const edgeLayer=node('g'),nodeLayer=node('g');svg.append(edgeLayer,nodeLayer);const groups={{}};visible.forEach(t=>(groups[t.community]??=[]).push(t));centers.forEach(c=>{{const ts=groups[c.name]||[],cr=28+Math.min(32,ts.length*4),g=node('g',{{class:'community-node '+(activeCommunity===c.name?'active':'')}});g.append(node('circle',{{cx:c.x,cy:c.y,r:cr}}));const label=node('text',{{x:c.x,y:c.y+4,class:'node-label'}});label.textContent=c.name;g.append(label);const count=node('text',{{x:c.x,y:c.y+cr+17,class:'community-count'}});count.textContent=ts.length+' 个话题';g.append(count);g.addEventListener('click',()=>showCommunity(c.name));nodeLayer.append(g);ts.forEach((t,j)=>{{const angle=(Math.PI*2*j/Math.max(1,ts.length))-Math.PI/2,radius=Math.max(95,Math.min(190,105+ts.length*8)),x=c.x+Math.cos(angle)*radius,y=c.y+Math.sin(angle)*radius,r=10+Math.min(18,Math.sqrt(Number(t.heat_score)||0)*.9),line=node('line',{{x1:c.x,y1:c.y,x2:x,y2:y,class:'edge'}});edgeLayer.append(line);const tg=node('g',{{class:'topic-node '+(activeTopic===t.topic_id?'active':'')}});tg.append(node('circle',{{cx:x,cy:y,r,fill:t.status==='formal'?'#ef8b42':'#d9a04f'}}));const tl=node('text',{{x,y:y+r+15,class:'topic-label'}});tl.textContent=String(t.label_zh||t.label_en||'未命名').slice(0,18);tg.append(tl);tg.addEventListener('click',e=>{{e.stopPropagation();showTopic(t.topic_id);}});nodeLayer.append(tg);}});}});}}
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
