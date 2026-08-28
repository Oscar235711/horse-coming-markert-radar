"""Offline WhatToSell-style community → topic → evidence report."""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any, Mapping


def render_html(analysis: Mapping[str, Any], output_path: str | Path) -> Path:
    """Render a deterministic, click-to-expand graph from one canonical JSON.

    The global view intentionally contains communities only. Selecting a
    community replaces the graph with that community and its topics; selecting
    a topic opens its analysis card. This mirrors WhatToSell's interaction
    model and prevents unselected communities/topics from appearing active.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    topics = [item for item in analysis.get("topics", []) if isinstance(item, Mapping)]
    communities = list(dict.fromkeys(str(item) for item in analysis.get("communities", []) if item))
    if not communities:
        communities = list(dict.fromkeys(str(item.get("community", "未知")) for item in topics if item.get("community")))

    # Recompute display metrics from the same topic/evidence arrays that the
    # browser consumes. Saved collection counts never override graph counts.
    community_count = len(communities)
    topic_count = len(topics)
    formal_count = sum(1 for item in topics if str(item.get("status", "")) == "formal")
    keyword_library = analysis.get("keyword_library", {})
    keyword_count = len(keyword_library.get("candidates", [])) if isinstance(keyword_library, Mapping) else 0
    evidence_count = sum(len(item.get("evidence", [])) for item in topics if isinstance(item.get("evidence", []), list))
    crawl_counts = analysis.get("crawl_counts", {}) if isinstance(analysis.get("crawl_counts", {}), Mapping) else {}
    collection_note = (
        f"{int(crawl_counts.get('normalized_posts', 0) or 0)} 条去重帖 · "
        f"{int(crawl_counts.get('saved_threads', 0) or 0)} 篇深读 · "
        f"{int(crawl_counts.get('saved_comments', 0) or 0)} 条评论"
    )
    mode_note = "本地规则/VOC分析 · 未调用DeepSeek" if str(analysis.get("model_mode", "")).casefold() in {"rule_based", "rule_fallback"} else "模型辅助分析"
    payload = json.dumps(dict(analysis), ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")

    html = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Opportunity Radar｜社区话题图谱</title>
<style>
:root{--bg:#f4f2ee;--paper:#faf9f6;--ink:#24211e;--muted:#817b72;--line:#dedad4;--orange:#e89545;--orange-dark:#a85f25;--blue:#597080;--green:#4e806d}
*{box-sizing:border-box}html,body{height:100%;margin:0}body{background:var(--bg);color:var(--ink);font:14px/1.55 Inter,"IBM Plex Sans","Microsoft YaHei",system-ui,sans-serif;overflow:hidden}
header{height:57px;padding:0 25px;border-bottom:1px solid #e7e3dd;display:flex;align-items:center;justify-content:space-between;background:var(--bg);position:relative;z-index:10}
.logo{font:700 18px/1 "IBM Plex Mono",ui-monospace,monospace;letter-spacing:-.03em}.logo b{color:var(--orange)}.brand{font:11px ui-monospace,monospace;color:#77736c;letter-spacing:.06em}
.page{height:calc(100vh - 57px);display:grid;grid-template-columns:282px minmax(0,1fr);position:relative}.page.detail-open{grid-template-columns:282px minmax(0,1fr) 410px}
.left{border-right:1px solid var(--line);padding:20px 17px;overflow:auto;background:rgba(244,242,238,.92);z-index:3}.left-kicker{font:10px ui-monospace,monospace;letter-spacing:.14em;color:var(--muted);text-transform:uppercase;margin-bottom:8px}.left h2{font-size:17px;line-height:1.25;margin:0 0 7px}.intro{font-size:12px;line-height:1.7;color:#5e5952;margin:0 0 15px}
.search{width:100%;border:1px solid #d5d0c8;border-radius:7px;background:#fff;padding:9px 11px;color:var(--ink);outline:none}.search:focus{border-color:#a99c8b;box-shadow:0 0 0 3px #e8954520}.reset{width:100%;border:0;background:#e9e4dc;border-radius:6px;padding:8px 10px;text-align:left;color:#635c53;cursor:pointer;margin-top:8px}.reset:hover{background:#ded7cc}
.left-section{border-top:1px solid var(--line);margin-top:18px;padding-top:14px}.section-title{font-size:10px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;margin-bottom:8px}.community-row,.topic-row{display:flex;align-items:center;gap:9px;width:100%;border:0;background:transparent;text-align:left;color:var(--ink);padding:8px 7px;border-radius:6px;cursor:pointer}.community-row:hover,.topic-row:hover,.topic-row.active{background:#e9e4dc}.dot{width:12px;height:12px;border:1.5px solid #8a8378;border-radius:50%;flex:none}.topic-dot{width:10px;height:10px;border-radius:50%;background:var(--orange);flex:none}.row-body{min-width:0;flex:1}.row-name{display:block;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row-meta{display:block;font-size:10px;color:var(--muted);white-space:nowrap}.empty{color:var(--muted);font-size:12px;padding:13px 4px;line-height:1.7}
.legend{border-top:1px solid var(--line);margin-top:20px;padding-top:14px;color:var(--muted);font-size:11px}.legend-line{display:flex;gap:7px;align-items:center;margin:6px 0}.legend .dot{width:11px;height:11px}.legend .topic-dot{width:11px;height:11px}
.center{position:relative;min-width:0;background:var(--bg);overflow:hidden}.toolbar{height:52px;position:absolute;left:18px;right:18px;top:13px;display:flex;align-items:center;gap:8px;z-index:4;pointer-events:none}.metric{font:10px ui-monospace,monospace;color:#77736c;background:#f4f2eed9;border-radius:999px;padding:5px 9px;white-space:nowrap;margin-left:auto}.graph{position:absolute;inset:0;width:100%;height:100%}.edge{stroke:#cbc4b9;stroke-width:1.15;opacity:.75}.community-node,.topic-node{cursor:pointer}.community-node circle{fill:var(--bg);stroke:#8b8479;stroke-width:1.6}.community-node:hover circle,.community-node.active circle{stroke:#28241f;stroke-width:2.8}.topic-node circle{stroke:var(--bg);stroke-width:2}.topic-node:hover circle,.topic-node.active circle{stroke:#28241f;stroke-width:3}.node-label{font-size:12px;text-anchor:middle;fill:#2c2823;font-weight:600;pointer-events:none}.topic-label{font-size:11px;text-anchor:middle;fill:#5d574f;pointer-events:none}.node-count{font-size:10px;text-anchor:middle;fill:#8a8378;pointer-events:none}.graph-help{position:absolute;left:50%;bottom:20px;transform:translateX(-50%);font-size:11px;color:#948d84;background:#f4f2eedc;padding:5px 11px;border-radius:99px;white-space:nowrap;pointer-events:none}
.right{border-left:1px solid var(--line);background:rgba(250,249,246,.96);position:relative;z-index:5;overflow:hidden}.right.closed{display:none}.detail{height:100%;overflow:auto;padding:23px 21px 30px}.close{position:absolute;right:16px;top:12px;width:30px;height:30px;border:0;border-radius:50%;background:#ece8e2;color:#625c53;font-size:22px;line-height:1;cursor:pointer;z-index:2}.close:hover{background:#dfd9d0;color:#25211d}.detail-placeholder{height:100%;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);font-size:13px}.detail-placeholder span{display:block;font-size:11px;margin-top:6px}.eyebrow{font:10px ui-monospace,monospace;color:var(--muted);letter-spacing:.12em;text-transform:uppercase}.detail h2{font-size:20px;line-height:1.3;margin:6px 38px 3px 0}.en{font-size:11px;color:var(--muted);margin-bottom:13px}.score{font:700 28px ui-monospace,monospace;color:var(--orange-dark);float:right;margin-top:-45px}.score small{font-size:11px;color:var(--muted);font-weight:400}.tags{display:flex;flex-wrap:wrap;gap:5px;margin:10px 0 15px}.tag{font-size:10px;color:#655e55;background:#ece8e2;padding:4px 8px;border-radius:99px}.tag.formal{background:#e6eee9;color:#3f6d5b}.tag.weak{background:#f7ead9;color:#986023}.summary{background:#f1eee9;border-left:3px solid var(--orange);padding:11px 12px;font-size:12px;line-height:1.7;margin-bottom:16px}.field{border-top:1px solid var(--line);padding:11px 0 8px}.field h3{font-size:11px;color:#75613e;margin:0 0 5px}.field ul{padding-left:17px;margin:0}.field li{font-size:12px;line-height:1.65;margin:2px 0}.rich-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:10px 0 14px}..rich-card{background:#f1eee9;border:1px solid #e3ded6;border-radius:8px;padding:10px}.rich-card .k{font-size:10px;color:var(--muted);margin-bottom:3px}.rich-card .v{font-size:13px;line-height:1.5}..rich-section{border-top:1px solid var(--line);padding:14px 0 5px}.rich-section h3{font-size:12px;margin:0 0 7px;color:#75613e}.rich-section h3 small{font-size:10px;color:var(--muted);font-weight:400;margin-left:4px}.rich-section ul{padding-left:17px;margin:0}.rich-section li{font-size:12px;line-height:1.6;margin:2px 0}.inference{font-size:10px;color:#8c6a3e;background:#fbf4e7;border-radius:5px;padding:5px 7px;margin-top:7px}.evidence{border-top:1px solid var(--line);margin-top:12px;padding-top:13px}.evidence h3{font-size:12px;margin:0 0 8px}.ev{border-bottom:1px dashed #d8d1c8;padding:9px 0;font-size:11px;line-height:1.55}.ev:last-child{border-bottom:0}.ev a{color:var(--blue);font-weight:600;text-decoration:none}.ev a:hover{text-decoration:underline}.ev .claim{margin-top:4px;color:#3f3a34}.ev .zh{margin-top:3px;color:#736a60}.community-detail .topic-mini{display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--line);padding:9px 0;cursor:pointer}.community-detail .topic-mini:hover{color:var(--orange-dark)}
@media(max-width:1000px){.page{grid-template-columns:235px minmax(0,1fr)}.right{position:absolute;right:0;top:0;bottom:0;width:min(410px,92vw);box-shadow:-10px 0 24px #40372218}.right.closed{display:none}.toolbar{left:12px}.metric{font-size:9px}.left{padding:17px 12px}}
@media(max-width:650px){body{overflow:auto}.page{height:auto;min-height:calc(100vh - 57px);display:block}.left{border:0}.center{height:520px}.right{position:fixed;top:57px;right:0;bottom:0;width:94vw}.toolbar{position:relative;top:auto;left:auto;right:auto;height:auto;padding:10px 12px}.metric{margin-left:0;white-space:normal}.graph-help{bottom:10px;font-size:10px}.brand{display:none}}
</style><style>.rich-card{background:#f1eee9;border:1px solid #e3ded6;border-radius:8px;padding:10px}.rich-section{border-top:1px solid var(--line);padding:14px 0 5px}.rich-section h3{font-size:12px;margin:0 0 7px;color:#75613e}.rich-section h3 small{font-size:10px;color:var(--muted);font-weight:400;margin-left:4px}.rich-section ul{padding-left:17px;margin:0}.rich-section li{font-size:12px;line-height:1.6;margin:2px 0}</style></head><body>
<header><div class="logo">Opportunity Radar<b>.</b></div><div class="brand">SUNCENTAUTO · DIESEL PICKUP MARKET</div></header>
<div class="page">
<aside class="left">
  <div class="left-kicker">Community radar · 90 days</div>
  <h2>社区—话题图谱</h2>
  <p class="intro">空心圈是 Reddit 社区。先选一个社区，再查看这个社区里被反复讨论的话题；点话题可下钻到痛点、方案缺口和原帖证据。</p>
  <input id="search" class="search" placeholder="搜社区、话题、车型或关键词…" autocomplete="off">
  <button id="reset" class="reset" type="button">← 回到全局社区图</button>
  <div class="left-section"><div class="section-title">已批准社区</div><div id="communityList"></div></div>
  <div class="left-section"><div class="section-title" id="topicTitle">选择社区后显示话题</div><div id="topicList"><div class="empty">当前未选择社区</div></div></div>
  <div class="legend"><div class="legend-line"><i class="dot"></i><span>社区（大小 = 关联话题数）</span></div><div class="legend-line"><i class="topic-dot"></i><span>话题（大小 = 社区样本热度）</span></div><div class="legend-line">点击空白或“关闭”可收起详情</div></div>
</aside>
<section class="center"><div class="toolbar"><span class="metric" id="metrics"></span></div><svg id="graph" class="graph" viewBox="0 0 1000 720" role="img" aria-label="社区与话题关系图"></svg><div class="graph-help" id="graphHelp">点击一个社区，展开它的热门话题</div></section>
<aside id="right" class="right closed"><button class="close" id="close" type="button" aria-label="关闭详情">×</button><div id="detail" class="detail"></div></aside>
</div>
<script id="analysis-data" type="application/json">__PAYLOAD__</script>
<script>
const DATA=JSON.parse(document.getElementById('analysis-data').textContent||'{}');
const TOPICS=Array.isArray(DATA.topics)?DATA.topics.filter(Boolean):[];
const norm=v=>{const s=String(v??'').trim().toLowerCase();return s.startsWith('r/')?s.slice(2):s};
const communityNames=new Map();
for(const raw of (Array.isArray(DATA.communities)?DATA.communities:[]).concat(TOPICS.map(t=>t.community||'')).filter(Boolean).map(String)){const key=norm(raw);if(!communityNames.has(key))communityNames.set(key,raw)}
const COMMUNITIES=Array.from(communityNames.values());
const byCommunity=new Map(COMMUNITIES.map(c=>[norm(c),TOPICS.filter(t=>norm(t.community)===norm(c))]));
const page=document.querySelector('.page'), svg=document.getElementById('graph'), search=document.getElementById('search'), reset=document.getElementById('reset'), closeBtn=document.getElementById('close'), right=document.getElementById('right'), detail=document.getElementById('detail'), communityList=document.getElementById('communityList'), topicList=document.getElementById('topicList'), topicTitle=document.getElementById('topicTitle'), metrics=document.getElementById('metrics'), graphHelp=document.getElementById('graphHelp');
const NS='http://www.w3.org/2000/svg'; let selectedCommunity=''; let selectedTopic='';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const arr=v=>Array.isArray(v)?v.filter(Boolean):[];
const communityTopics=c=>byCommunity.get(norm(c))||[];
const topicMatches=(t,q)=>JSON.stringify(t).toLowerCase().includes(q);
function node(tag,attrs={}){const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));return n;}
function openPanel(){right.classList.remove('closed');page.classList.add('detail-open');}
function closePanel(){selectedCommunity='';selectedTopic='';right.classList.add('closed');page.classList.remove('detail-open');renderSide();renderGraph();}
function selectCommunity(name){selectedCommunity=String(name);selectedTopic='';openPanel();renderSide();renderGraph();showCommunityDetail(selectedCommunity);}
function selectTopic(id){const t=TOPICS.find(x=>String(x.topic_id)===String(id));if(!t)return;selectedCommunity=String(t.community);selectedTopic=String(t.topic_id);openPanel();renderSide();renderGraph();showTopicDetail(t);}
function renderSide(){
  const q=search.value.trim().toLowerCase();
  communityList.innerHTML=COMMUNITIES.filter(c=>!q||norm(c).includes(q)||communityTopics(c).some(t=>topicMatches(t,q))).map(c=>`<button class="community-row" data-community="${esc(c)}"><i class="dot"></i><span class="row-body"><span class="row-name">${esc(c)}</span><span class="row-meta">${communityTopics(c).length} 个话题</span></span></button>`).join('')||'<div class="empty">没有匹配社区</div>';
  communityList.querySelectorAll('[data-community]').forEach(b=>b.addEventListener('click',()=>selectCommunity(b.dataset.community)));
  if(!selectedCommunity){topicTitle.textContent='选择社区后显示话题';topicList.innerHTML='<div class="empty">当前未选择社区</div>';return;}
  const ts=communityTopics(selectedCommunity).filter(t=>!q||topicMatches(t,q));topicTitle.textContent=`${selectedCommunity} · ${communityTopics(selectedCommunity).length} 个话题`;
  topicList.innerHTML=ts.length?ts.slice().sort((a,b)=>(Number(b.heat_score)||0)-(Number(a.heat_score)||0)).map(t=>`<button class="topic-row ${String(t.topic_id)===selectedTopic?'active':''}" data-topic="${esc(t.topic_id)}"><i class="topic-dot"></i><span class="row-body"><span class="row-name">${esc(t.label_zh||t.label_en||'未命名话题')}</span><span class="row-meta">${esc(t.trend||'unknown')} · 热度 ${esc(t.heat_score||0)} · ${esc(t.post_count||0)} 帖</span></span></button>`).join(''):'<div class="empty">该社区没有匹配话题</div>';
  topicList.querySelectorAll('[data-topic]').forEach(b=>b.addEventListener('click',()=>selectTopic(b.dataset.topic)));
}
function communityPositions(){const n=COMMUNITIES.length||1;const out=[];for(let i=0;i<n;i++){const angle=-Math.PI/2+(Math.PI*2*i/n);const radius=n<=2?170:240;out.push({x:500+Math.cos(angle)*radius,y:355+Math.sin(angle)*radius});}return out;}
function topicPositions(ts){const out=[];const rings=Math.ceil(ts.length/6);let index=0;for(let ring=0;ring<rings;ring++){const count=Math.min(6,ts.length-index),radius=150+ring*92;for(let j=0;j<count;j++){const angle=-Math.PI/2+(Math.PI*2*j/count)+(ring%2?Math.PI/6:0);out.push({x:500+Math.cos(angle)*radius,y:360+Math.sin(angle)*radius});index++;}}return out;}
function renderGraph(){
  svg.innerHTML='';const edgeLayer=node('g'),layer=node('g');svg.append(edgeLayer,layer);
  if(!selectedCommunity){
    graphHelp.textContent='点击一个社区，展开它的热门话题';
    const positions=communityPositions();COMMUNITIES.forEach((c,i)=>{const ts=communityTopics(c),p=positions[i],r=35+Math.min(35,ts.length*4),g=node('g',{class:'community-node'});g.append(node('circle',{cx:p.x,cy:p.y,r}));const l=node('text',{x:p.x,y:p.y+4,class:'node-label'});l.textContent=c;g.append(l);const count=node('text',{x:p.x,y:p.y+r+18,class:'node-count'});count.textContent=ts.length+' 个话题';g.append(count);g.addEventListener('click',()=>selectCommunity(c));layer.append(g);});return;
  }
  graphHelp.textContent='点击话题查看分析；点击空白或右上角 × 返回全局';
  const ts=communityTopics(selectedCommunity);const cp={x:500,y:360},cr=38+Math.min(35,ts.length*4),cg=node('g',{class:'community-node active'});cg.append(node('circle',{cx:cp.x,cy:cp.y,r:cr}));const cl=node('text',{x:cp.x,y:cp.y+4,class:'node-label'});cl.textContent=selectedCommunity;cg.append(cl);const cc=node('text',{x:cp.x,y:cp.y+cr+18,class:'node-count'});cc.textContent=ts.length+' 个话题';cg.append(cc);cg.addEventListener('click',()=>showCommunityDetail(selectedCommunity));layer.append(cg);
  topicPositions(ts).forEach((p,i)=>{const t=ts[i],r=11+Math.min(18,Math.sqrt(Number(t.heat_score)||0)*1.15),line=node('line',{x1:cp.x,y1:cp.y,x2:p.x,y2:p.y,class:'edge'});edgeLayer.append(line);const tg=node('g',{class:'topic-node '+(String(t.topic_id)===selectedTopic?'active':'')});tg.append(node('circle',{cx:p.x,cy:p.y,r,fill:t.status==='formal'?'#e89545':'#d1a15d'}));const label=node('text',{x:p.x,y:p.y+r+16,class:'topic-label'});const raw=String(t.label_zh||t.label_en||'未命名话题');label.textContent=raw.length>16?raw.slice(0,15)+'…':raw;tg.append(label);tg.addEventListener('click',e=>{e.stopPropagation();selectTopic(t.topic_id)});layer.append(tg);});
}
function field(label,values){const vals=arr(values);return `<section class="field"><h3>${esc(label)}</h3><ul>${vals.length?vals.map(v=>`<li>${esc(v)}</li>`).join(''):'<li>未知</li>'}</ul></section>`;}
function obj(value){return value&&typeof value==='object'&&!Array.isArray(value)?value:{};}
function richList(values){const vals=arr(values);return `<ul>${vals.length?vals.map(v=>`<li>${esc(v)}</li>`).join(''):'<li>未知</li>'}</ul>`;}
function richSection(title,values,note=''){return `<section class="rich-section"><h3>${esc(title)}</h3>${richList(values)}${note?`<div class="inference">${esc(note)}</div>`:''}</section>`;}
function richGrid(items){return `<div class="rich-grid">${items.map(item=>`<div class="rich-card"><div class="k">${esc(item[0])}</div><div class="v">${esc(item[1]||'未知')}</div></div>`).join('')}</div>`;}
function showCommunityDetail(name){const ts=communityTopics(name).slice().sort((a,b)=>(Number(b.heat_score)||0)-(Number(a.heat_score)||0));detail.innerHTML=`<div class="community-detail"><div class="eyebrow">Reddit社区 · 人群入口</div><h2>${esc(name)}</h2><div class="en">该社区当前关联 ${ts.length} 个话题</div><div class="summary">先从社区层面观察讨论结构，再点进具体话题查看痛点、方案缺口和原帖/评论证据。未选中的社区与话题不会在图中展开。</div><div class="field"><h3>热门话题</h3>${ts.length?ts.map(t=>`<div class="topic-mini" data-topic="${esc(t.topic_id)}"><i class="topic-dot"></i><span>${esc(t.label_zh||t.label_en||'未命名话题')}</span><span class="row-meta">${esc(t.heat_score||0)}</span></div>`).join(''):'<div class="empty">暂无话题</div>'}</div></div>`;detail.querySelectorAll('[data-topic]').forEach(b=>b.addEventListener('click',()=>selectTopic(b.dataset.topic)));}
function showTopicDetail(t){
  const ev=arr(t.evidence), validation=obj(t.demand_validation), insight=obj(t.seller_insight), business=obj(t.business_profile), why=obj(t.why_not_done), manufacturing=obj(t.manufacturing_profile), decision=obj(t.decision), coverage=obj(t.coverage);
  const evidenceHtml=ev.length?ev.map(e=>`<div class="ev"><a href="${esc(e.url||'#')}" target="_blank" rel="noreferrer">打开 Reddit 原文 ↗</a><div class="claim">${esc(e.claim_en||'')}</div><div class="zh">${esc(e.claim_zh||'')}</div></div>`).join(''):'<div class="empty">暂无可回溯证据</div>';
  detail.innerHTML=`<div class="eyebrow">${esc(t.community)} · 话题分析</div><h2>${esc(t.label_zh||'未命名话题')}</h2><div class="en">${esc(t.label_en||'')}</div><div class="score">${esc(t.heat_score||0)}<small>/100</small></div><div class="tags"><span class="tag ${t.status==='formal'?'formal':'weak'}">${t.status==='formal'?'正式话题':'弱信号'}</span><span class="tag">建议：${esc(decision.label||'继续观察')}</span><span class="tag">趋势：${esc(t.trend||'unknown')}</span><span class="tag">${esc(t.post_count||0)} 帖 · ${esc(t.author_count||0)} 作者 · ${esc(t.commenter_count||0)} 评论者</span></div><div class="summary">${esc(t.summary||'未知')}<div class="inference">机会分 ${esc(t.opportunity_score??'未知')}/10 · ${esc(decision.reason||'样本分析结果')} · 所有产品方向均为机会假设。</div></div><div class="rich-section"><h3>Demand Validation <small>需求验证</small></h3>${richGrid([['帖子数',validation.posts??t.post_count],['独立作者',validation.authors??t.author_count],['评论者',validation.commenters??t.commenter_count],['当前/基线',`${validation.current_posts??0} / ${validation.baseline_posts??0}`]])}<div class="inference">${esc(validation.note||'社区样本信号，不代表全量市场。')}</div></div><div class="rich-section"><h3>At a Glance <small>快速判断</small></h3>${richGrid([['Top buyer complaint',t.top_buyer_complaint],['Best opening angle',t.best_opening_angle],['涉及平台',arr(t.platforms).join('、')||'未知'],['使用场景',arr(t.scenarios).join('、')||'未知']])}</div><div class="rich-section"><h3>Seller Insight <small>卖家视角</small></h3>${richList([`适合：${insight.who_should_sell||'未知'}`,`不适合：${insight.who_should_avoid||'未知'}`,`定位角度：${insight.positioning_angle||'待验证'}`,`竞品观察：${insight.competition_note||'未知'}`])}<div class="inference">${esc(insight.basis||'推断项，需业务复核。')}</div></div>${richSection('Pain Points · 用户痛点',t.pains)}${richSection('Needs & Current Solutions · 需求与现有方案',[...arr(t.needs),...arr(t.current_solutions)])}${richSection('Seller Opportunities · 产品机会假设',t.opportunity_hypotheses,'机会假设，不是开品结论。')}${richSection('方案不足 / Gaps',t.gaps)}<div class="rich-section"><h3>Why hasn’t this been done? <small>为什么还没有被解决</small></h3>${richList(why.reasons)}<div class="inference">供应链/成本影响：${esc(why.cost_supply_chain_impact||'待验证')}<br>商业模式冲突：${esc(why.business_model_conflict||'未知')}</div></div><div class="rich-section"><h3>Manufacturing Profile <small>制造与适配画像</small></h3>${richGrid([['平台/车型',arr(manufacturing.platform_fitment).join('、')||'未知'],['材料与工艺',manufacturing.material_process],['模具/加工',manufacturing.tooling],['SKU复杂度',manufacturing.sku_complexity],['安装要求',manufacturing.installation]])}</div><div class="rich-section"><h3>Seller Verdict <small>卖家结论</small></h3><div class="summary">${esc(t.seller_verdict||'机会假设，建议先验证。')}</div></div>${richSection('验证问题',t.validation_questions)}<div class="rich-section"><h3>Research Coverage <small>研究覆盖</small></h3>${richGrid([['帖子',coverage.posts??t.post_count],['作者',coverage.authors??t.author_count],['评论者',coverage.commenters??t.commenter_count],['证据',coverage.evidence??ev.length]])}</div><div class="evidence"><h3>帖子 / 评论证据（${ev.length}）</h3>${evidenceHtml}</div>`;
}
function updateMetrics(){const c=DATA.crawl_counts||{};metrics.textContent=`${COMMUNITIES.length} 社区 · ${TOPICS.length} 话题 · ${TOPICS.filter(t=>t.status==='formal').length} 正式 · ${Number(DATA.keyword_library?.candidates?.length||0)} 关键词 · ${TOPICS.reduce((n,t)=>n+arr(t.evidence).length,0)} 证据 · ${Number(c.saved_comments||0)} 评论`}
search.addEventListener('input',()=>{renderSide();renderGraph();});reset.addEventListener('click',closePanel);closeBtn.addEventListener('click',closePanel);svg.addEventListener('click',e=>{if(e.target===svg)closePanel();});updateMetrics();renderSide();renderGraph();
</script></body></html>'''
    html = html.replace("__PAYLOAD__", payload).replace("__MODE_NOTE__", escape(mode_note))
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
